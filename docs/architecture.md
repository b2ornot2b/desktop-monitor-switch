# Architecture

## The problem

Two machines share one monitor. the Mac (macOS) owns the keyboard and
trackpad; the Linux machine (Arch Linux, Hyprland) has no input devices of its own.
Switching between them meant reaching for the monitor's input menu and having
no way to drive the Linux box at all.

## The shape of the solution

```
   the Mac (macOS)                              the Linux machine (Arch/Hyprland)
   ┌──────────────────────────┐   TCP :24810    ┌──────────────────────────┐
   │ dmswitch                 │  EVT: events    │ dmswitch_receiver.py     │
   │  ├─ a Space per omarchy  │ ──────────────► │  ├─ held-key watchdog    │
   │  │   workspace           │  CTL: json      │  ├─ relays to ydotoold   │
   │  ├─ CGEventTap capture   │ ◄──────────────►│  └─ hyprctl workspaces   │
   │  └─ betterdisplaycli     │                 │            ▼             │
   └───────────┬──────────────┘                 │      /dev/uinput         │
               │ DDC                            └──────────────────────────┘
               ▼
        shared LG 3440x1440  ── HDMI 1: the Mac · HDMI 2: the Linux machine
```

## Two independent questions

The central design decision. With two displays these are *not* the same thing:

| | follows | why |
|---|---|---|
| which machine the **monitor shows** | which Space is on the shared monitor | you swipe to change what you are looking at |
| which machine **input goes to** | where the **pointer** is | you may want to use the Mac on the other display while the Linux machine stays on screen |

An earlier version tied both to the Space. That made it impossible to work on
the second display: keystrokes kept going to the Linux machine, and because clicks were
suppressed too, clicking a local window never landed, focus never changed, and
the state sustained itself.

## One Space per workspace

Each the Linux machine workspace gets its own full-screen macOS Space, so the two
machines' desktops form a single strip:

```
[mac 1] [mac 2] … [mac last] │ [ws1] [ws2] [spare] [spare]
                             ↑ swipe left from ws1 returns to the Mac
```

Swiping is left entirely to macOS. The app observes which of its windows is on
the active Space and tells the Linux machine to match.

This is not a stylistic choice. macOS handles the Space-switch gesture from the
raw touch stream, above event taps — a tap can see it but **cannot suppress
it**. Rather than fight that, the gesture is given something useful to switch
between, and the edge behaviour comes for free.

Two spare Spaces sit past the last real workspace so there is always somewhere
to swipe into; Hyprland creates a workspace when one is focused. Spare ids skip
anything in use on another output, since focusing such a workspace would drag
focus to that monitor.

## Workspace tiles

Each Space shows a snapshot of the Linux machine workspace it maps to, so Mission
Control shows something recognisable rather than black squares. The receiver
runs `grim` on the shared output and returns a small JPEG over the control
channel.

`grim` can only photograph what an output is *currently displaying*, so
background workspaces cannot be captured. Snapshots are therefore taken as you
visit a workspace, and again as you leave the strip, and each Space keeps the
last one — the same "as you last saw it" behaviour Mission Control uses for its
own hidden Spaces.

Two constraints the receiver has to respect: `grim` **blocks indefinitely** on a
DPMS-off output, so the display state is checked before capturing rather than
discovered by hanging, and the subprocess is given a timeout regardless.
Captures run on the control worker thread and are applied to the windows on the
main thread, since AppKit is not thread safe.

Each Space is also named after the workspace's current window, so they read
as `remote: user@linux-box:~` rather than all looking alike. Titles come from
Hyprland's `lastwindowtitle`, refreshed whenever a snapshot is taken.

## Components

| module | responsibility |
|---|---|
| `app.py` | the delegate: owns the strip, decides engage/disengage, maps Space → workspace |
| `spaces.py` | builds and tracks the full-screen windows; screen geometry and workspace planning |
| `capture.py` | the CGEventTap: what to forward, what to suppress, where the pointer is |
| `transport.py` | TCP client for input events, with held-key tracking |
| `remote.py` | TCP client for the control channel, with a worker thread for focus |
| `monitor.py` | `betterdisplaycli` wrapper for the DDC input switch |
| `evdev.py` | wire format and the macOS → Linux keycode map |
| `single_instance.py` | flock'd pid file; two copies fight over the keyboard |
| `linux/dmswitch_receiver.py` | the far side: relays input, answers workspace queries |

## What happens on engage

1. A strip Space becomes active on the shared monitor.
2. The event tap is enabled and an event connection opens.
3. `wake` tells the Linux machine to bring its output out of DPMS — it sleeps while the
   monitor is showing the Mac, so switching the input would otherwise land on a
   display sending no picture.
4. `betterdisplaycli` switches the monitor to the Linux machine's input.
5. The active Space's workspace id is sent as a `focus` command.

If the monitor switch fails, forwarding is stopped rather than leaving someone
looking at the Mac with a keyboard that talks to the other machine.

## Safety properties

Handing over your only keyboard deserves more than one way back:

- **Pointer to the other display** — input returns to the Mac immediately
- **Swipe left off the front** — releases monitor and input
- **`Ctrl+Opt+Cmd+Esc`** — panic. Swallowed locally rather than forwarded,
  so it cannot reach the remote machine and cannot be missed
- **`Cmd+Q` / `Ctrl+C`** — quit, via an explicit menu and a signal-polling timer
- **Held-key release** — both ends track pressed keys and release them on
  disconnect, so the remote machine is never left with a stuck modifier it has
  no keyboard to clear
- **Single instance** — a flock'd pid file; two copies would each build a strip
  and install a tap

Pointer motion is forwarded but never suppressed, so the cursor can always
leave the shared monitor. That display is showing the Linux machine anyway, so the
local cursor is invisible while it is over there.

## Deliberate non-choices

- **No gesture interception** — impossible for Space gestures; see
  `learnings.d/macos-event-taps.md`
- **No private Spaces APIs** — `NSWindow.isOnActiveSpace` and the NSWorkspace
  notification are public and sufficient
- **No Deskflow** — cannot be triggered programmatically, and its Wayland
  client cannot run on Hyprland; see `learnings.d/deskflow-dead-end.md`
- **TCP, not UDP** — a dropped key-release strands a key on a machine with no
  keyboard
