# dmswitch

Turns switching to a dedicated macOS Space into a KVM switch: the shared monitor
flips its input to `b2omarchy`, and this Mac's keyboard and trackpad start
driving that machine instead. Swiping back reverses both.

```
   b2umini (macOS)                              b2omarchy (Arch/Hyprland)
   ┌──────────────────────────┐                 ┌──────────────────────────┐
   │ dmswitch                 │   TCP :24810    │ dmswitch_receiver.py     │
   │  ├─ a Space per omarchy  │  EVT: events    │  ├─ held-key watchdog    │
   │  │   workspace           │ ──────────────► │  ├─ relays to ydotoold   │
   │  ├─ CGEventTap capture   │  CTL: json      │  └─ hyprctl workspaces   │
   │  └─ betterdisplaycli     │ ◄──────────────►│            ▼             │
   └───────────┬──────────────┘                 │      /dev/uinput         │
               │ DDC                            └──────────────────────────┘
               ▼
        shared LG 3440x1440  ── HDMI 1: b2umini · HDMI 2: b2omarchy
```

## How it works

### One Space per workspace

b2omarchy's workspaces are mirrored as macOS Spaces, so the two machines read
as a single continuous strip:

```
[mac 1] [mac 2] … [mac last] │ [ws1] [ws2] [ws3]
                             ↑ swipe left from ws1 lands back on the Mac
```

Swiping is left entirely to macOS. The app just notices which of its windows is
on the active Space and tells b2omarchy to switch to the matching workspace.
That is deliberate: macOS handles the Space-switch gesture from the raw touch
stream, so an event tap can observe it but **cannot suppress it**. Rather than
fight that, the gesture is given something useful to switch between — and
"swipe left off the front to leave b2omarchy" then works for free.

The strip is rebuilt to match however many workspaces b2omarchy has, resynced
whenever you leave it. (Resyncing while you are inside would yank you sideways
mid-use, so it waits.)

It also keeps a couple of empty Spaces past the last real workspace
(`spare_workspaces`, default 2), so there is always somewhere to swipe into:
Hyprland creates a workspace when one is focused, so entering a spare makes it
real. Without them the strip dead-ends and swiping right silently does nothing.
Spare ids skip anything in use on another output, since focusing such a
workspace would drag focus to that monitor.

### Two independent questions

With two displays these are *not* the same thing, so they follow different
signals:

| | follows |
|---|---|
| which machine the **monitor shows** | which Space is on the shared monitor |
| which machine **input goes to** | where the **pointer** is |

So you can leave b2omarchy up on the shared monitor, move the pointer to the
other display, and carry on using this Mac - keystrokes go wherever the
pointer is. Pointer *motion* is forwarded but never suppressed, so the cursor
can always be moved off the shared monitor; if clicks were swallowed
everywhere there would be no way to click a local window and take focus back.

### Engaging

The app puts a full-screen window on its own Space. macOS reports Space changes
through `NSWorkspaceActiveSpaceDidChangeNotification`, and `NSWindow.isOnActiveSpace`
says whether that Space is the one now showing — both public API, so no private
Spaces calls are needed.

When the Space becomes active:

1. `betterdisplaycli` switches the monitor to b2omarchy's input.
2. A CGEventTap starts capturing keyboard and pointer events, *suppressing* them
   locally and sending them to b2omarchy as raw Linux `input_event` records.

Leaving the strip reverses both.

## Documentation

| | |
|---|---|
| [QuickStart.md](QuickStart.md) | get it running, and how to stop it |
| [docs/](docs/) | architecture, protocol, configuration, operations, troubleshooting |
| [learnings.md](learnings.md) | what this cost to find out, so it only costs it once |
| [CLAUDE.md](CLAUDE.md) | orientation for working in this repo |

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
- **Swipe out** — gestures are never captured, so the trackpad always works;
  swiping left off the front of the strip leaves b2omarchy.
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
| `spare_workspaces` | `2` | empty Spaces kept past the last real workspace |
| `freeze_local_cursor` | `false` | detach the local cursor while forwarding (global state; can strand the cursor if the process dies) |

The `--vcp=inputSelectAlt` symbolic form is required for this display; raw hex
VCP codes fail *silently* on it.

## Known limitations

- Workspaces are resynced when you leave the strip, so a workspace created on
  b2omarchy while you are inside it is not reachable until you leave and return.
- Reordering the Spaces in Mission Control still maps correctly (mapping is by
  window, not position) but the left-to-right order stops matching b2omarchy's.

## Development

```bash
.venv/bin/python -m pytest
```

Tests cover the wire format, the macOS→Linux keycode mapping, and the held-key
release logic — everything that can be checked without real hardware in the loop.
