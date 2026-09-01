# Operations

## Starting up

Three things must be running, in order:

```bash
# 1. b2omarchy: the input daemon (numeric uid:gid - names fail silently)
sudo ydotoold --socket-own=1001:992 --socket-perm=0660

# 2. b2omarchy: the receiver
nohup python3 ~/dmswitch_receiver.py --port 24810 > /tmp/dmswitch_receiver.log 2>&1 &

# 3. b2umini: the app
.venv/bin/python -m dmswitch -v
```

Verify the first two before the third:

```bash
.venv/bin/python -m dmswitch --check
```

## Not yet persistent

Neither `ydotoold` nor the receiver survives a reboot — the Arch package ships
no systemd unit. Until that is addressed, both need starting by hand after a
restart. Sketches, untested:

```ini
# /etc/systemd/system/ydotoold.service
[Unit]
Description=ydotool daemon
[Service]
ExecStart=/usr/bin/ydotoold --socket-own=1001:992 --socket-perm=0660
Restart=always
[Install]
WantedBy=multi-user.target
```

```ini
# ~/.config/systemd/user/dmswitch-receiver.service
[Unit]
Description=dmswitch receiver
After=graphical-session.target
[Service]
ExecStart=/usr/bin/python3 %h/dmswitch_receiver.py --port 24810
Restart=always
[Install]
WantedBy=graphical-session.target
```

The receiver needs the user session's environment to reach `hyprctl`, which is
why it belongs as a user unit rather than a system one.

## Stopping

| | |
|---|---|
| `Cmd+Q` | from the app |
| `Ctrl+C` | in the launching terminal |
| `pkill -f 'python.*dmswitch'` | from anywhere, including SSH |

All three go through the same shutdown path: input released, held keys
released, monitor returned to b2umini.

Only one copy can run; a second exits and prints the running pid.

## Recovering by hand

If the app is killed hard (`kill -9`) it cannot clean up after itself.

**Monitor stuck showing b2omarchy:**

```bash
betterdisplaycli set --tagID=2 --ddcAlt=144 --vcp=inputSelectAlt
```

**Cursor frozen** (only possible with `freeze_local_cursor` enabled):

```bash
.venv/bin/python -c "import Quartz; Quartz.CGAssociateMouseAndMouseCursorPosition(True)"
```

**Stuck modifier on b2omarchy:** the receiver releases held keys when a
connection drops, so this should self-heal. If not, restart `ydotoold`.

## Logs

The app logs to stdout; redirect it when running detached. `-v` adds the two
lines worth having:

```
reevaluate (space-change): workspace=1 engaged=True
key mac=71 -> linux=69 pressed=True repeat=0 sent=True
```

The first says what the app believes about Spaces; the second traces a
keystroke through translation and out to the wire.

The receiver logs to wherever you redirect it, conventionally
`/tmp/dmswitch_receiver.log`. Worth noticing there:

```
event sender connected from 100.65.60.72
woke the HDMI-A-1 output (dpms now True)
connection ended with 1 key(s) held; releasing
```

The last one means a sender vanished mid-keystroke and the watchdog cleaned up.

## Health checks

```bash
# reachable, permissions, CLI present
.venv/bin/python -m dmswitch --check

# b2omarchy: daemon, socket ownership, virtual device
ssh b2omarchy 'pgrep -x ydotoold; ls -l /tmp/.ydotool_socket; grep -c ydotoold /proc/bus/input/devices'

# the full path, end to end, with nobody typing
# (macOS keycode 0x47 -> KEY_NUMLOCK; hyprctl reports the result)
```

That last check is worth keeping: it exercises capture, transport, and
injection together, and it is how several silent failures in this stack were
caught.

## Things that will surprise you

- **Exit code 0 proves nothing here.** Several layers report success and do
  nothing. Verify the observable effect.
- **Two Hyprland instances run on b2omarchy.** Always select by which one
  drives the shared monitor; picking by recency gives the nested one, whose
  cursor never moves.
- **CapsLock cannot be used to test keyboard forwarding** — it is remapped to
  Compose. Use NumLock.
- **The strip skips workspace 3** — it lives on a headless output.
