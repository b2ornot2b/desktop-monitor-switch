"""Tests for locating the BetterDisplay CLI.

launchd hands a process a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin), so a
bare command name resolves from a shell and not at all from a LaunchAgent.
That difference silently broke monitor switching once already.
"""

from __future__ import annotations

import os

import pytest

from dmswitch import monitor


def test_absolute_path_is_used_when_it_exists(tmp_path):
    cli = tmp_path / "betterdisplaycli"
    cli.write_text("#!/bin/sh\n")
    assert monitor.resolve_cli(str(cli)) == str(cli)


def test_absolute_path_that_does_not_exist_is_rejected(tmp_path):
    assert monitor.resolve_cli(str(tmp_path / "nope")) is None


def test_bare_name_found_on_path(tmp_path, monkeypatch):
    cli = tmp_path / "betterdisplaycli"
    cli.write_text("#!/bin/sh\n")
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert monitor.resolve_cli("betterdisplaycli") == str(cli)


def test_falls_back_when_path_is_stripped(monkeypatch):
    """The launchd case: nothing useful on PATH, but the CLI is installed."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    resolved = monitor.resolve_cli("betterdisplaycli")
    if not any(os.path.exists(p) for p in monitor.FALLBACK_CLI_PATHS):
        pytest.skip("BetterDisplay is not installed on this machine")
    assert resolved is not None
    assert resolved in monitor.FALLBACK_CLI_PATHS


def test_missing_everywhere_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(monitor, "FALLBACK_CLI_PATHS", ())
    assert monitor.resolve_cli("betterdisplaycli") is None


def test_switcher_reports_failure_rather_than_raising(monkeypatch, tmp_path):
    from dmswitch.config import MonitorConfig

    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(monitor, "FALLBACK_CLI_PATHS", ())
    switcher = monitor.MonitorSwitcher(MonitorConfig())
    assert switcher.to_remote() is False
    assert switcher.to_local() is False


class TestDDCAddressing:
    """Which flag carries the value depends on the addressing in use.

    Hardcoding --ddcAlt made the documented path for non-LG monitors
    (standard DDC input select, VCP 0x60) impossible to follow.
    """

    def test_symbolic_vcp_uses_alt_addressing(self):
        from dmswitch.config import MonitorConfig

        assert MonitorConfig(vcp="inputSelectAlt").uses_alt_addressing is True

    def test_raw_vcp_code_uses_standard_addressing(self):
        from dmswitch.config import MonitorConfig

        assert MonitorConfig(vcp="0x60").uses_alt_addressing is False
        assert MonitorConfig(vcp="0X60").uses_alt_addressing is False
