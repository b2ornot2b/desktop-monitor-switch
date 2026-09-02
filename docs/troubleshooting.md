# Troubleshooting

Most failures in this stack are **silent** — a layer reports success and does
nothing. Trust what the monitor and cursor actually do over any exit code.

Start with `--check` and `-v`.

## Nothing happens when I swipe into the strip

| check | |
|---|---|
| Is the app running? | `pgrep -f 'python.*dmswitch'` |
| Did it engage? | look for `engaging` in the log |
| What does it think? | `reevaluate (...): workspace=N engaged=...` |

`workspace=None` means no strip window is on its display's active Space — the
Space you swiped to is not one of ours.

## The monitor does not switch

The command that works, and the ones that fail silently, are covered in
`learnings.d/silent-failures.md`. Test by hand:

```bash
betterdisplaycli set --tagID=2 --ddcAlt=145 --vcp=inputSelectAlt   # → the Linux machine
betterdisplaycli set --tagID=2 --ddcAlt=144 --vcp=inputSelectAlt   # → the Mac
```

If those do nothing, check BetterDisplay is **running** — `betterdisplaycli`
only messages the running app — and that `tag_id` still matches
`betterdisplaycli get --identifiers`.

## The monitor switches but the screen is black

the Linux machine's output is asleep. Its HDMI output enters DPMS while the monitor is
showing the Mac, so the input switches to a display sending no picture — the
workspaces are switching correctly underneath.

```bash
ssh linux-box "hyprctl -i <sig> monitors -j" | grep dpmsStatus
```

The app sends `wake` on engage. If that is failing, the log says so. Note that
`hl.dsp.dpms` *toggles*, so do not "fix" it by calling it repeatedly.

## Keystrokes do not reach the Linux machine

Work along the chain:

1. **Is it engaged, and is the pointer on the shared monitor?** Input follows
   the pointer. On the other display, input stays on the Mac by design.
2. **Is the Mac sending?** With `-v`:
   `key mac=71 -> linux=69 pressed=True repeat=0 sent=True`.
   No line at all means the tap is not capturing; `sent=False` means the
   transport failed.
3. **Is the receiver reading?** Its log should show `event sender connected`
   *when you engage*, not only at shutdown. Connected-then-immediately-
   disconnected at the end is the signature of the backlog bug.
4. **Is ydotoold alive?** `pgrep -x ydotoold`, and
   `ls -l $XDG_RUNTIME_DIR/.ydotool_socket` should show `youruser input`, not `root root`.

Do not test with **CapsLock** — it is remapped to Compose here and can never
toggle. Use NumLock.

## Keystrokes reach both machines

The event tap is listen-only, which means **Accessibility** is not granted
(Input Monitoring alone is not enough — it lets you see events but not suppress
them).

```bash
.venv/bin/python -c "
import ctypes, ctypes.util
lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library('ApplicationServices'))
lib.AXIsProcessTrusted.restype = ctypes.c_bool
print(lib.AXIsProcessTrusted())"
```

Grant it to the binary that hosts the process — your terminal, if launched from
a shell.

## My cursor is frozen

Only possible with `freeze_local_cursor` enabled and the process killed hard.

```bash
.venv/bin/python -c "import Quartz; Quartz.CGAssociateMouseAndMouseCursorPosition(True)"
```

Leave the setting off unless you have a specific reason.

## A Space opened on the wrong monitor

The log says so explicitly:

```
workspace 4 Space opened on LG ULTRAWIDE (1), expected LG ULTRAWIDE (2)
```

This was a real bug (window rects are measured from the specified screen's
origin, not the global one) and is fixed; if it recurs, check
`TARGET_SCREEN_SIZE` still matches your display.

## Swiping right past the last workspace does nothing

The strip has run out of Spaces. Raise `spare_workspaces`. Note the strip skips
ids that live on another output — with ws3 on a headless monitor, the strip
covers [1, 2, 4, 5], so the Space after 2 is workspace **4**.

## Duplicate Spaces in Mission Control

Two copies were running at some point, each building a strip. The single-
instance lock prevents this now; orphaned Spaces disappear when their process
exits.

## It engages and disengages repeatedly

Each engage/disengage switches the monitor input, so this looks like the
monitor flapping. Left idle the app engages once and stays put — repeated
transitions mean the active Space is genuinely changing, usually from swiping.
Confirm with the `reevaluate` lines.

## The receiver cannot find Hyprland

```
no Hyprland instance drives monitor HDMI-A-1
```

It resolves the instance by which one lists the target monitor. If the
compositor restarted, it re-resolves automatically. Check `--monitor` matches
what `hyprctl monitors` reports.

Errors while probing *other* instance directories are normal — the runtime
directory keeps a stale entry for every compositor ever started.
