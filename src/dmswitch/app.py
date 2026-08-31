"""The macOS app: a strip of Spaces that mirrors b2omarchy's workspaces.

Entering any Space in the strip hands the shared monitor and this Mac's
keyboard and trackpad to b2omarchy. Swiping within the strip switches
b2omarchy's workspace. Swiping left off the front of the strip lands back on
the Mac's own Spaces, which releases both.

Space membership is read with ``NSWindow.isOnActiveSpace`` alongside
NSWorkspace's active-space notification: both public API, so no private
CoreGraphics Spaces calls are needed.
"""

from __future__ import annotations

import logging
import signal

import AppKit
import objc
from Foundation import NSObject

from .capture import InputCapture
from .config import Config
from .monitor import MonitorSwitcher
from .remote import ControlClient
from .spaces import WorkspaceStrip
from .transport import EventSender

log = logging.getLogger(__name__)

# The shared monitor, matched by size. b2omarchy is on this display's other input.
TARGET_SCREEN_SIZE = (3440, 1440)

# Set by the signal handler, polled on the run loop. See checkForInterrupt_.
_interrupted = False


def _build_menu():
    """Give the app a main menu.

    Without one there is no key equivalent bound to Quit, so Cmd+Q silently
    does nothing - and since the windows are full screen their close buttons
    are hidden too, which leaves no way out at all.
    """
    main_menu = AppKit.NSMenu.alloc().init()
    app_item = AppKit.NSMenuItem.alloc().init()
    main_menu.addItem_(app_item)

    app_menu = AppKit.NSMenu.alloc().init()
    app_menu.addItemWithTitle_action_keyEquivalent_("Hide dmswitch", b"hide:", "h")
    app_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    app_menu.addItemWithTitle_action_keyEquivalent_("Quit dmswitch", b"terminate:", "q")
    app_item.setSubmenu_(app_menu)

    AppKit.NSApp().setMainMenu_(main_menu)


def _find_target_screen():
    """The shared monitor if we can identify it, else the main screen."""
    for screen in AppKit.NSScreen.screens():
        frame = screen.frame()
        if (round(frame.size.width), round(frame.size.height)) == TARGET_SCREEN_SIZE:
            return screen
    log.warning(
        "no %sx%s screen found; falling back to the main screen", *TARGET_SCREEN_SIZE
    )
    return AppKit.NSScreen.mainScreen()


class SwitcherDelegate(NSObject):
    """Owns the strip and drives the switch in and switch out transitions."""

    def initWithConfig_(self, config: Config):
        self = objc.super(SwitcherDelegate, self).init()
        if self is None:
            return None
        self.config = config
        self.sender = EventSender(config.remote)
        self.control = ControlClient(config.remote)
        self.capture = InputCapture(
            self.sender,
            scroll_divisor=config.scroll_divisor,
            on_panic=self.panic,
        )
        self.monitor = MonitorSwitcher(config.monitor, enabled=config.switch_monitor)
        self.strip = None
        self.engaged = False
        self.current_workspace = None
        self._panicked = False
        return self

    # -- lifecycle ---------------------------------------------------------

    def applicationDidFinishLaunching_(self, notification):
        _build_menu()
        self.capture.install()
        self.strip = WorkspaceStrip(_find_target_screen(), on_ready=self._strip_ready)
        self._rebuild_strip()

        AppKit.NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            self,
            b"activeSpaceChanged:",
            AppKit.NSWorkspaceActiveSpaceDidChangeNotification,
            None,
        )
        log.info("watching for Space changes")

    def applicationWillTerminate_(self, notification):
        self.disengage()
        self.control.close()
        if self.strip is not None:
            self.strip.teardown()

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return False

    # -- strip management --------------------------------------------------

    def _rebuild_strip(self):
        """Match the strip to whatever workspaces b2omarchy currently has."""
        state = self.control.workspaces()
        if not state.get("ok"):
            log.error(
                "could not read b2omarchy's workspaces (%s); using a single Space",
                state.get("error"),
            )
            workspace_ids = [1]
        else:
            workspace_ids = state.get("workspaces") or [1]
            log.info(
                "b2omarchy has workspaces %s on %s",
                workspace_ids,
                state.get("monitor"),
            )

        if self.strip.matches(workspace_ids) and self.strip.windows:
            return
        self.strip.build(workspace_ids)

    def _strip_ready(self):
        # Building leaves us on the last Space created, which would drop the
        # user at the far end of the strip. Start at the front instead, so
        # entering always means "b2omarchy's first workspace".
        if self.strip.windows:
            self.strip.windows[0].makeKeyAndOrderFront_(None)
        self.activeSpaceChanged_(None)

    # -- space transitions -------------------------------------------------

    def activeSpaceChanged_(self, notification):
        if self.strip is None or self.strip.building:
            return

        workspace_id = self.strip.active_workspace_id()
        if workspace_id is None:
            self.disengage()
            return

        self.engage()
        if self.engaged and workspace_id != self.current_workspace:
            log.info("strip Space -> b2omarchy workspace %s", workspace_id)
            self.current_workspace = workspace_id
            self.control.focus_async(workspace_id)

    def engage(self):
        """A strip Space became active: monitor and input follow."""
        if self.engaged:
            return
        # A panic stays in force until the user leaves the strip and returns.
        if self._panicked:
            log.info("still disengaged after panic; leave the strip and return to resume")
            return

        log.info("engaging")
        if self.config.forward_input:
            if not self.capture.start():
                log.error("input capture did not start; leaving the monitor alone")
                return
        else:
            log.info("input forwarding disabled; not touching the keyboard or trackpad")

        if not self.monitor.to_remote():
            # Do not strand the user looking at b2umini with a dead keyboard.
            log.error("monitor switch failed; backing out of forwarding")
            self.capture.stop()
            return

        self.engaged = True

    def disengage(self):
        """Left the strip (or shutting down): put everything back."""
        if not self.engaged:
            return
        log.info("disengaging")
        self.capture.stop()
        self.monitor.to_local()
        self.engaged = False
        self.current_workspace = None
        # Safe to resync now that we are outside the strip: adding or removing
        # a Space while the user is inside it would yank them sideways.
        if self.strip is not None and not self.strip.building:
            self._rebuild_strip()

    def panic(self):
        """Escape hatch: drop input forwarding and give the monitor back now."""
        self._panicked = True
        self.disengage()

    # -- signal handling ---------------------------------------------------

    def checkForInterrupt_(self, timer):
        """Poll the flag set by the SIGINT/SIGTERM handler.

        Python only runs signal handlers between bytecodes, and the Cocoa run
        loop sits in C, so Ctrl+C would otherwise never be noticed. This timer
        gives the interpreter a moment to breathe, and the handler itself just
        sets a flag rather than calling into AppKit from signal context.
        """
        if _interrupted:
            log.info("interrupted; shutting down")
            AppKit.NSApp().terminate_(None)


def run(config: Config | None = None) -> int:
    config = config or Config.load()
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    delegate = SwitcherDelegate.alloc().initWithConfig_(config)
    app.setDelegate_(delegate)

    def _handle_signal(signum, _frame):
        global _interrupted
        _interrupted = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Wakes the interpreter often enough for the handler above to be seen.
    AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.25, delegate, b"checkForInterrupt:", None, True
    )

    app.activateIgnoringOtherApps_(True)
    try:
        app.run()
    finally:
        delegate.disengage()
        delegate.control.close()
    return 0
