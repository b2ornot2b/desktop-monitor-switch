# Operations

## Starting up

b2omarchy runs two **systemd user units**, installed by `linux/install.sh`:

| unit | what |
|---|---|
| `ydotoold.service` | owns the virtual input device |
| `dmswitch-receiver.service` | relays input, answers workspace queries |

Both are `WantedBy=graphical-session.target`, so they start with the desktop
session and return after a reboot. Neither needs root: `/dev/uinput` is
`root:input 0660` via the udev rule shipped with the ydotool package, and the
user is in the `input` group.

```bash
ssh b2omarchy 'systemctl --user status ydotoold dmswitch-receiver'
ssh b2omarchy 'journalctl --user -u dmswitch-receiver -f'
```

Then on b2umini:

```bash
.venv/bin/python -m dmswitch --check
.venv/bin/python -m dmswitch -v
```

Lingering is off, so the units start at *login* rather than at boot. That is
what you want: the receiver needs a running compositor to talk to. Enable
`loginctl enable-linger b2` only if that changes.

### Two things the units exist to work around

- **ydotoold does not remove its socket when killed.** It then fails to bind on
  the next start while still reporting itself as active, so everything gets
  `ECONNREFUSED`. `ExecStartPre` clears the socket first.
- **Its socket path follows `XDG_RUNTIME_DIR`**, so it differs between a
  systemd unit (`/run/user/1001/`) and a plain SSH shell (`/tmp/`). Both units
  pin the path with `%t` rather than relying on the default.

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
