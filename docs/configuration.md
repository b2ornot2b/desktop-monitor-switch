# Configuration

**The defaults describe the author's hardware, not yours.** The monitor id, DDC
input values, hostname and shared-display size all need setting before this
does anything useful.

## File

`~/.config/dmswitch/config.json`, written by:

```bash
.venv/bin/python -m dmswitch --write-config
```

```json
{
  "monitor": {
    "tag_id": 2,
    "local_input": 144,
    "remote_input": 145,
    "cli": "betterdisplaycli",
    "vcp": "inputSelectAlt"
  },
  "remote": {
    "host": "linux-host",
    "port": 24810,
    "connect_timeout": 2.0
  },
  "screen": {
    "width": 0,
    "height": 0
  },
  "remote_label": "remote",
  "switch_monitor": true,
  "forward_input": true,
  "start_hidden": false,
  "freeze_local_cursor": false,
  "spare_workspaces": 2,
  "tile_scale": 1.0,
  "tile_quality": 90,
  "tile_format": "jpeg",
  "scroll_divisor": 3.0
}
```


## Monitor

| key | default | meaning |
|---|---|---|
| `tag_id` | `2` | BetterDisplay display id. `betterdisplaycli get --identifiers` lists them |
| `local_input` | `144` | DDC value for HDMI 1 (the Mac) |
| `remote_input` | `145` | DDC value for HDMI 2 (the Linux machine) |

| `cli` | `betterdisplaycli` | must be on `PATH`; BetterDisplay must also be *running* |
| `vcp` | `inputSelectAlt` | symbolic name for LG's alternate addressing |

`vcp` is a **symbolic name**, not a hex code. Raw codes like `0x60` fail
*silently* on this display — exit 0, no switch. The raw input values come from
BetterDisplay's own preferences and can be re-derived if they ever change:

```bash
defaults read pro.betterdisplay.BetterDisplay 'ddcCustomInputSources@Display:2' \
  | grep -o '{[^}]*LG alt[^}]*}'
```

## Remote

| key | default | meaning |
|---|---|---|
| `host` | `linux-host` | must resolve from this Mac |
| `port` | `24810` | both channels share it |
| `connect_timeout` | `2.0` | seconds |

## Screen

Which display to put the strip on.

| key | default | meaning |
|---|---|---|
| `width` | `0` | shared monitor width in points; `0` means the main screen |
| `height` | `0` | shared monitor height in points |

Matching by size rather than by name, because macOS does not give a stable
identifier for a display across reconnects. If both your displays are the same
size, the first match wins - set this to the one you want and check the log
line `target screen: ...` on startup.

## Labelling

| key | default | meaning |
|---|---|---|
| `remote_label` | `remote` | shown in Space titles, e.g. `remote: nvim` |

## Behaviour

| key | default | meaning |
|---|---|---|
| `switch_monitor` | `true` | set `false` to test forwarding without touching the monitor |
| `forward_input` | `true` | set `false` to watch Space transitions without ever capturing input |
| `start_hidden` | `false` | build the strip at launch without switching into it. The LaunchAgent sets this |
| `freeze_local_cursor` | `false` | see the warning below |
| `spare_workspaces` | `2` | empty Spaces kept past the last real workspace |
| `tile_scale` | `1.0` | snapshot size for Space backgrounds, as a fraction of the output |
| `tile_quality` | `90` | JPEG quality, 1-100 |
| `tile_format` | `jpeg` | `jpeg` or `png` (lossless) |
| `scroll_divisor` | `3.0` | wheel detents per macOS scroll unit |

### `freeze_local_cursor`

Detaches the on-screen cursor from the mouse while forwarding, via
`CGAssociateMouseAndMouseCursorPosition(False)`.

**This is global system state.** If the process dies while it is set, the
cursor stays frozen for the entire login session, with no obvious remedy for
whoever is sitting there. It is off by default because suppressing motion
events already keeps the local pointer still where that is wanted. Turn it on
only if the pointer is observed drifting, and be aware of the failure mode.

### `tile_scale`

Each Space shows a snapshot of the Linux machine workspace it maps to, so Mission
Control shows something recognisable instead of black squares.

Full size by default, because the Space is displayed at the monitor's native
resolution and anything smaller is visibly upscaled. Scaling down is also
*slower*, not faster - it costs CPU that the capture itself does not:

| scale | format | size | capture | round trip |
|---|---|---|---|---|
| 0.25 | jpeg q55 | 15 KB | 183 ms | 205 ms |
| 1.0 | jpeg q75 | 509 KB | 57 ms | 91 ms |
| **1.0** | **jpeg q90** | **765 KB** | **61 ms** | **110 ms** |
| 1.0 | png | 1.05 MB | 282 ms | 352 ms |

These snapshots are mostly text, which is where JPEG artefacts are most
visible, hence the high default quality. Set `tile_format` to `png` for
lossless at roughly 3× the capture time.

Snapshots are taken as you visit a workspace and when you leave the strip, so a
tile shows that workspace **as you last saw it**. `grim` can only photograph
what an output is currently displaying, so background workspaces cannot be
captured, and nothing can be captured while the output is asleep.

### `spare_workspaces`

Without spares the strip dead-ends at the last existing workspace and swiping
right silently does nothing. Hyprland creates a workspace when one is focused,
so a spare Space is a way to make a new desktop.

Spare ids skip anything in use on another output. With workspaces 1 and 2 on
the shared monitor and 3 on a headless output, the strip covers **[1, 2, 4,
5]** — 3 is skipped deliberately, because focusing it would move focus to the
headless monitor.

## Command line

Flags override the file for that run:

```
-v, --verbose          debug logging
--no-monitor-switch    leave the monitor input alone
--no-forward           never capture or forward input
--host HOST            override the receiver host
--port PORT            override the receiver port
--start-hidden         build the strip without switching into it
--log-file PATH        also write the log here
--write-config         write current settings and exit
--check                round-trip the receiver, check permissions and CLI, then exit
```

`--check` asks the receiver for its workspace list rather than just opening the
port, so it also catches a receiver that is talking to the wrong Hyprland
instance:

```
receiver:      linux-box:24810, monitor HDMI-A-1, workspaces [1, 2]
input access:  granted
betterdisplay: /opt/homebrew/bin/betterdisplaycli
```

`--no-forward` is the safe way to try changes: it cannot take over the
keyboard.

## Environment

| variable | used by | note |
|---|---|---|
| `DMSWITCH_CONFIG` | the app | alternative config path |
| `YDOTOOL_SOCKET` | ydotool clients | there is no client-side flag for this |

## Adapting to other hardware

- **Screen matching** — set `screen.width` / `screen.height` to your shared
  monitor's size in points. Left at `0`, the strip goes on the main screen.
- **Monitor name on the Linux side** — pass `--monitor` to the receiver, or
  give the installer the output name (`./install.sh HDMI-A-1`). It refuses to
  guess when several outputs are connected. `hyprctl monitors -j` lists them.
- **A monitor that is not an LG** — `vcp` and the input values will differ.
  Standard DDC input select is VCP `0x60` with values 17/18 for HDMI 1/2; the
  `inputSelectAlt` form here is specific to LG's alternate addressing.
