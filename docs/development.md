# Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest
```

74 tests, no hardware required — they cover everything that can be checked
without a real event tap or a Linux machine in the loop.

## What the tests cover

| file | area |
|---|---|
| `test_evdev.py` | wire format, keycode map (positional correctness, no duplicates, Command→Meta) |
| `test_transport.py` | handshake, held-key tracking, release on disconnect |
| `test_remote.py` | control channel, focus coalescing |
| `test_spaces.py` | screen comparison, CG↔Cocoa conversion, workspace planning |
| `test_single_instance.py` | the lock, including a genuinely separate process |

The pattern that makes this testable: keep the logic in plain functions and
classes, and let the AppKit layer stay thin. `plan_workspaces`,
`cg_point_in_frame` and the keycode map are all pure, and they are where the
subtle bugs were.

Fakes exposing `frame()` and `localizedName()` stand in for `NSScreen` fine.

## Testing against real hardware

Both machines are live, so this has visible consequences: the monitor switches
inputs and the Linux machine's workspace changes. Restore state afterwards.

Prefer closing the loop yourself over asking someone to swipe and report:

```python
# keyboard: macOS keycode 0x47 → KEY_NUMLOCK, observable via hyprctl
src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
for down in (True, False):
    Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                       Quartz.CGEventCreateKeyboardEvent(src, 0x47, down))
```

```bash
ssh linux-box "hyprctl -i <sig> devices -j" | python3 -c "..."   # numLock
ssh linux-box "hyprctl -i <sig> cursorpos"                       # pointer
```

`CGWarpMouseCursorPosition` places the pointer on a chosen display, which is
how the input-follows-pointer rule is tested.

Always launch background test runs with a `kill -9` fallback so a bug cannot
strand whoever is at the keyboard:

```bash
nohup .venv/bin/python -m dmswitch -v > /tmp/test.log 2>&1 &
APP=$!
sleep 10
# ... drive it ...
kill -TERM $APP
for i in $(seq 1 10); do sleep 0.5; ps -p $APP >/dev/null || break; done
ps -p $APP >/dev/null && kill -9 $APP
```

Use `--no-forward` for anything not specifically about input capture.

## Deploying the receiver

```bash
scp linux/dmswitch_receiver.py linux-box:~/
scp linux/dmswitch_receiver.py linux-box:~/.local/bin/
ssh linux-box 'systemctl --user restart dmswitch-receiver'
```

Stdlib only, deliberately — it can be copied to a machine with nothing
installed. Keep it that way.

## Conventions

- **git flow**: `feature/*` → `develop` → `main`. Commit after each feature,
  once tests pass.
- **Commit messages** explain the failure mode, not just the change. Several
  bugs here were invisible; a message saying *how* something failed is worth
  more than one saying what was edited.
- **Comments explain why.** The codebase is full of constraints that look
  arbitrary — pointer motion deliberately not suppressed, dpms read before
  toggling, windows built at the origin. Each of those has a comment because
  each was a bug once.

## Before changing capture or engage logic

Read `learnings.d/macos-event-taps.md`, and keep at least one escape route
working: pointer to the other display, swipe off the strip, panic key, Cmd+Q.
It is very easy to write a version that takes the keyboard and does not give it
back.

## Open work

- The Mac side has no reboot test equivalent to the Linux one; the
  LaunchAgent is verified by loading it, not by signing out and in
- The strip resyncs only when you leave it, so a workspace created on
  the Linux machine while you are inside is unreachable until you leave and return
- Workspace 3 is skipped because it lives on a headless output; making the
  numbering contiguous would mean moving it, which would disturb that output
- No authentication on the wire; fine for a trusted link, not for anything else
