"""Monitor input switching via BetterDisplay's CLI.

BetterDisplay must be installed and running: ``betterdisplaycli`` only messages
the running app.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from .config import MonitorConfig

log = logging.getLogger(__name__)

# Where the CLI usually lives, plus the app binary it is only a wrapper around.
# launchd hands a process a minimal PATH - /usr/bin:/bin:/usr/sbin:/sbin - so a
# bare name resolves fine from a shell and not at all from a LaunchAgent.
FALLBACK_CLI_PATHS = (
    "/opt/homebrew/bin/betterdisplaycli",
    "/usr/local/bin/betterdisplaycli",
    "/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay",
)


def resolve_cli(name: str) -> str | None:
    """Find the BetterDisplay CLI, without depending on the inherited PATH."""
    if os.path.sep in name:
        return name if os.path.exists(name) else None

    found = shutil.which(name)
    if found:
        return found

    for candidate in FALLBACK_CLI_PATHS:
        if os.path.exists(candidate):
            return candidate
    return None


class MonitorSwitcher:
    def __init__(self, config: MonitorConfig, enabled: bool = True):
        self.config = config
        self.enabled = enabled
        self._resolved = resolve_cli(config.cli)
        if self._resolved and self._resolved != config.cli:
            log.info("using %s", self._resolved)

    def _set_input(self, value: int) -> bool:
        if not self.enabled:
            log.info("monitor switching disabled; would have set input %s", value)
            return True

        if self._resolved is None:
            log.error(
                "%s not found. Is BetterDisplay installed? Note launchd provides a "
                "minimal PATH, so it may resolve from a shell but not from the agent.",
                self.config.cli,
            )
            return False

        # Which flag carries the value depends on the addressing in use:
        # LG's alternate scheme takes --ddcAlt, standard DDC takes --ddc.
        # Hardcoding --ddcAlt made the documented "adapting to other hardware"
        # path impossible to follow.
        value_flag = "--ddcAlt" if self.config.uses_alt_addressing else "--ddc"
        cmd = [
            self._resolved,
            "set",
            f"--tagID={self.config.tag_id}",
            f"{value_flag}={value}",
            f"--vcp={self.config.vcp}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            log.error("%s vanished between resolving and running it", self._resolved)
            return False
        except subprocess.TimeoutExpired:
            log.error("timed out running %s", " ".join(cmd))
            return False

        # BetterDisplay prints "Failed." and exits non-zero on a rejected
        # command. A clean exit is the best signal available: there is no
        # read-back path for this display's input source.
        if result.returncode != 0 or "Failed" in result.stdout:
            log.error(
                "monitor switch failed (rc=%s): %s%s",
                result.returncode,
                result.stdout.strip(),
                result.stderr.strip(),
            )
            return False

        log.info("monitor input set to %s", value)
        return True

    def to_remote(self) -> bool:
        """Show the remote machine on the shared monitor."""
        return self._set_input(self.config.remote_input)

    def to_local(self) -> bool:
        """Show this Mac on the shared monitor."""
        return self._set_input(self.config.local_input)
