"""Tests for strip bookkeeping and screen comparison."""

from __future__ import annotations

from dmswitch.spaces import WorkspaceStrip, _same_screen


class FakeRect:
    def __init__(self, x, y, w, h):
        self.origin = type("P", (), {"x": x, "y": y})()
        self.size = type("S", (), {"width": w, "height": h})()


class FakeScreen:
    """Stands in for NSScreen, which cannot be constructed in a unit test."""

    def __init__(self, x, y, w, h, name="fake"):
        self._frame = FakeRect(x, y, w, h)
        self._name = name

    def frame(self):
        return self._frame

    def localizedName(self):
        return self._name


def test_same_screen_matches_by_frame_not_identity():
    # PyObjC returns a new proxy for the same display every time, so identity
    # comparison would always report a mismatch.
    a = FakeScreen(787, 1440, 3440, 1440)
    b = FakeScreen(787, 1440, 3440, 1440)
    assert a is not b
    assert _same_screen(a, b) is True


def test_same_screen_distinguishes_different_displays():
    shared = FakeScreen(787, 1440, 3440, 1440)
    other = FakeScreen(0, 0, 5120, 1440)
    assert _same_screen(shared, other) is False


def test_same_screen_handles_none():
    screen = FakeScreen(0, 0, 100, 100)
    assert _same_screen(None, screen) is False
    assert _same_screen(None, None) is True


class TestStripMatching:
    def test_a_fresh_strip_matches_nothing(self):
        strip = WorkspaceStrip(FakeScreen(0, 0, 100, 100))
        assert strip.matches([1, 2]) is False

    def test_matches_is_order_sensitive(self):
        strip = WorkspaceStrip(FakeScreen(0, 0, 100, 100))
        strip.workspace_ids = [1, 2, 3]
        assert strip.matches([1, 2, 3]) is True
        assert strip.matches([3, 2, 1]) is False
        assert strip.matches([1, 2]) is False

    def test_active_workspace_is_unknown_while_building(self):
        # Mid-build the windows have not been separated into Spaces yet, so
        # any answer would be wrong.
        strip = WorkspaceStrip(FakeScreen(0, 0, 100, 100))
        strip.building = True
        assert strip.active_workspace_id() is None
