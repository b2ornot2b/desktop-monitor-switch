# ydotool and uinput on Wayland

Injecting input into a Wayland compositor from outside is normally the hard
part. `uinput` sidesteps it: a virtual kernel input device is indistinguishable
from real hardware to the compositor, with no portal or DBus involvement.
`ydotoold` owns that device.

## Setup that actually works

```bash
sudo ydotoold --socket-own=1001:992 --socket-perm=0660
```

- **Numeric uid:gid only.** Names (`b2:input`) fail *silently* — the daemon
  starts, prints nothing, and leaves the socket `root:root`.
- Clients find the socket through the **`YDOTOOL_SOCKET` environment
  variable**. There is no client-side `-p`/`--socket-path` flag, despite the
  daemon having one, and the client's default path depends on
  `XDG_RUNTIME_DIR` — so setting that env var can move the socket it looks for.
- **No udev rule is needed.** Explicitly tested by removing one: the device
  works with default tags (`:power-switch:`). Hyprland picks up the hot-plugged
  device fine. The `uaccess`/`seat` tagging that looks necessary is a red
  herring here.
- Nothing survives a reboot; no systemd unit ships with the Arch package.

## The wire protocol is raw input_event records

`ydotoold` listens on a **`SOCK_DGRAM`** unix socket and accepts
`struct input_event` records directly — 24 bytes on 64-bit, `struct.Struct("llHHi")`:

```python
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.connect("/tmp/.ydotool_socket")
s.send(struct.pack("llHHi", 0, 0, EV_REL, REL_X, 120))
s.send(struct.pack("llHHi", 0, 0, EV_SYN, SYN_REPORT, 0))
```

Timestamps can be zero; the kernel fills them in. Every batch needs a
`SYN_REPORT` to be committed. Using this format end to end means the receiver
is a pure relay and never has to interpret anything.

`SOCK_STREAM` fails with `Protocol wrong type for socket` — a good early
signal if you assumed otherwise.

## Do not test with CapsLock

b2omarchy's keyboard options are `compose:caps`, so **CapsLock is remapped to
Compose** and can never toggle capsLock state. Testing with it produced a
convincing false "keyboard injection does not work".

**NumLock (code 69) is the reliable probe** — `hyprctl devices -j` reports
`numLock` per keyboard, giving a clean observable.

## Pointer motion is scaled by libinput

Relative deltas pass through pointer acceleration: `-60,-60` commanded arrived
as `-42,-42`. For 1:1 fidelity set `accel_profile = flat` for the virtual
device in the compositor config.

Absolute positioning (`mousemove -a`) hits ydotool's known half-resolution
bug — commanded `(2000,800)` landed at `(4000,1439)`, exactly 2× with y clamped
by the screen height. Relative motion plus flat acceleration is the more
predictable path.

## Always release held keys

The remote machine has no keyboard of its own, so a modifier left held down
there is genuinely hard to recover from. Both ends track what is pressed:

- the sender releases everything on a clean disconnect
- the receiver releases everything if the connection drops, crashes, or the
  sending machine sleeps

This is why the receiver is a small program rather than a `socat` bridge.
Prefer TCP over UDP for the same reason: a dropped key-release datagram leaves
a key stuck down, which is far worse than a little latency.
