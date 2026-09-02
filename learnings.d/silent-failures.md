# Silent failures

Four separate layers in this stack report success and do nothing. Between them
they account for most of the time this project took. The habit worth keeping:
**verify the observable effect, not the return code.**

## 1. BetterDisplay's CLI accepts wrong commands cheerfully

Every one of these exits 0 and never switches the monitor:

```bash
betterdisplaycli set --tagID=2 --changeInputSource=18
betterdisplaycli set --tagID=2 --ddcAlt --vcp=0x60 --value=145
betterdisplaycli set --tagID=2 --hardwareInputSource=145
curl "http://localhost:55777/set?tagID=2&ddcAlt&vcp=0x60&value=145"   # HTTP 200
```

The working form — verified in both directions:

```bash
betterdisplaycli set --tagID=2 --ddcAlt=145 --vcp=inputSelectAlt
```

`--vcp` takes a **symbolic name**, not a raw hex code, and the value belongs on
`--ddcAlt=`. The generated CLI docs describe `vcp` only as "the DDC control
code" and never mention symbolic names; the answer came from a maintainer reply
on a GitHub issue.

A whole session was spent concluding the DDC bus was "flaky and unreliable"
because wrong commands returned success. The hardware was fine the entire time.

## 2. ydotoold's socket ownership flag ignores names

```bash
sudo ydotoold --socket-own=b2:input --socket-perm=0660   # silently ineffective
sudo ydotoold --socket-own=$(id -u):$(getent group input | cut -d: -f3) --socket-perm=0660   # works
```

With names, the daemon starts, prints nothing, and leaves the socket
`root:root`. Every later step looks correct until input mysteriously does
nothing. Check with `ls -l /tmp/.ydotool_socket`.

## 3. A TCP write into an unaccepted backlog succeeds

The worst one. The receiver handled one connection at a time; the control
channel holds its connection open for the whole session, so `accept()` was
never reached again and the event connection sat unaccepted in the backlog.

The sender's `connect()` succeeded. `sendall()` succeeded into the socket
buffer. The app logged `sent=True`. Nothing was ever read. Workspace switching
worked — that was the *other* channel — while every keystroke vanished with no
error anywhere in the system.

Fixed with a thread per connection. The general shape: **a successful write to
a socket says nothing about anyone reading it.**

## 4. `hl.dsp.dpms({on=true})` toggles rather than sets

The `on` key is accepted and ignored. Four consecutive calls:

```
True → False → True → False
```

Used naively as a "wake the display" call, this blanks the screen on every
second engage — which presents as an intermittently faulty monitor, not a bug.
The fix is to read `dpmsStatus` first and only toggle when actually asleep.

## How to defend against this

Pick an observable that cannot lie, and check it:

| what you changed | what to observe |
|---|---|
| monitor input | look at the monitor, or ask the person |
| keyboard forwarding | `hyprctl devices -j` → `numLock` after sending `KEY_NUMLOCK` |
| pointer forwarding | `hyprctl cursorpos` before and after |
| display awake | `hyprctl monitors -j` → `dpmsStatus` |

For keyboard specifically, macOS keycode `0x47` maps to `KEY_NUMLOCK`, so a
synthetic `CGEventPost` plus a `hyprctl` query is a complete end-to-end check
with nobody in the loop.
