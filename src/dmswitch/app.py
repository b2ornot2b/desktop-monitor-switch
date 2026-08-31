"""The macOS app: a full-screen window that owns the last Space.

When that Space becomes active the monitor flips to b2omarchy and keyboard and
trackpad start forwarding; when it stops being active both revert.

Space membership is detected with ``NSWindow.isOnActiveSpace`` together with
NSWorkspace's active-space-change notification. Both are public API, so no
private CoreGraphics Spaces calls are needed.
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
from .transport import EventSender

log = logging.getLogger(__name__)

# The shared monitor, matched by size. b2omarchy is on this display's other input.
TARGET_SCREEN_SIZE = (3440, 1440)

# Set by the signal handler, polled on the run loop. See checkForInterrupt_.
_interrupted = False


def _build_menu():
    """Give the app a main menu.

    Without one there is no key equivalent bound to Quit, so Cmd+Q silently
    does nothing - and since the window is full screen its close button is
    hidden too, which leaves no way out at all.
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
    """Owns the window and drives the switch in and switch out transitions."""

    def initWithConfig_(self, config: Config):
        self = objc.super(SwitcherDelegate, self).init()
        if self is None:
            return None
        self.config = config
        self.sender = EventSender(config.remote)
        self.capture = InputCapture(
            self.sender,
            scroll_divisor=config.scroll_divisor,
            on_panic=self.panic,
        )
        self.monitor = MonitorSwitcher(config.monitor, enabled=config.switch_monitor)
        self.window = None
        self.status_label = None
        self.engaged = False
        self._panicked = False
        return self

    # -- lifecycle ---------------------------------------------------------

    def applicationDidFinishLaunching_(self, notification):
        _build_menu()
        self._build_window()
        self.capture.install()

        AppKit.NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            self,
            b"activeSpaceChanged:",
            AppKit.NSWorkspaceActiveSpaceDidChangeNotification,
            None,
        )
        log.info("watching for Space changes")
        # The window may already be on the active Space at launch.
        self.activeSpaceChanged_(None)

    def applicationWillTerminate_(self, notification):
        self.disengage()

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return True

    def _build_window(self):
        screen = _find_target_screen()
        frame = screen.frame()
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_screen_(
            frame,
            AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskFullSizeContentView,
            AppKit.NSBackingStoreBuffered,
            False,
            screen,
        )
        window.setTitle_("b2omarchy")
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorFullScreenPrimary
        )
        window.setTitlebarAppearsTransparent_(True)
        window.setBackgroundColor_(AppKit.NSColor.blackColor())

        label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, frame.size.height / 2 - 40, frame.size.width, 80)
        )
        label.setStringValue_(
            "b2omarchy\nidle\n\n⌘Q quit · ⌃⌥⌘⎋ panic · swipe back to return"
        )
        label.setAlignment_(AppKit.NSTextAlignmentCenter)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        label.setFont_(AppKit.NSFont.systemFontOfSize_(28))
        window.contentView().addSubview_(label)
        self.status_label = label

        window.makeKeyAndOrderFront_(None)
        # Its own full-screen Space, which is the Space we then watch for.
        window.toggleFullScreen_(None)
        self.window = window

    # -- space transitions -------------------------------------------------

    def activeSpaceChanged_(self, notification):
        if self.window is None:
            return
        on_active = bool(self.window.isOnActiveSpace())
        log.debug("active space changed; ours is active: %s", on_active)
        if on_active:
            self.engage()
        else:
            self.disengage()

    def engage(self):
        """Our Space became active: monitor and input follow."""
        if self.engaged:
            return
        # A panic stays in force until the user leaves the Space and comes back.
        if self._panicked:
            log.info("still disengaged after panic; leave and re-enter the Space to resume")
            return

        log.info("engaging")
        if self.config.forward_input:
            if not self.capture.start():
                self._set_status("could not forward input - check the receiver and permissions")
                log.error("input capture did not start; leaving the monitor alone")
                return
        else:
            log.info("input forwarding disabled; not touching the keyboard or trackpad")

        if not self.monitor.to_remote():
            # Do not strand the user looking at b2umini with a dead keyboard.
            log.error("monitor switch failed; backing out of forwarding")
            self.capture.stop()
            self._set_status("monitor switch failed")
            return

        self.engaged = True
        self._set_status(
            "forwarding to b2omarchy" if self.config.forward_input else "engaged (input forwarding off)"
        )

    def disengage(self):
        """Left our Space (or shutting down): put everything back."""
        if not self.engaged:
            return
        log.info("disengaging")
        self.capture.stop()
        self.monitor.to_local()
        self.engaged = False
        self._set_status("idle")

    def panic(self):
        """Escape hatch: drop input forwarding and give the monitor back now."""
        self._panicked = True
        self.disengage()
        self._set_status("panic - forwarding released")

    def _set_status(self, text: str):
        if self.status_label is not None:
            self.status_label.setStringValue_(
                f"b2omarchy\n{text}\n\n⌘Q quit · ⌃⌥⌘⎋ panic · swipe back to return"
            )

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
            self.disengage()
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
    return 0
