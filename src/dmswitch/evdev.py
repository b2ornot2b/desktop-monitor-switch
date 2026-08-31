"""Linux evdev wire format and macOS -> Linux input code translation.

Events are sent to b2omarchy as raw ``struct input_event`` records, which is
exactly what ydotoold reads off its unix datagram socket. Keeping that format
end to end means the receiver is a relay and never has to interpret anything.
"""

from __future__ import annotations

import struct

# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
# On 64-bit Linux timeval is two 64-bit longs, so the record is 24 bytes.
EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02

SYN_REPORT = 0

REL_X = 0x00
REL_Y = 0x01
REL_HWHEEL = 0x06
REL_WHEEL = 0x08

BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113
BTN_EXTRA = 0x114

KEY_PRESS = 1
KEY_RELEASE = 0


def pack_event(ev_type: int, code: int, value: int) -> bytes:
    """Pack one input_event. Timestamps are zero: the kernel fills them in."""
    return struct.pack(EVENT_FORMAT, 0, 0, ev_type, code, value)


def unpack_event(data: bytes) -> tuple[int, int, int]:
    """Return ``(type, code, value)`` from a packed input_event."""
    _sec, _usec, ev_type, code, value = struct.unpack(EVENT_FORMAT, data)
    return ev_type, code, value


def sync() -> bytes:
    """A SYN_REPORT, which tells the kernel a batch of events is complete."""
    return pack_event(EV_SYN, SYN_REPORT, 0)


# Linux key codes we care about, from input-event-codes.h.
KEY_ESC = 1
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_LEFTSHIFT = 42
KEY_RIGHTSHIFT = 54
KEY_KPASTERISK = 55
KEY_LEFTALT = 56
KEY_SPACE = 57
KEY_CAPSLOCK = 58
KEY_NUMLOCK = 69
KEY_KPMINUS = 74
KEY_KPPLUS = 78
KEY_KPDOT = 83
KEY_KPENTER = 96
KEY_RIGHTCTRL = 97
KEY_KPSLASH = 98
KEY_RIGHTALT = 100
KEY_HOME = 102
KEY_UP = 103
KEY_PAGEUP = 104
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_END = 107
KEY_DOWN = 108
KEY_PAGEDOWN = 109
KEY_INSERT = 110
KEY_DELETE = 111
KEY_MUTE = 113
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115
KEY_KPEQUAL = 117
KEY_LEFTMETA = 125
KEY_RIGHTMETA = 126

