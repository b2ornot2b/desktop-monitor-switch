"""A strip of macOS Spaces, one per b2omarchy workspace.

Each workspace on the shared monitor gets its own full-screen window, and a
full-screen window is its own Space. macOS then places them side by side just
past the Mac's own Spaces, so the two machines read as one continuous strip:

    [mac 1] [mac 2] ... [mac last] | [ws1] [ws2] [ws3]

Swiping is handled entirely by macOS. All this code does is notice which
window is on the active Space and tell b2omarchy to match. That is why there
is no gesture interception anywhere in this project: the system's own Space
gesture cannot be suppressed by an event tap, so instead of fighting it we
give it something useful to switch between.

Swiping left off the first strip Space lands on the Mac's own last Space,
which is exactly the "leave b2omarchy" behaviour, for free.
"""

from __future__ import annotations

import logging

import AppKit
import objc
from Foundation import NSObject

log = logging.getLogger(__name__)


class StripWindowDelegate(NSObject):
    """Reports when a window has finished becoming its own Space."""

    def initWithCallback_(self, callback):
        self = objc.super(StripWindowDelegate, self).init()
        if self is None:
            return None
        self._callback = callback
        return self

    def windowDidEnterFullScreen_(self, notification):
        if self._callback:
            self._callback(notification.object())

    def windowDidFailToEnterFullScreen_(self, window):
        log.error("a strip window failed to enter full screen")
        if self._callback:
            self._callback(window)


class WorkspaceStrip:
    """Owns the full-screen windows that mirror b2omarchy's workspaces."""

    def __init__(self, screen, on_ready=None):
        self.screen = screen
        self.on_ready = on_ready
        self.windows: list = []
        self.workspace_ids: list[int] = []
        self._delegate = StripWindowDelegate.alloc().initWithCallback_(
            self._window_entered_full_screen
        )
        self._pending: list = []
        self.building = False

    # -- construction ------------------------------------------------------

    def build(self, workspace_ids: list[int]) -> None:
        """Create one full-screen Space per workspace id, in order.

        Entering full screen is animated and asynchronous, so the windows are
        taken one at a time: starting the next before the previous has settled
        makes macOS put them in the wrong order, or refuse outright.
        """
        self.teardown()
        self.workspace_ids = list(workspace_ids)
        if not self.workspace_ids:
            log.warning("b2omarchy reported no workspaces; strip is empty")
            if self.on_ready:
                self.on_ready()
            return

        log.info("building a Space per workspace: %s", self.workspace_ids)
        self.building = True
        for workspace_id in self.workspace_ids:
            self.windows.append(self._make_window(workspace_id))
        self._pending = list(self.windows)
        self._enter_next_full_screen()

    def _make_window(self, workspace_id: int):
        frame = self.screen.frame()
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_screen_(
            frame,
            AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskFullSizeContentView,
            AppKit.NSBackingStoreBuffered,
            False,
            self.screen,
        )
        window.setTitle_(f"b2omarchy · workspace {workspace_id}")
        window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorFullScreenPrimary)
        window.setTitlebarAppearsTransparent_(True)
        window.setBackgroundColor_(AppKit.NSColor.blackColor())
        window.setDelegate_(self._delegate)
        window.setReleasedWhenClosed_(False)

        label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, frame.size.height / 2 - 60, frame.size.width, 120)
        )
        label.setStringValue_(
            f"b2omarchy\nworkspace {workspace_id}\n\n"
            "⌘Q quit · ⌃⌥⌘⎋ panic · swipe left past the first to return"
        )
        label.setAlignment_(AppKit.NSTextAlignmentCenter)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        label.setFont_(AppKit.NSFont.systemFontOfSize_(28))
        window.contentView().addSubview_(label)

        # objc associates the id with the window so lookups stay simple.
        window.setIdentifier_(str(workspace_id))
        return window

    def _enter_next_full_screen(self) -> None:
        if not self._pending:
            self.building = False
            log.info("strip ready: %d Space(s)", len(self.windows))
            if self.on_ready:
                self.on_ready()
            return
        window = self._pending[0]
        window.makeKeyAndOrderFront_(None)
        window.toggleFullScreen_(None)

    def _window_entered_full_screen(self, window) -> None:
        if self._pending and window is self._pending[0]:
            self._pending.pop(0)
            self._enter_next_full_screen()

    def teardown(self) -> None:
        for window in self.windows:
            try:
                window.setDelegate_(None)
                window.close()
            except Exception:
                log.debug("failed to close a strip window", exc_info=True)
        self.windows = []
        self.workspace_ids = []
        self._pending = []
        self.building = False

    # -- queries -----------------------------------------------------------

    def active_workspace_id(self) -> int | None:
        """Which workspace the currently visible Space maps to, if any."""
        if self.building:
            return None
        for window in self.windows:
            try:
                if window.isOnActiveSpace():
                    identifier = window.identifier()
                    return int(identifier) if identifier else None
            except Exception:
                log.debug("could not read a strip window's Space", exc_info=True)
        return None

    def matches(self, workspace_ids: list[int]) -> bool:
        return list(workspace_ids) == self.workspace_ids
