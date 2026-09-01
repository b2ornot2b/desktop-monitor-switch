# CLAUDE.md

Guidance for working in this repository.

## What this is

`dmswitch` turns switching to a macOS Space into a KVM switch. Two machines
share one monitor:

- **b2umini** — Mac mini (Apple Silicon, macOS 26), owns the keyboard and trackpad
- **b2omarchy** — Arch Linux ARM running Hyprland, reachable over Tailscale

The shared monitor is the **3440×1440 LG** (BetterDisplay `tagID=2`, `HDMI-A-1`
on the Linux side). A second 5120×1440 display is attached to the Mac only.

## The two rules the design rests on

Do not collapse these into one. They are separate on purpose, and conflating
them is what made an earlier version trap the user:

| | follows |
|---|---|
| which machine the **monitor shows** | which Space is on the shared monitor |
| which machine **input goes to** | where the **pointer** is |

That separation is what lets someone leave b2omarchy up on the shared monitor
while carrying on with the Mac on the other display.

## Architecture in one paragraph

Each b2omarchy workspace gets its own full-screen macOS Space, so the Spaces
and the workspaces form one continuous strip. macOS handles the swipe; the app
just notices which of its windows is on the active Space and tells b2omarchy to
match. Input is captured with a CGEventTap and shipped to a small receiver on
b2omarchy as raw Linux `input_event` records, which it relays into `ydotoold`.

Gestures are **never** intercepted — see `learnings.d/macos-event-taps.md` for
why that is not a choice.

## Ground rules

- **Exit code 0 does not mean it worked.** This stack is full of layers that
  report success and do nothing: BetterDisplay's CLI, ydotool's socket
  ownership flags, a TCP write into an unaccepted backlog. Verify the observable
  effect — the monitor changed, the cursor moved, `numLock` flipped. Most of the
  hard bugs here were silent. See `learnings.d/silent-failures.md`.
- **Measure before theorising.** The single worst detour in this project was
  hours spent concluding "ydotool does nothing" while querying the wrong
  Hyprland instance. Check the instrument before doubting the system.
- **Never leave input captured with no way out.** Any change to capture or
  engage logic must keep at least one escape working: pointer to the other
  display, swipe off the front of the strip, `Ctrl+Opt+Cmd+Esc`, or Cmd+Q.
- Use **git flow** (`feature/*` → `develop` → `main`) and commit after each
  feature, once tests pass.

## Working on this

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest              # 58 tests, no hardware needed
.venv/bin/python -m dmswitch --check    # receiver, permissions, CLI
.venv/bin/python -m dmswitch --no-forward -v   # safe: never captures input
```

`--no-forward` is the right way to try changes to Space or monitor logic
without risking the keyboard.

The receiver and `ydotoold` run as systemd user units on b2omarchy, installed
by `linux/install.sh`, and come back with the graphical session:

```bash
ssh b2omarchy 'systemctl --user status ydotoold dmswitch-receiver'
```

After changing `linux/dmswitch_receiver.py`, redeploy and restart it:

```bash
scp linux/dmswitch_receiver.py b2omarchy:~/.local/bin/
ssh b2omarchy 'systemctl --user restart dmswitch-receiver'
```

## Testing against real hardware

Both machines are live, so tests have visible side effects: the monitor
switches inputs, b2omarchy's workspace changes. That is fine, but restore state
afterwards, and prefer driving things yourself over asking the user to swipe —
a synthetic keystroke of macOS keycode `0x47` maps to `KEY_NUMLOCK`, and
`hyprctl devices -j` reports b2omarchy's numLock, which gives a complete
end-to-end check with no human in the loop.

Do not test keyboard forwarding with **CapsLock**: b2omarchy maps it to Compose
(`compose:caps`), so it can never toggle and looks like a failure.

## Layout

| path | what |
|---|---|
| `src/dmswitch/` | the macOS app |
| `linux/dmswitch_receiver.py` | the b2omarchy receiver, stdlib only so it can just be copied over |
| `docs/` | architecture, protocol, configuration, operations, troubleshooting |
| `learnings.d/` | one file per hard-won lesson, indexed by `learnings.md` |

Read `learnings.md` before changing capture, Spaces, or the receiver. Most of
the non-obvious constraints in this codebase were paid for once already.
