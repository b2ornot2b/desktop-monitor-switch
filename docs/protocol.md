# Protocol

Both channels share one TCP port (default **24810**) and identify themselves
with a four-byte handshake sent immediately after connecting.

| handshake | channel |
|---|---|
| `EVT\n` | input events, one way, Mac → b2omarchy |
| `CTL\n` | control, request/response, newline-delimited JSON |

The receiver serves connections **concurrently**, one thread each. This is not
an optimisation: the control client holds its connection open for the whole
session, so handling connections in turn would leave the event stream sitting
unaccepted in the backlog — where the sender's `connect()` and `sendall()` both
still succeed and every keystroke silently disappears.

## Event channel

A stream of fixed 24-byte `struct input_event` records, exactly as the Linux
kernel lays them out on 64-bit:

```c
struct input_event {
    struct timeval time;   // two 64-bit longs
    __u16 type;
    __u16 code;
    __s32 value;
};
```

`struct.Struct("llHHi")`, 24 bytes. Timestamps are sent as zero; the kernel
fills them in. Framing is trivial because records are fixed width.

The receiver relays each record verbatim into `ydotoold`'s unix datagram
socket, so it never has to interpret anything.

| type | codes used |
|---|---|
| `EV_KEY` (1) | Linux key codes; `BTN_LEFT` 0x110, `BTN_RIGHT` 0x111, `BTN_MIDDLE` 0x112 |
| `EV_REL` (2) | `REL_X` 0, `REL_Y` 1, `REL_WHEEL` 8, `REL_HWHEEL` 6 |
| `EV_SYN` (0) | `SYN_REPORT` 0, terminating every batch |

Key values are `1` for press and `0` for release. Every logical action ends
with a `SYN_REPORT` or the kernel will not commit it.

### Keycode translation

macOS virtual keycodes are translated to Linux codes **positionally**, not by
the character produced — evdev is positional too, and the layout is applied by
XKB on the far side. Command maps to `KEY_LEFTMETA`/`KEY_RIGHTMETA` so
Hyprland's `SUPER` bindings work, and Option maps to Alt. Left and right
modifiers stay distinct.

Auto-repeats are dropped: the far side repeats on its own from the held-down
state.

## Control channel

One JSON object per line, one response per request.

### `workspaces`

```json
→ {"cmd": "workspaces"}
← {"ok": true, "monitor": "HDMI-A-1", "workspaces": [1, 2],
   "taken": [1, 2, 3], "active": 1, "active_monitor": "HDMI-A-1"}
```

`workspaces` are the ids on the shared monitor — the strip mirrors these.
`taken` are ids in use on *any* output, so the Mac can choose spare ids that
will not drag focus to another monitor.

### `focus`

```json
→ {"cmd": "focus", "id": 2}
← {"ok": true, "active": 2}
```

Absolute ids only. Relative selectors like `e+1` wrap around and walk onto
other monitors, which would make the ends of the strip undetectable. Focusing
an id that does not exist creates that workspace, which is what makes spare
Spaces work.

### `wake`

```json
→ {"cmd": "wake"}
← {"ok": true, "dpms": true, "changed": true}
```

Brings the shared monitor's output out of DPMS. `changed` says whether anything
was actually done.

Idempotent by construction, which matters: `hl.dsp.dpms` **toggles** and
ignores its `on` argument, so calling it unconditionally would blank the screen
on every second engage. The receiver reads `dpmsStatus` first and only toggles
when the output is genuinely asleep.

### `ping`

```json
→ {"cmd": "ping"}
← {"ok": true}
```

Every response carries `ok`; failures add `error` with a human-readable reason.

## Failure handling

- **Sender**: reconnects on demand; tracks every key and button it has pressed
  and releases them on a clean disconnect.
- **Receiver**: tracks pressed keys per connection and releases them if the
  connection drops for any reason — crash, sleep, network loss. Without this,
  b2omarchy is left with a stuck modifier and no keyboard of its own to clear
  it.
- **Focus requests** are coalesced: if several swipes queue up faster than the
  network, only the destination is sent rather than walking through every
  workspace in between.

## Security

None. There is no authentication, and input events are sent in clear text. It
is intended for a trusted private network — here, a Tailscale link between two
machines on one desk. Do not expose port 24810 more widely.
