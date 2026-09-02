# Quick start

Getting `dmswitch` running, and knowing how to stop it.

Read the security note in [README.md](README.md#-read-this-before-running-it)
first. The receiver is unauthenticated: anyone who can reach its port can type
into the Linux machine and read its screen.

## Before you start

**Hardware**

- A monitor with two inputs and working **DDC/CI input switching**, one cable
  from each machine. Not every monitor honours DDC input select.
- A **second display on the Mac**, strongly recommended — moving the pointer
  there is how you take input back without leaving the Space.

**On the Mac**

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- [BetterDisplay](https://github.com/waydabber/BetterDisplay) installed **and
  running** — `betterdisplaycli` only messages the running app, so a stopped
  BetterDisplay means every switch silently does nothing. DDC control is a
  paid-tier feature.
- Both **Accessibility** and **Input Monitoring** granted to whichever binary
  runs this — your terminal, if you launch it the way shown below. Input
  Monitoring alone is not enough: without Accessibility the event tap is
  downgraded to listen-only and keystrokes reach *both* machines.

**On the Linux machine**

- **Hyprland** — this drives `hyprctl` directly and does not work on other
  compositors as written
- `ydotool` and `grim` installed, and your user in the `input` group
- Reachable over the network from the Mac

```bash
git clone https://github.com/b2ornot2b/desktop-monitor-switch
cd desktop-monitor-switch
```

## 1. Install the Linux side

Copy the `linux/` directory over and run the installer, naming the output the
shared monitor is plugged into. `hyprctl monitors -j` lists them; the installer
refuses to guess when there is more than one.

```bash
scp -r linux you@linux-box:~/dmswitch-install
ssh you@linux-box '~/dmswitch-install/install.sh HDMI-A-1'
```

No root needed. It checks for `hyprctl`, `ydotoold` and `grim`, checks you are
in the `input` group, and installs two **systemd user units** so the receiver
and `ydotoold` come back with your graphical session after a reboot.

```bash
ssh you@linux-box 'systemctl --user status ydotoold dmswitch-receiver'
```

By default the receiver listens on all interfaces and says so in its log. To
bind one address, edit the unit's `--host` argument.

## 2. Install and check on the Mac

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m dmswitch --check
```

`--check` does a real round trip — it asks the receiver for its workspace list,
which also proves the receiver found the right Hyprland instance:

```
receiver:      linux-box:24810, monitor HDMI-A-1, workspaces [1, 2]
input access:  granted
betterdisplay: /opt/homebrew/bin/betterdisplaycli
```

Nothing here matches your hardware by default. Write a config and edit it —
monitor id, DDC values, host, and the size of the shared display:

```bash
.venv/bin/python -m dmswitch --write-config   # ~/.config/dmswitch/config.json
```

See [docs/configuration.md](docs/configuration.md).

## 3. First run — without touching your keyboard

```bash
.venv/bin/python -m dmswitch --no-forward --no-monitor-switch -v
```

This mirrors the Linux machine's workspaces as Spaces but never captures input
and never touches the monitor, so nothing can go wrong that you cannot swipe
away from. Swipe between the new Spaces and watch the Linux workspace follow.

Then add the monitor switching back:

```bash
.venv/bin/python -m dmswitch --no-forward -v
```

And finally, with input forwarding:

```bash
.venv/bin/python -m dmswitch -v
```

## Optional: start at login

```bash
./macos/install-launchagent.sh              # install and load
./macos/install-launchagent.sh --uninstall  # remove
```

The agent runs with `--start-hidden`, so signing in builds the strip without
switching you into it or handing the monitor over. Logs go to
`~/Library/Logs/dmswitch.log`.

It runs from a small `.app` bundle (built automatically into `build/`) so macOS
shows it as **dmswitch** rather than `python`. The bundle's executable is a
symlink to the venv interpreter and macOS keys these grants to the underlying
binary, so an existing grant normally carries over. If the log says "could not
create event tap", grant Accessibility and Input Monitoring to
`build/dmswitch.app` under System Settings › Privacy & Security.

## Using it

Your Spaces and the Linux machine's workspaces become one continuous strip:

```
[mac 1] [mac 2] … [mac last] │ [ws1] [ws2] [spare] [spare]
                             ↑ swipe left from ws1 to come back
```

- **Swipe right** into the strip — the monitor switches to the Linux machine
  and your keyboard and trackpad follow
- **Swipe within** the strip — the Linux machine changes workspace
- **Swipe left off the front** — back to the Mac, monitor and input released
- **Move the pointer to your other display** — input returns to the Mac while
  the Linux machine stays on screen. Input follows the pointer, not the Space.

The trailing spare Spaces exist so there is always somewhere to swipe into:
Hyprland creates a workspace when you focus one.

## Getting out

| | |
|---|---|
| Swipe left off the front of the strip | normal exit |
| Move the pointer to the other display | input back to the Mac, monitor unchanged |
| `Ctrl+Opt+Cmd+Esc` | panic — releases input and the monitor immediately |
| `Cmd+Q`, or `Ctrl+C` in the launching terminal | quit |
| `pkill -f 'python.*dmswitch'` | from any other machine or SSH session |

Gestures are never captured, so swiping always works even if something else has
gone wrong.

## If something looks wrong

Run with `-v`. The two lines that answer most questions:

```
reevaluate (space-change): workspace=1 engaged=True
key mac=71 -> linux=69 pressed=True repeat=0 sent=True
```

[docs/troubleshooting.md](docs/troubleshooting.md) maps symptoms to causes. Be
aware that several failures in this stack are *silent* — a command can report
success and do nothing — so trust what the monitor and cursor actually do over
what any exit code says.
