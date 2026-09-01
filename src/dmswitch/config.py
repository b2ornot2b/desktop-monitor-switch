"""Configuration, with defaults matching this setup (b2umini <-> b2omarchy)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_PATH = Path(
    os.environ.get("DMSWITCH_CONFIG", Path.home() / ".config" / "dmswitch" / "config.json")
)


@dataclass
class MonitorConfig:
    """How to drive the shared monitor's input source via BetterDisplay.

    ``--vcp`` takes the symbolic name ``inputSelectAlt`` rather than a raw hex
    VCP code: this LG uses LG's non-standard "alt" DDC addressing, and every
    other command shape fails silently (exit 0, no switch).
    """

    tag_id: int = 2
    local_input: int = 144  # "HDMI 1 (LG alt)" -> b2umini
    remote_input: int = 145  # "HDMI 2 (LG alt)" -> b2omarchy
    cli: str = "betterdisplaycli"
    vcp: str = "inputSelectAlt"


@dataclass
class RemoteConfig:
    """Where the receiver on b2omarchy is listening."""

    host: str = "b2omarchy"
    port: int = 24810
    connect_timeout: float = 2.0


@dataclass
class Config:
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)

    # Switch the monitor input as well as forwarding input. Turning this off is
    # useful when testing forwarding on its own.
    switch_monitor: bool = True

    # Capture and forward keyboard/pointer input. Turning this off leaves the
    # Mac's input alone entirely, which makes a first run safe to observe.
    forward_input: bool = True

    # Empty Spaces kept past the last real workspace, so there is always
    # somewhere to swipe into. Hyprland creates a workspace when one is
    # focused, so entering a spare makes it real.
    spare_workspaces: int = 2

    # Build the strip without pulling the user into it. Creating a
    # full-screen Space switches to it, so at login this would otherwise
    # hand the monitor to b2omarchy the moment you sign in.
    start_hidden: bool = False

    # Snapshot size for the Space backgrounds, as a fraction of the real
    # output. Full size by default: the Space is displayed at the monitor's
    # native resolution, so anything less is visibly upscaled - and scaling
    # is actually slower than not, since it costs CPU the capture does not.
    # 1.0 at quality 75 is roughly 500 KB and about 60 ms.
    tile_scale: float = 1.0
    tile_quality: int = 90
    # "jpeg" or "png". These snapshots are mostly text, which is exactly
    # where JPEG artefacts show; png is lossless at roughly 1 MB and a
    # slower capture (~280ms against ~60ms).
    tile_format: str = "jpeg"

    # Scroll wheel detents per macOS scroll unit.
    scroll_divisor: float = 3.0

    # Detach the on-screen cursor from the mouse while forwarding. Suppressing
    # the events should already stop the local cursor moving, and this is
    # global state: if the process dies hard while it is set, the cursor stays
    # frozen for the whole session. Off unless the pointer is seen to drift.
    freeze_local_cursor: bool = False

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or CONFIG_PATH
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls(
            monitor=MonitorConfig(**raw.get("monitor", {})),
            remote=RemoteConfig(**raw.get("remote", {})),
            switch_monitor=raw.get("switch_monitor", True),
            forward_input=raw.get("forward_input", True),
            freeze_local_cursor=raw.get("freeze_local_cursor", False),
            spare_workspaces=raw.get("spare_workspaces", 2),
            start_hidden=raw.get("start_hidden", False),
            tile_scale=raw.get("tile_scale", 1.0),
            tile_quality=raw.get("tile_quality", 90),
            tile_format=raw.get("tile_format", "jpeg"),
            scroll_divisor=raw.get("scroll_divisor", 3.0),
        )

    def save(self, path: Path | None = None) -> Path:
        path = path or CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")
        return path
