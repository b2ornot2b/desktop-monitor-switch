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
from Foundation import NSData
from Foundation import NSObject

log = logging.getLogger(__name__)


def plan_workspaces(
    existing: list[int], taken: list[int] | None = None, spares: int = 2
) -> list[int]:
    """The workspace ids the strip should cover.

    The real workspaces on the shared monitor, plus a few empty slots past the
    end so there is always somewhere to swipe into: Hyprland creates a
    workspace when one is focused, so entering a spare makes it real. Without
    this the strip dead-ends at the last existing workspace and swiping right
    silently does nothing.

    Spare ids skip anything already in use on another output, since focusing
    such a workspace would drag focus to that monitor instead.
    """
    existing = sorted(set(existing))
    taken_ids = set(taken or []) | set(existing)

    result = list(existing)
    candidate = (max(taken_ids) if taken_ids else 0) + 1
    for _ in range(max(0, spares)):
        while candidate in taken_ids:
            candidate += 1
        result.append(candidate)
        taken_ids.add(candidate)
        candidate += 1
    return result


def _window_title(workspace_id: int, remote_title: str | None) -> str:
    """What macOS shows for this Space.

    Named after what is actually on the far machine, so the Spaces are
    distinguishable at a glance rather than all reading the same.
    """
    remote_title = (remote_title or "").strip()
    if remote_title:
        return f"b2omarchy: {remote_title}"
    return f"b2omarchy: workspace {workspace_id}"


def cg_point_in_frame(x: float, y: float, frame, main_height: float) -> bool:
    """Whether a CoreGraphics event location falls inside a Cocoa screen frame.

    The two coordinate systems disagree about which way is up: CG puts the
    origin at the top left of the main display with y growing downwards, Cocoa
    at the bottom left with y growing upwards. Comparing them directly places
    the pointer on the wrong display whenever the screens are stacked
    vertically, which is exactly this setup.
    """
    cocoa_y = main_height - y
    return (
        frame.origin.x <= x < frame.origin.x + frame.size.width
        and frame.origin.y <= cocoa_y < frame.origin.y + frame.size.height
    )


def _same_screen(a, b) -> bool:
    """Whether two NSScreens are the same display.

    Compared by frame rather than identity: PyObjC hands back a fresh proxy
    object for the same display each time it is asked, so ``is`` is never true.
    """
    if a is None or b is None:
        return a is b
    fa, fb = a.frame(), b.frame()
    return (
        fa.origin.x == fb.origin.x
        and fa.origin.y == fb.origin.y
        and fa.size.width == fb.size.width
        and fa.size.height == fb.size.height
    )


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
        self.image_views: dict[int, object] = {}
        self.labels: dict[int, object] = {}
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
        # initWithContentRect:...screen: measures the rect from the *screen's*
        # origin, not the global one. Passing a global frame therefore doubles
        # the offset on any display that is not at (0,0), leaving the window
        # hanging off the side - and full screen then lands on whichever
        # display holds most of it, which may be the wrong one. Build it at the
        # origin and position it afterwards, where coordinates are global.
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_screen_(
            AppKit.NSMakeRect(0, 0, frame.size.width, frame.size.height),
            AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskFullSizeContentView,
            AppKit.NSBackingStoreBuffered,
            False,
            self.screen,
        )
        window.setFrame_display_(frame, False)
        window.setTitle_(_window_title(workspace_id, None))
        window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorFullScreenPrimary)
        window.setTitlebarAppearsTransparent_(True)
        window.setBackgroundColor_(AppKit.NSColor.blackColor())
        window.setDelegate_(self._delegate)
        window.setReleasedWhenClosed_(False)

        # Behind everything: the last snapshot of this workspace, so the
        # Space is recognisable in Mission Control instead of a black square.
        image_view = AppKit.NSImageView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, frame.size.width, frame.size.height)
        )
        image_view.setImageScaling_(AppKit.NSImageScaleProportionallyUpOrDown)
        image_view.setAutoresizingMask_(
            AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable
        )
        window.contentView().addSubview_(image_view)
        self.image_views[workspace_id] = image_view

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
        self.labels[workspace_id] = label

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
        # Worth logging: a Space landing on the wrong display is invisible from
        # the app's point of view but very obvious to the person using it.
        landed = window.screen()
        if landed is not None and not _same_screen(landed, self.screen):
            log.error(
                "workspace %s Space opened on %s, expected %s",
                window.identifier(),
                landed.localizedName(),
                self.screen.localizedName(),
            )
        else:
            log.debug(
                "workspace %s Space is on %s",
                window.identifier(),
                landed.localizedName() if landed else "?",
            )
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
        self.image_views = {}
        self.labels = {}
        self._pending = []
        self.building = False

    def set_title(self, workspace_id: int, remote_title: str | None) -> bool:
        """Rename a Space after whatever b2omarchy is showing on it."""
        for window in self.windows:
            identifier = window.identifier()
            if identifier and int(identifier) == workspace_id:
                window.setTitle_(_window_title(workspace_id, remote_title))
                label = self.labels.get(workspace_id)
                if label is not None and not label.isHidden():
                    label.setStringValue_(
                        f"b2omarchy\nworkspace {workspace_id}"
                        + (f"\n{remote_title}" if remote_title else "")
                    )
                return True
        return False

    def set_tile(self, workspace_id: int, jpeg: bytes) -> bool:
        """Show a snapshot as the background of a workspace's Space.

        Must be called on the main thread: AppKit is not thread safe, and the
        capture arrives on the control worker.
        """
        view = self.image_views.get(workspace_id)
        if view is None:
            return False
        data = NSData.dataWithBytes_length_(jpeg, len(jpeg))
        image = AppKit.NSImage.alloc().initWithData_(data)
        if image is None:
            log.warning("workspace %s tile was not a usable image", workspace_id)
            return False
        view.setImage_(image)
        # The caption is only there to explain an empty Space; once there is a
        # picture it just gets in the way.
        label = self.labels.get(workspace_id)
        if label is not None:
            label.setHidden_(True)
        return True

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
