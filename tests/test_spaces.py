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


class TestPlanWorkspaces:
    """The strip needs slots past the last real workspace, or it dead-ends."""

    def test_spares_are_appended_after_the_existing_workspaces(self):
        from dmswitch.spaces import plan_workspaces

        assert plan_workspaces([1, 2], taken=[1, 2], spares=2) == [1, 2, 3, 4]

    def test_spares_skip_ids_used_on_another_monitor(self):
        # Focusing a workspace that lives on another output would drag focus
        # to that monitor, so 3 must be stepped over here.
        from dmswitch.spaces import plan_workspaces

        assert plan_workspaces([1, 2], taken=[1, 2, 3], spares=2) == [1, 2, 4, 5]

    def test_no_spares_gives_just_the_real_workspaces(self):
        from dmswitch.spaces import plan_workspaces

        assert plan_workspaces([1, 2], taken=[1, 2], spares=0) == [1, 2]

    def test_existing_ids_are_sorted_and_deduplicated(self):
        from dmswitch.spaces import plan_workspaces

        assert plan_workspaces([3, 1, 1], taken=[1, 3], spares=1) == [1, 3, 4]

    def test_gaps_below_the_end_are_left_alone(self):
        # Reusing a gap would renumber the strip relative to b2omarchy.
        from dmswitch.spaces import plan_workspaces

        assert plan_workspaces([1, 5], taken=[1, 5], spares=1) == [1, 5, 6]

    def test_works_with_no_existing_workspaces(self):
        from dmswitch.spaces import plan_workspaces

        assert plan_workspaces([], taken=[], spares=2) == [1, 2]
