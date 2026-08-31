"""Captures keyboard and pointer input on macOS and forwards it to b2omarchy.

Uses an active CGEventTap, which both observes events and swallows them, so a
keystroke goes to b2omarchy instead of to whatever is focused locally. This
needs Accessibility permission for whichever binary hosts the process.

Deliberately *not* captured: swipe and other gesture events. They stay with
macOS so the trackpad can always swipe back out of the dedicated Space, which
doubles as the escape hatch if forwarding ever misbehaves.
"""

from __future__ import annotations

import logging

import Quartz

from . import evdev
from .transport import EventSender

log = logging.getLogger(__name__)

# Chosen to be awkward to hit by accident. Never forwarded, never suppressed.
PANIC_KEYCODE = 0x35  # escape
PANIC_FLAGS = (
    evdev.FLAG_CONTROL | evdev.FLAG_ALTERNATE | evdev.FLAG_COMMAND
)

_CAPTURED_EVENTS = (
    Quartz.kCGEventKeyDown,
    Quartz.kCGEventKeyUp,
    Quartz.kCGEventFlagsChanged,
    Quartz.kCGEventMouseMoved,
    Quartz.kCGEventLeftMouseDown,
    Quartz.kCGEventLeftMouseUp,
    Quartz.kCGEventLeftMouseDragged,
    Quartz.kCGEventRightMouseDown,
    Quartz.kCGEventRightMouseUp,
    Quartz.kCGEventRightMouseDragged,
    Quartz.kCGEventOtherMouseDown,
    Quartz.kCGEventOtherMouseUp,
    Quartz.kCGEventOtherMouseDragged,
    Quartz.kCGEventScrollWheel,
)

_EVENT_MASK = 0
for _event in _CAPTURED_EVENTS:
    _EVENT_MASK |= Quartz.CGEventMaskBit(_event)


