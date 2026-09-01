# Quick start

Getting `dmswitch` running, and knowing how to stop it.

## Before you start

- **b2omarchy**: `ydotool` installed, reachable over the network
- **b2umini**: BetterDisplay installed *and running* (`betterdisplaycli` only
  messages the running app), `uv`, Python 3.11+
- Both **Accessibility** and **Input Monitoring** granted to whichever binary
  runs this — your terminal, if you launch it the way shown below. Input
  Monitoring alone is not enough: without Accessibility the event tap is
  downgraded to listen-only, and keystrokes reach *both* machines.

## 1. Start the input daemon on b2omarchy

```bash
sudo ydotoold --socket-own=1001:992 --socket-perm=0660
```

Use **numeric** uid:gid. Passing names (`b2:input`) fails *silently* — the
socket stays root-owned and every later step looks fine until nothing happens.
Check with `ls -l /tmp/.ydotool_socket`; it should read `b2 input`.

## 2. Start the receiver on b2omarchy

```bash
scp linux/dmswitch_receiver.py b2omarchy:~/
ssh b2omarchy 'nohup python3 ~/dmswitch_receiver.py --port 24810 > /tmp/dmswitch_receiver.log 2>&1 &'
```

Stdlib only, so nothing to install. Neither this nor `ydotoold` survives a
reboot yet.

## 3. Install and check on b2umini

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m dmswitch --check
```

Expected:

```
receiver:      reachable at b2omarchy:24810
input access:  granted
betterdisplay: betterdisplaycli found
```

## 4. First run — without touching your keyboard

```bash
.venv/bin/python -m dmswitch --no-forward -v
```

This mirrors b2omarchy's workspaces as Spaces and switches the monitor, but
never captures input. Swipe between the new Spaces and watch b2omarchy's
workspace follow. When that looks right, drop the flag:

```bash
.venv/bin/python -m dmswitch -v
```

## Using it

Your Spaces and b2omarchy's workspaces are one continuous strip:

```
[mac 1] [mac 2] … [mac last] │ [ws1] [ws2] [spare] [spare]
                             ↑ swipe left from ws1 to come back
```

- **Swipe right** into the strip — the monitor switches to b2omarchy and your
  keyboard and trackpad follow
- **Swipe within** the strip — b2omarchy changes workspace
- **Swipe left off the front** — back to the Mac, monitor and input released
- **Move the pointer to your other display** — input returns to the Mac while
  b2omarchy stays on screen. Input follows the pointer, not the Space.

The two trailing spare Spaces exist so there is always somewhere to swipe into:
Hyprland creates a workspace when you focus one.

## Getting out

| | |
|---|---|
| Swipe left off the front of the strip | normal exit |
| Move the pointer to the other display | input back to the Mac, monitor unchanged |
| `Ctrl+Opt+Cmd+Esc` | panic — releases input and the monitor immediately |
| `Cmd+Q`, or `Ctrl+C` in the launching terminal | quit |
| `pkill -f 'python.*dmswitch'` | from any other machine or SSH session |

Gestures are never captured, so swiping always works even if something else
has gone wrong.

## If something looks wrong

Run with `-v`. The two lines that answer most questions:

```
reevaluate (space-change): workspace=1 engaged=True
key mac=71 -> linux=69 pressed=True repeat=0 sent=True
```

`docs/troubleshooting.md` maps symptoms to causes. Be aware that several
failures in this stack are *silent* — a command can report success and do
nothing — so trust what the monitor and cursor actually do over what any exit
code says.
