"""Tests for the wire format and keycode translation.

These cover the parts that must be right for the far side to interpret events
correctly, and that can be checked without a Mac event tap or a Linux uinput
device in the loop.
"""

from __future__ import annotations

import struct

import pytest

from dmswitch import evdev


def test_event_record_is_24_bytes():
    # ydotoold reads struct input_event as the kernel lays it out on 64-bit.
    assert evdev.EVENT_SIZE == 24


def test_pack_and_unpack_round_trip():
    packed = evdev.pack_event(evdev.EV_KEY, 30, 1)
    assert len(packed) == evdev.EVENT_SIZE
    assert evdev.unpack_event(packed) == (evdev.EV_KEY, 30, 1)


def test_packed_layout_matches_kernel_struct():
    packed = evdev.pack_event(evdev.EV_REL, evdev.REL_X, -5)
    sec, usec, ev_type, code, value = struct.unpack("llHHi", packed)
    assert (sec, usec) == (0, 0)  # kernel fills timestamps in
    assert (ev_type, code, value) == (evdev.EV_REL, evdev.REL_X, -5)


def test_key_event_is_terminated_by_sync():
    payload = evdev.key_event(evdev.KEY_ENTER, pressed=True)
    assert len(payload) == 2 * evdev.EVENT_SIZE
    assert evdev.unpack_event(payload[: evdev.EVENT_SIZE]) == (
        evdev.EV_KEY,
        evdev.KEY_ENTER,
        1,
    )
    assert evdev.unpack_event(payload[evdev.EVENT_SIZE :]) == (
        evdev.EV_SYN,
        evdev.SYN_REPORT,
        0,
    )


def test_key_release_uses_value_zero():
    payload = evdev.key_event(evdev.KEY_ENTER, pressed=False)
    assert evdev.unpack_event(payload[: evdev.EVENT_SIZE])[2] == 0


def test_rel_move_omits_axes_that_did_not_move():
    payload = evdev.rel_move(3, 0)
    assert len(payload) == 2 * evdev.EVENT_SIZE  # REL_X + SYN only
    assert evdev.unpack_event(payload[: evdev.EVENT_SIZE]) == (
        evdev.EV_REL,
        evdev.REL_X,
        3,
    )


def test_rel_move_of_zero_sends_nothing():
    # No point waking the far side up for a no-op.
    assert evdev.rel_move(0, 0) == b""


def test_scroll_maps_axes_to_wheel_codes():
    payload = evdev.scroll(dx=2, dy=-1)
    events = [
        evdev.unpack_event(payload[i : i + evdev.EVENT_SIZE])
        for i in range(0, len(payload), evdev.EVENT_SIZE)
    ]
    assert (evdev.EV_REL, evdev.REL_WHEEL, -1) in events
    assert (evdev.EV_REL, evdev.REL_HWHEEL, 2) in events
    assert events[-1][0] == evdev.EV_SYN


class TestKeyMap:
    @pytest.mark.parametrize(
        "mac_keycode,linux_key",
        [
            (0x00, 30),  # A
            (0x0C, 16),  # Q
            (0x24, evdev.KEY_ENTER),
            (0x31, evdev.KEY_SPACE),
            (0x35, evdev.KEY_ESC),
            (0x33, evdev.KEY_BACKSPACE),
            (0x7B, evdev.KEY_LEFT),
            (0x7A, 59),  # F1
        ],
    )
    def test_known_keys(self, mac_keycode, linux_key):
        assert evdev.MAC_TO_LINUX_KEY[mac_keycode] == linux_key

    def test_command_maps_to_meta_not_alt(self):
        # Command is the Super/Meta key on Linux; getting this wrong would make
        # every Hyprland SUPER binding unreachable.
        assert evdev.MAC_TO_LINUX_KEY[0x37] == evdev.KEY_LEFTMETA
        assert evdev.MAC_TO_LINUX_KEY[0x36] == evdev.KEY_RIGHTMETA

    def test_option_maps_to_alt(self):
        assert evdev.MAC_TO_LINUX_KEY[0x3A] == evdev.KEY_LEFTALT
        assert evdev.MAC_TO_LINUX_KEY[0x3D] == evdev.KEY_RIGHTALT

    def test_left_and_right_modifiers_are_distinct(self):
        pairs = [(0x38, 0x3C), (0x3B, 0x3E), (0x3A, 0x3D), (0x37, 0x36)]
        for left, right in pairs:
            assert evdev.MAC_TO_LINUX_KEY[left] != evdev.MAC_TO_LINUX_KEY[right]

    def test_letter_rows_are_positionally_correct(self):
        # evdev is positional; the home row must land on 30..38 in order.
        home_row = [0x00, 0x01, 0x02, 0x03, 0x05, 0x04, 0x26, 0x28, 0x25]
        assert [evdev.MAC_TO_LINUX_KEY[k] for k in home_row] == list(range(30, 39))

    def test_no_duplicate_linux_codes(self):
        codes = list(evdev.MAC_TO_LINUX_KEY.values())
        duplicates = {c for c in codes if codes.count(c) > 1}
        assert not duplicates, f"two macOS keys map to the same Linux code: {duplicates}"

    def test_every_modifier_has_a_side_bit(self):
        # _forward_modifier relies on these to tell press from release.
        for mac_key in evdev.MODIFIER_FLAG_BY_MAC_KEY:
            assert mac_key in evdev.MAC_TO_LINUX_KEY


def test_mouse_buttons_map_to_btn_codes():
    assert evdev.MOUSE_BUTTON_TO_LINUX[0] == evdev.BTN_LEFT
    assert evdev.MOUSE_BUTTON_TO_LINUX[1] == evdev.BTN_RIGHT
    assert evdev.MOUSE_BUTTON_TO_LINUX[2] == evdev.BTN_MIDDLE