class InputCapture:
    """Owns the event tap and translates each event into evdev records."""

    def __init__(self, sender: EventSender, scroll_divisor: float = 3.0, on_panic=None):
        self.sender = sender
        self.scroll_divisor = scroll_divisor
        self.on_panic = on_panic
        self._tap = None
        self._source = None
        self._active = False
        self._modifier_state: dict[int, bool] = {}

    @property
    def active(self) -> bool:
        return self._active

    def install(self) -> bool:
        """Create the tap and attach it to the current run loop, left disabled."""
        if self._tap is not None:
            return True

        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,  # active tap: we may suppress
            _EVENT_MASK,
            self._callback,
            None,
        )
        if not tap:
            log.error(
                "could not create event tap. Grant Accessibility permission to the "
                "binary running this (System Settings > Privacy & Security > Accessibility)."
            )
            return False

        self._tap = tap
        self._source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(), self._source, Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(tap, False)
        log.info("event tap installed (idle)")
        return True

    def start(self) -> bool:
        """Begin capturing, and freeze the local cursor so it stops wandering."""
        if self._tap is None and not self.install():
            return False
        if self._active:
            return True
        if not self.sender.connect():
            return False

        self._modifier_state.clear()
        Quartz.CGEventTapEnable(self._tap, True)
        # Detach the on-screen cursor from mouse movement. Deltas still arrive,
        # so b2omarchy sees the motion while the local pointer stays put.
        Quartz.CGAssociateMouseAndMouseCursorPosition(False)
        self._active = True
        log.info("forwarding input to remote")
        return True

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        if self._tap is not None:
            Quartz.CGEventTapEnable(self._tap, False)
        Quartz.CGAssociateMouseAndMouseCursorPosition(True)
        # Order matters: release held keys while the socket is still open.
        self.sender.disconnect()
        log.info("stopped forwarding input")

    def _callback(self, proxy, event_type, event, refcon):
        # The system disables a tap that takes too long. Put it back only if we
        # actually want it live: we also disable the tap ourselves when idle,
        # and that fires this same notification.
        if event_type in (
            Quartz.kCGEventTapDisabledByTimeout,
            Quartz.kCGEventTapDisabledByUserInput,
        ):
            if self._active and self._tap is not None:
                log.warning("event tap was disabled by the system; re-enabling")
                Quartz.CGEventTapEnable(self._tap, True)
            return event

        if not self._active:
            return event

        try:
            if self._is_panic(event_type, event):
                log.warning("panic combo pressed; releasing input")
                if self.on_panic:
                    self.on_panic()
                else:
                    self.stop()
                return None

            handled = self._forward(event_type, event)
        except Exception:  # never let a bug wedge the user's input
            log.exception("error forwarding event; passing it through locally")
            return event

        # Suppressing means the keystroke does not also land on the Mac.
        return None if handled else event

    def _is_panic(self, event_type, event) -> bool:
        if event_type != Quartz.kCGEventKeyDown:
            return False
        keycode = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventKeycode
        )
        if keycode != PANIC_KEYCODE:
            return False
        flags = Quartz.CGEventGetFlags(event)
        return (flags & PANIC_FLAGS) == PANIC_FLAGS

    def _forward(self, event_type, event) -> bool:
        if event_type in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp):
            keycode = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode
            )
            linux_key = evdev.MAC_TO_LINUX_KEY.get(keycode)
            if linux_key is None:
                log.debug("unmapped macOS keycode %s", keycode)
                return False
            # Ignore auto-repeat: the far side repeats on its own from the
            # held-down state, so forwarding repeats would double up.
            if event_type == Quartz.kCGEventKeyDown and Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventAutorepeat
            ):
                return True
            return self.sender.send_key(
                linux_key, pressed=event_type == Quartz.kCGEventKeyDown
            )

        if event_type == Quartz.kCGEventFlagsChanged:
            return self._forward_modifier(event)

        if event_type in (
            Quartz.kCGEventMouseMoved,
            Quartz.kCGEventLeftMouseDragged,
            Quartz.kCGEventRightMouseDragged,
            Quartz.kCGEventOtherMouseDragged,
        ):
            dx = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventDeltaX)
            dy = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventDeltaY)
            return self.sender.send_move(int(dx), int(dy))

        if event_type in (
            Quartz.kCGEventLeftMouseDown,
            Quartz.kCGEventLeftMouseUp,
            Quartz.kCGEventRightMouseDown,
            Quartz.kCGEventRightMouseUp,
            Quartz.kCGEventOtherMouseDown,
            Quartz.kCGEventOtherMouseUp,
        ):
            button = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGMouseEventButtonNumber
            )
            linux_button = evdev.MOUSE_BUTTON_TO_LINUX.get(int(button))
            if linux_button is None:
                return False
            pressed = event_type in (
                Quartz.kCGEventLeftMouseDown,
                Quartz.kCGEventRightMouseDown,
                Quartz.kCGEventOtherMouseDown,
            )
            return self.sender.send_key(linux_button, pressed=pressed)

        if event_type == Quartz.kCGEventScrollWheel:
            dy = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGScrollWheelEventDeltaAxis1
            )
            dx = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGScrollWheelEventDeltaAxis2
            )
            return self.sender.send_scroll(int(dx), int(dy))

        return False

    def _forward_modifier(self, event) -> bool:
        """Turn a flagsChanged event into a press or release.

        macOS reports the new flag state rather than a direction, so the
        device-dependent bit for that specific key decides which it was.
        """
        keycode = int(
            Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        )
        linux_key = evdev.MAC_TO_LINUX_KEY.get(keycode)
        if linux_key is None:
            return False

        mask = evdev.MODIFIER_FLAG_BY_MAC_KEY.get(keycode)
        flags = Quartz.CGEventGetFlags(event)
        if mask is not None:
            pressed = bool(flags & mask)
        else:
            # Caps lock and anything else without a left/right bit: just toggle.
            pressed = not self._modifier_state.get(keycode, False)

        self._modifier_state[keycode] = pressed
        return self.sender.send_key(linux_key, pressed=pressed)
