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
import threading

import AppKit
import objc
from Foundation import NSObject

from .capture import InputCapture
from .config import Config
from .monitor import MonitorSwitcher
from .remote import ControlClient
from .spaces import WorkspaceStrip, cg_point_in_frame, plan_workspaces
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
            freeze_local_cursor=config.freeze_local_cursor,
            pointer_is_remote=self.pointerIsOverSharedMonitor,
        )
        self.monitor = MonitorSwitcher(config.monitor, enabled=config.switch_monitor)
        self.strip = None
        self.engaged = False
        self.current_workspace = None
        self._panicked = False
        # Set while starting hidden: blocks engaging until the strip has
        # actually been left once, since hiding is asynchronous and any
        # evaluation before it lands still sees a strip Space.
        self._awaiting_first_exit = False
        # Captured tiles land here from the control worker and are applied on
        # the main thread, since AppKit must not be touched from elsewhere.
        self._pending_tiles: dict[int, tuple] = {}
        self._tiles_lock = threading.Lock()
        self.control.set_tile_handler(self._tile_captured)
        self.control.tile_scale = config.tile_scale
        self.control.tile_quality = config.tile_quality
        self.control.tile_format = config.tile_format
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
        # Space membership alone is not enough to know the user is here. With
        # "Displays have separate Spaces" each display keeps its own active
        # Space, so a strip Space can stay frontmost on the shared monitor
        # while the user works on the other display - and holding their
        # keyboard hostage in that state is exactly the wrong thing to do.
        centre = AppKit.NSNotificationCenter.defaultCenter()
        centre.addObserver_selector_name_object_(
            self, b"appActivationChanged:", AppKit.NSApplicationDidResignActiveNotification, None
        )
        centre.addObserver_selector_name_object_(
            self, b"appActivationChanged:", AppKit.NSApplicationDidBecomeActiveNotification, None
        )
        log.info("watching for Space and activation changes")

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
            existing = state.get("workspaces") or [1]
            workspace_ids = plan_workspaces(
                existing,
                taken=state.get("taken"),
                spares=self.config.spare_workspaces,
            )
            log.info(
                "b2omarchy has workspaces %s on %s; strip covers %s",
                existing,
                state.get("monitor"),
                workspace_ids,
            )

        titles = (state.get("titles") or {}) if state.get("ok") else {}
        if self.strip.matches(workspace_ids) and self.strip.windows:
            self._apply_titles(titles)
            return
        self.strip.build(workspace_ids)
        self._pending_titles = titles

    @objc.python_method
    def _apply_titles(self, titles: dict):
        """Name each Space after what b2omarchy has on that workspace."""
        for key, title in (titles or {}).items():
            try:
                self.strip.set_title(int(key), title)
            except (TypeError, ValueError):
                continue

    def _strip_ready(self):
        self._apply_titles(getattr(self, "_pending_titles", {}))
        if self.config.start_hidden:
            # Creating full-screen Spaces switches to them, so at login this
            # would dump the user into b2omarchy uninvited. Step back out and
            # wait to be swiped to.
            log.info("strip built; staying out of the way until you swipe to it")
            self._awaiting_first_exit = True
            AppKit.NSApp().hide_(None)
            # Deliberately no re-evaluation here: hiding switches Space
            # asynchronously, so asking now would still see a strip Space and
            # engage - exactly what this flag exists to avoid. The
            # active-space notification arrives once the switch completes.
            return
        # Building leaves us on the last Space created, which would drop the
        # user at the far end of the strip. Start at the front instead, so
        # entering always means "b2omarchy's first workspace".
        if self.strip.windows:
            self.strip.windows[0].makeKeyAndOrderFront_(None)
        self._reevaluate("strip-ready")

    # -- space transitions -------------------------------------------------

    def appActivationChanged_(self, notification):
        """The user moved to or from another app - possibly on another display."""
        self._reevaluate(notification.name() if notification else "activation")

    def activeSpaceChanged_(self, notification):
        self._reevaluate("space-change" if notification else "manual")

    @objc.python_method
    def _reevaluate(self, reason: str):
        # objc.python_method keeps this off the Objective-C side: PyObjC would
        # otherwise try to expose it as a zero-argument selector and refuse.
        if self.strip is None or self.strip.building:
            return

        workspace_id = self.strip.active_workspace_id()
        log.debug(
            "reevaluate (%s): workspace=%s engaged=%s",
            reason,
            workspace_id,
            self.engaged,
        )

        # Only the Space matters here. Whether input actually goes to
        # b2omarchy is decided per event by where the pointer is, so the
        # monitor can keep showing b2omarchy while this Mac is being used on
        # the other display.
        if workspace_id is None:
            if self.engaged:
                log.info("releasing because the strip Space is no longer showing")
            if self._awaiting_first_exit:
                log.debug("left the strip; ready to engage when swiped to")
                self._awaiting_first_exit = False
            self.disengage()
            return

        if self._awaiting_first_exit:
            # Started hidden and the Space has not moved off us yet.
            log.debug("not engaging yet: waiting to leave the strip first")
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

        # b2omarchy's output sleeps while the monitor is showing this Mac, so
        # wake it before handing the monitor over - otherwise the input
        # switches to a display that is not sending a picture.
        woken = self.control.wake()
        if not woken.get("ok"):
            log.warning(
                "could not wake b2omarchy's output (%s); the monitor may show nothing",
                woken.get("error"),
            )

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
        # Snapshot what is being left behind *before* the monitor goes back:
        # once the input switches away the output sleeps and capture fails.
        if self.current_workspace is not None:
            self.control.capture_async(self.current_workspace)
        self.capture.stop()
        self.monitor.to_local()
        self.engaged = False
        self.current_workspace = None
        # Safe to resync now that we are outside the strip: adding or removing
        # a Space while the user is inside it would yank them sideways.
        if self.strip is not None and not self.strip.building:
            self._rebuild_strip()

    @objc.python_method
    def pointerIsOverSharedMonitor(self, location) -> bool:
        """Whether the pointer is on the shared monitor right now.

        Used to decide, per event, whether input belongs to b2omarchy or to
        this Mac. Moving the pointer to the other display hands input back
        without disturbing what the shared monitor is showing.
        """
        if self.strip is None or self.strip.screen is None:
            return True
        screens = AppKit.NSScreen.screens()
        if not screens:
            return True
        main_height = screens[0].frame().size.height
        return cg_point_in_frame(
            location.x, location.y, self.strip.screen.frame(), main_height
        )

    def panic(self):
        """Escape hatch: drop input forwarding and give the monitor back now."""
        self._panicked = True
        self.disengage()

    # -- workspace tiles ---------------------------------------------------

    @objc.python_method
    def _tile_captured(self, workspace_id: int, jpeg: bytes | None, title: str = ""):
        """Called on the control worker thread; hand off to the main thread."""
        with self._tiles_lock:
            self._pending_tiles[workspace_id] = (jpeg, title)
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            b"applyPendingTiles:", None, False
        )

    def applyPendingTiles_(self, _ignored):
        if self.strip is None:
            return
        with self._tiles_lock:
            pending = dict(self._pending_tiles)
            self._pending_tiles.clear()
        for workspace_id, (jpeg, title) in pending.items():
            if title:
                self.strip.set_title(workspace_id, title)
            if jpeg and self.strip.set_tile(workspace_id, jpeg):
                log.debug("updated tile for workspace %s", workspace_id)

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
