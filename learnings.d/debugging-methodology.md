# Debugging methodology

## The expensive lesson: check the instrument first

The longest detour in this project was concluding that `ydotool` input
injection "does not work on Hyprland". Evidence gathered at the time:

- `ydotool mousemove -- 50 50` → exit 0
- `hyprctl cursorpos` → unchanged, every time
- Retried five times with delays → unchanged
- Quit BetterDisplay in case of DDC contention → unchanged
- Added a udev rule for `uaccess`/`seat` tags → unchanged
- Recreated the device so tags applied from birth → unchanged
- Captured system-wide logs, tried dtrace (blocked by SIP)

The conclusion drawn — a genuine capability gap in Hyprland's Wayland stack —
was written up in detail. It was wrong.

b2omarchy runs **two** Hyprland instances. Selecting one with
`ls -t /run/user/1001/hypr/ | head -1` picks the *nested* one, whose cursor
never responds to real input. Injection had been working the entire time. The
measurement was broken, not the system.

**When evidence says something basic is impossible, suspect the measurement
before the system.** Especially after several failed fixes: each "failed fix"
was really more evidence that the instrument was wrong.

The instance must be resolved by which one drives the target monitor:

```bash
for d in /run/user/1001/hypr/*/; do
  sig=$(basename "$d")
  hyprctl -i "$sig" monitors -j 2>/dev/null | grep -q HDMI-A-1 && echo "$sig"
done
```

## Probe a signature by calling it wrong

Hyprland's Lua API is barely documented, but its errors describe what they
want. Calling a dispatcher incorrectly is the fastest way to learn it:

```
hl.dsp.focus()              → "expected a table, e.g. { direction = "left" }"
hl.dsp.workspace.change_id(2) → "expected a table { workspace, id }"
```

Two wrong calls found `hl.dsp.focus({workspace=2})`. Enumerating the namespace
helps too — `hyprctl repl` prints return values where `hyprctl eval` does not:

```bash
hyprctl repl 'local t={} for k,v in pairs(hl.dsp) do t[#t+1]=k end return table.concat(t,", ")'
```

## Automate the end-to-end check

Testing a KVM switch normally needs a human to type and look. Two tricks remove
that, which makes iteration far faster and avoids burning the user's attention:

- macOS keycode `0x47` maps to `KEY_NUMLOCK`; `hyprctl devices -j` reports
  b2omarchy's `numLock`. Post a synthetic key, query the state — a full
  end-to-end verification of capture, transport, and injection.
- `CGWarpMouseCursorPosition` plus `hyprctl cursorpos` does the same for the
  pointer, and lets you place the pointer on a chosen display to test the
  input-follows-pointer rule.

## Instrument the boundary, not the ends

The single-threaded-receiver bug was invisible from either end: the Mac said
`sent=True`, b2omarchy's tools all worked when driven directly. What exposed it
was logging on *both* sides of the same moment — the Mac reporting a successful
send while the receiver's log showed the event connection being accepted only
at shutdown.

When two components each look correct, log the handoff between them.

## Do not ask the user to be the test harness

Several rounds here ended with "try it now and tell me what happened", each
costing a full context switch and sometimes leaving the person with a captured
keyboard. Where a synthetic event and a remote query can close the loop, do
that instead, and save the human check for the things only a person can judge —
whether the screen looks right, whether it *feels* seamless.
