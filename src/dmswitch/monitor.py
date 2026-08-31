"""Monitor input switching via BetterDisplay's CLI.

BetterDisplay must be installed and running: ``betterdisplaycli`` only messages
the running app.
"""

from __future__ import annotations

import logging
import subprocess

from .config import MonitorConfig

log = logging.getLogger(__name__)


class MonitorSwitcher:
    def __init__(self, config: MonitorConfig, enabled: bool = True):
        self.config = config
        self.enabled = enabled

    def _set_input(self, value: int) -> bool:
        if not self.enabled:
            log.info("monitor switching disabled; would have set input %s", value)
            return True

        cmd = [
            self.config.cli,
            "set",
            f"--tagID={self.config.tag_id}",
            f"--ddcAlt={value}",
            f"--vcp={self.config.vcp}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            log.error("%s not found; is BetterDisplay installed?", self.config.cli)
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
        """Show b2omarchy on the shared monitor."""
        return self._set_input(self.config.remote_input)

    def to_local(self) -> bool:
        """Show b2umini on the shared monitor."""
        return self._set_input(self.config.local_input)
