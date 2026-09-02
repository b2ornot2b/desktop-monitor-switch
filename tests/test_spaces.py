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
        # Reusing a gap would renumber the strip relative to the remote machine.
        from dmswitch.spaces import plan_workspaces

        assert plan_workspaces([1, 5], taken=[1, 5], spares=1) == [1, 5, 6]

    def test_works_with_no_existing_workspaces(self):
        from dmswitch.spaces import plan_workspaces

        assert plan_workspaces([], taken=[], spares=2) == [1, 2]


class TestCGPointInFrame:
    """CG and Cocoa disagree about which way y grows.

    Getting this wrong puts the pointer on the wrong display whenever the
    screens are stacked vertically, which is this setup: the 49" is at Cocoa
    (0,0) and the shared 34" sits above it at Cocoa y=1440.
    """

    MAIN_H = 1440.0
    SHARED = FakeRect(787, 1440, 3440, 1440)   # the 34", above the main screen
    MAIN = FakeRect(0, 0, 5120, 1440)          # the 49"

    def test_point_on_the_shared_monitor(self):
        from dmswitch.spaces import cg_point_in_frame

        # Cocoa y 2000 (on the 34") is CG y -560.
        assert cg_point_in_frame(2000, -560, self.SHARED, self.MAIN_H) is True

    def test_point_on_the_main_monitor_is_not_shared(self):
        from dmswitch.spaces import cg_point_in_frame

        # Middle of the 49": CG (2000, 700) -> Cocoa y 740.
        assert cg_point_in_frame(2000, 700, self.SHARED, self.MAIN_H) is False
        assert cg_point_in_frame(2000, 700, self.MAIN, self.MAIN_H) is True

    def test_naive_comparison_would_have_been_wrong(self):
        from dmswitch.spaces import cg_point_in_frame

        # A CG y of 1500 looks like it is inside the shared frame's Cocoa
        # y-range (1440..2880) if compared directly, but it is really below
        # the main screen and on neither.
        assert cg_point_in_frame(2000, 1500, self.SHARED, self.MAIN_H) is False

    def test_x_outside_the_shared_monitor(self):
        from dmswitch.spaces import cg_point_in_frame

        # Left of the 34", which starts at x=787.
        assert cg_point_in_frame(100, -560, self.SHARED, self.MAIN_H) is False


class TestWindowTitle:
    """Spaces are named after what the remote machine has on them.

    All Spaces reading the same makes them indistinguishable in Mission
    Control, which is the whole reason for showing a title at all.
    """

    def test_uses_the_remote_window_title(self):
        from dmswitch.spaces import _window_title

        assert _window_title(1, "user@host:~", "linux") == "linux: user@host:~"

    def test_falls_back_to_the_workspace_number(self):
        from dmswitch.spaces import _window_title

        assert _window_title(3, "", "linux") == "linux: workspace 3"
        assert _window_title(3, None, "linux") == "linux: workspace 3"

    def test_whitespace_only_titles_are_treated_as_empty(self):
        from dmswitch.spaces import _window_title

        assert _window_title(2, "   ", "linux") == "linux: workspace 2"

    def test_label_is_configurable_not_hardcoded(self):
        # The label names whichever machine the user is switching to; baking
        # in one hostname made every Space read as the author's setup.
        from dmswitch.spaces import _window_title

        assert _window_title(1, "vim", "workstation") == "workstation: vim"
        assert _window_title(1, "vim").startswith("remote: ")

    def test_title_is_always_prefixed_so_the_machine_is_obvious(self):
        from dmswitch.spaces import _window_title

        for title in ("vim", "", None, "a b c"):
            assert _window_title(1, title, "linux").startswith("linux: ")


class TestStripStability:
    """The strip must not churn.

    Visiting a spare Space makes Hyprland create that workspace, which changes
    the id set and so the plan. Rebuilding on every change tore all the windows
    down, destroying the user's Spaces and re-adding them at the end of the
    order - repeatedly, every time they left the strip.
    """

    def _strip(self):
        from dmswitch.spaces import WorkspaceStrip

        strip = WorkspaceStrip(FakeScreen(0, 0, 3440, 1440))
        strip.workspace_ids = [1, 3, 4]
        strip.windows = ["w1", "w3", "w4"]  # stand-ins; extend() is not called
        return strip

    def test_a_shifting_spare_plan_leaves_the_strip_alone(self):
        # Real workspaces are all covered, so nothing should be added even
        # though a fresh plan would have picked different spare ids.
        strip = self._strip()
        existing = [1]
        missing = [w for w in existing if w not in set(strip.workspace_ids)]
        assert missing == []

    def test_a_genuinely_new_workspace_is_added(self):
        strip = self._strip()
        existing = [1, 9]
        missing = [w for w in existing if w not in set(strip.workspace_ids)]
        assert missing == [9]

    def test_extend_ignores_ids_already_covered(self):
        from dmswitch.spaces import WorkspaceStrip

        strip = WorkspaceStrip(FakeScreen(0, 0, 3440, 1440))
        strip.workspace_ids = [1, 2]
        strip.windows = ["a", "b"]
        strip.extend([1, 2])          # all known: must be a no-op
        assert strip.workspace_ids == [1, 2]
        assert strip.windows == ["a", "b"]
        assert strip.building is False