# macOS virtual key code (kVK_*) -> Linux key code.
#
# Deliberately keyed on physical position, not the character produced, because
# evdev is positional too: the layout is applied on the far side by XKB.
MAC_TO_LINUX_KEY: dict[int, int] = {
    # Letters
    0x00: 30,  # A
    0x0B: 48,  # B
    0x08: 46,  # C
    0x02: 32,  # D
    0x0E: 18,  # E
    0x03: 33,  # F
    0x05: 34,  # G
    0x04: 35,  # H
    0x22: 23,  # I
    0x26: 36,  # J
    0x28: 37,  # K
    0x25: 38,  # L
    0x2E: 50,  # M
    0x2D: 49,  # N
    0x1F: 24,  # O
    0x23: 25,  # P
    0x0C: 16,  # Q
    0x0F: 19,  # R
    0x01: 31,  # S
    0x11: 20,  # T
    0x20: 22,  # U
    0x09: 47,  # V
    0x0D: 17,  # W
    0x07: 45,  # X
    0x10: 21,  # Y
    0x06: 44,  # Z
    # Number row
    0x12: 2,   # 1
    0x13: 3,   # 2
    0x14: 4,   # 3
    0x15: 5,   # 4
    0x17: 6,   # 5
    0x16: 7,   # 6
    0x1A: 8,   # 7
    0x1C: 9,   # 8
    0x19: 10,  # 9
    0x1D: 11,  # 0
    0x1B: 12,  # minus
    0x18: 13,  # equal
    # Punctuation and structure
    0x21: 26,  # [
    0x1E: 27,  # ]
    0x2A: 43,  # backslash
    0x29: 39,  # ;
    0x27: 40,  # '
    0x32: 41,  # `
    0x2B: 51,  # ,
    0x2F: 52,  # .
    0x2C: 53,  # /
    0x24: KEY_ENTER,
    0x30: KEY_TAB,
    0x31: KEY_SPACE,
    0x33: KEY_BACKSPACE,
    0x35: KEY_ESC,
    # Modifiers
    0x37: KEY_LEFTMETA,   # left command
    0x36: KEY_RIGHTMETA,  # right command
    0x38: KEY_LEFTSHIFT,
    0x3C: KEY_RIGHTSHIFT,
    0x3A: KEY_LEFTALT,    # left option
    0x3D: KEY_RIGHTALT,   # right option
    0x3B: KEY_LEFTCTRL,
    0x3E: KEY_RIGHTCTRL,
    0x39: KEY_CAPSLOCK,
    # Navigation
    0x7B: KEY_LEFT,
    0x7C: KEY_RIGHT,
    0x7D: KEY_DOWN,
    0x7E: KEY_UP,
    0x73: KEY_HOME,
    0x77: KEY_END,
    0x74: KEY_PAGEUP,
    0x79: KEY_PAGEDOWN,
    0x75: KEY_DELETE,      # forward delete
    0x72: KEY_INSERT,      # help/insert
    # Function row
    0x7A: 59,   # F1
    0x78: 60,   # F2
    0x63: 61,   # F3
    0x76: 62,   # F4
    0x60: 63,   # F5
    0x61: 64,   # F6
    0x62: 65,   # F7
    0x64: 66,   # F8
    0x65: 67,   # F9
    0x6D: 68,   # F10
    0x67: 87,   # F11
    0x6F: 88,   # F12
    0x69: 183,  # F13
    0x6B: 184,  # F14
    0x71: 185,  # F15
    0x6A: 186,  # F16
    0x40: 187,  # F17
    0x4F: 188,  # F18
    0x50: 189,  # F19
    0x5A: 190,  # F20
    # Keypad
    0x52: 82,  # KP0
    0x53: 79,  # KP1
    0x54: 80,  # KP2
    0x55: 81,  # KP3
    0x56: 75,  # KP4
    0x57: 76,  # KP5
    0x58: 77,  # KP6
    0x59: 71,  # KP7
    0x5B: 72,  # KP8
    0x5C: 73,  # KP9
    0x41: KEY_KPDOT,
    0x43: KEY_KPASTERISK,
    0x45: KEY_KPPLUS,
    0x4E: KEY_KPMINUS,
    0x4B: KEY_KPSLASH,
    0x4C: KEY_KPENTER,
    0x51: KEY_KPEQUAL,
    0x47: KEY_NUMLOCK,  # clear
    # Media
    0x48: KEY_VOLUMEUP,
    0x49: KEY_VOLUMEDOWN,
    0x4A: KEY_MUTE,
}

# macOS modifier flag masks (NSEvent / CGEventFlags), used to work out whether a
# flagsChanged event is a press or a release.
FLAG_CAPSLOCK = 0x00010000
FLAG_SHIFT = 0x00020000
FLAG_CONTROL = 0x00040000
FLAG_ALTERNATE = 0x00080000
FLAG_COMMAND = 0x00100000

# Device-dependent bits, which are what distinguish left from right.
MODIFIER_FLAG_BY_MAC_KEY: dict[int, int] = {
    0x38: 0x0002,  # left shift
    0x3C: 0x0004,  # right shift
    0x3B: 0x0001,  # left control
    0x3E: 0x2000,  # right control
    0x3A: 0x0020,  # left option
    0x3D: 0x0040,  # right option
    0x37: 0x0008,  # left command
    0x36: 0x0010,  # right command
}

# macOS mouse button number -> Linux button code.
MOUSE_BUTTON_TO_LINUX: dict[int, int] = {
    0: BTN_LEFT,
    1: BTN_RIGHT,
    2: BTN_MIDDLE,
    3: BTN_SIDE,
    4: BTN_EXTRA,
}


def key_event(linux_key: int, pressed: bool) -> bytes:
    """A key press or release, followed by the SYN_REPORT that commits it."""
    return pack_event(EV_KEY, linux_key, KEY_PRESS if pressed else KEY_RELEASE) + sync()


def rel_move(dx: int, dy: int) -> bytes:
    """Relative pointer motion. Axes with no movement are omitted."""
    out = b""
    if dx:
        out += pack_event(EV_REL, REL_X, dx)
    if dy:
        out += pack_event(EV_REL, REL_Y, dy)
    return out + sync() if out else b""


def scroll(dx: int, dy: int) -> bytes:
    """Wheel motion, in detents."""
    out = b""
    if dy:
        out += pack_event(EV_REL, REL_WHEEL, dy)
    if dx:
        out += pack_event(EV_REL, REL_HWHEEL, dx)
    return out + sync() if out else b""
