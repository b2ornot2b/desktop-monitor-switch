# Configuration

Defaults match this setup, so normally nothing needs configuring.

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
    "host": "b2omarchy",
    "port": 24810,
    "connect_timeout": 2.0
  },
  "switch_monitor": true,
  "forward_input": true,
  "freeze_local_cursor": false,
  "spare_workspaces": 2,
  "scroll_divisor": 3.0
}
```

## Monitor

| key | default | meaning |
|---|---|---|
| `tag_id` | `2` | BetterDisplay display id. `betterdisplaycli get --identifiers` lists them |
| `local_input` | `144` | DDC value for HDMI 1 (b2umini) |
| `remote_input` | `145` | DDC value for HDMI 2 (b2omarchy) |
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
| `host` | `b2omarchy` | must resolve from this Mac |
| `port` | `24810` | both channels share it |
| `connect_timeout` | `2.0` | seconds |

## Behaviour

| key | default | meaning |
|---|---|---|
| `switch_monitor` | `true` | set `false` to test forwarding without touching the monitor |
| `forward_input` | `true` | set `false` to watch Space transitions without ever capturing input |
| `freeze_local_cursor` | `false` | see the warning below |
| `spare_workspaces` | `2` | empty Spaces kept past the last real workspace |
| `scroll_divisor` | `3.0` | wheel detents per macOS scroll unit |

### `freeze_local_cursor`

Detaches the on-screen cursor from the mouse while forwarding, via
`CGAssociateMouseAndMouseCursorPosition(False)`.

**This is global system state.** If the process dies while it is set, the
cursor stays frozen for the entire login session, with no obvious remedy for
whoever is sitting there. It is off by default because suppressing motion
events already keeps the local pointer still where that is wanted. Turn it on
only if the pointer is observed drifting, and be aware of the failure mode.

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
--write-config         write current settings and exit
--check                verify receiver, permissions and CLI, then exit
```

`--no-forward` is the safe way to try changes: it cannot take over the
keyboard.

## Environment

| variable | used by | note |
|---|---|---|
| `DMSWITCH_CONFIG` | the app | alternative config path |
| `YDOTOOL_SOCKET` | ydotool clients | there is no client-side flag for this |

## Adapting to other hardware

- **Screen matching** — `TARGET_SCREEN_SIZE` in `app.py` identifies the shared
  monitor by size; change it if yours differs.
- **Monitor name on the Linux side** — the receiver defaults to `HDMI-A-1`;
  pass `--monitor` to change it.
- **A monitor that is not an LG** — `vcp` and the input values will differ.
  Standard DDC input select is VCP `0x60` with values 17/18 for HDMI 1/2; the
  `inputSelectAlt` form here is specific to LG's alternate addressing.
