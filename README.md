# dmswitch

Turns switching to a dedicated macOS Space into a KVM switch: the shared monitor
flips its input to `b2omarchy`, and this Mac's keyboard and trackpad start
driving that machine instead. Swiping back reverses both.

```
   b2umini (macOS)                              b2omarchy (Arch/Hyprland)
   ┌──────────────────────────┐                 ┌──────────────────────────┐
   │ dmswitch                 │                 │ dmswitch_receiver.py     │
   │  ├─ full-screen window   │   TCP :24810    │  ├─ held-key watchdog    │
   │  │   on the last Space   │  input_event    │  └─ relays to ydotoold   │
   │  ├─ CGEventTap capture   │ ──────────────► │            │             │
   │  └─ betterdisplaycli     │   (24B records) │            ▼             │
   └───────────┬──────────────┘                 │      /dev/uinput         │
               │ DDC                            └──────────────────────────┘
               ▼
        shared LG 3440x1440  ── HDMI 1: b2umini · HDMI 2: b2omarchy
```

## How it works

The app puts a full-screen window on its own Space. macOS reports Space changes
through `NSWorkspaceActiveSpaceDidChangeNotification`, and `NSWindow.isOnActiveSpace`
says whether that Space is the one now showing — both public API, so no private
Spaces calls are needed.

When the Space becomes active:

1. `betterdisplaycli` switches the monitor to b2omarchy's input.
2. A CGEventTap starts capturing keyboard and pointer events, *suppressing* them
   locally and sending them to b2omarchy as raw Linux `input_event` records.

Leaving the Space reverses both. Gesture events are deliberately **not**
captured, so a trackpad swipe can always take you back out.

## Setup

### b2omarchy (receiver)

`ydotoold` owns the virtual input device and must be running:

```bash
sudo ydotoold --socket-own=1001:992 --socket-perm=0660
```

Use **numeric** uid:gid — names fail silently, leaving the socket root-owned.
Then run the receiver:

```bash
python3 linux/dmswitch_receiver.py --port 24810
```

Stdlib only, so it can just be copied over.

### b2umini (sender)

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m dmswitch --check     # verifies receiver, permissions, CLI
.venv/bin/python -m dmswitch
```

Use `--no-forward` for a first run: it reports Space transitions without
capturing input, so it cannot take over your keyboard.

`--check` confirms the receiver is reachable, that input access is granted, and
that `betterdisplaycli` is on PATH.

macOS will require **Accessibility** and **Input Monitoring** permission for
whichever binary hosts the process (your terminal, when run this way), under
System Settings › Privacy & Security.

## Safety

Handing your only keyboard to another machine deserves a way back:

- **Quit** — `Cmd+Q`, or `Ctrl+C` in the launching terminal. Both disengage
  cleanly, restoring the monitor and releasing any held keys.
- **Panic key** — `Ctrl+Option+Cmd+Escape` immediately stops forwarding and
  returns the monitor. It is never suppressed or forwarded.
- **Swipe out** — gestures are never captured, so the trackpad always works to
  leave the Space.
- **Held-key release** — both ends track what is held down. On disconnect,
  crash, or sleep, the receiver releases every held key, so b2omarchy is never
  left with a stuck modifier it has no keyboard to clear.
- **Backing out** — if the monitor fails to switch, forwarding is stopped rather
  than leaving you looking at b2umini with a keyboard that talks to b2omarchy.

## Configuration

Defaults match this setup. Override in `~/.config/dmswitch/config.json`
(`python -m dmswitch --write-config` writes the current values):

| Setting | Default | Meaning |
|---|---|---|
| `monitor.tag_id` | `2` | BetterDisplay display id for the shared LG |
| `monitor.local_input` / `remote_input` | `144` / `145` | LG-alt DDC values for HDMI 1 / HDMI 2 |
| `remote.host` / `port` | `b2omarchy` / `24810` | where the receiver listens |
| `switch_monitor` | `true` | set false to test forwarding without touching the monitor |

The `--vcp=inputSelectAlt` symbolic form is required for this display; raw hex
VCP codes fail *silently* on it.

## Not yet implemented

Forwarding the trackpad's desktop-switch gesture onto b2omarchy (so a forward
swipe past the last Space changes workspace there). That needs low-level
multitouch capture rather than a CGEventTap.

## Development

```bash
.venv/bin/python -m pytest
```

Tests cover the wire format, the macOS→Linux keycode mapping, and the held-key
release logic — everything that can be checked without real hardware in the loop.
