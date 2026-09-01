# Deskflow: why not the obvious answer

Deskflow (the maintained Synergy/Barrier successor) is the obvious tool for
sharing a keyboard and mouse between machines. It was installed on both
machines and evaluated properly. It cannot work for this project, for two
independent reasons. Recorded so nobody spends the day again.

## 1. It cannot be triggered programmatically, by design

The requirement is "switching to a Space hands input to the other machine".
Deskflow offers no way to ask it to switch:

| channel | result |
|---|---|
| synthetic keystrokes (Hammerspoon, `osascript`) | filtered — its `CGEventTap` distinguishes hardware from synthetic events deliberately, as anti-injection |
| Karabiner virtual HID, triggered by a variable | rules are event-driven; setting a variable fires nothing |
| HTTP API | settings only |
| WebSocket | settings sync only |
| binary core protocol | `kMsgCEnter`/`kMsgCLeave` are server→client; no inbound switch message |

Confirmed by the maintainers on [deskflow#9606](https://github.com/deskflow/deskflow/issues/9606),
where a REST endpoint for exactly this was declined as out of scope, and by an
independent write-up that exhausted the same avenues. Only a real mouse-edge
crossing or a genuine physical hotkey switches screens.

## 2. Its Wayland client cannot run on Hyprland

```
ERROR: failed to initialize remote desktop session:
  No such interface "org.freedesktop.portal.RemoteDesktop"
```

Deskflow's Wayland client needs the `RemoteDesktop` portal.
`xdg-desktop-portal-hyprland` 1.4.1 — the current release — does not implement
it; [hyprwm/xdg-desktop-portal-hyprland#252](https://github.com/hyprwm/xdg-desktop-portal-hyprland/issues/252)
is still open. Confirmed by DBus introspection: `InputCapture`, `ScreenCast`
and others are present, `RemoteDesktop` is simply absent.

Deskflow's alternative `InputCapture` portal work is explicitly scoped to GNOME
(Mutter) and KDE (KWin) only, and concerns server-side capture rather than
client-side injection. Not a version problem, not a config problem.

## What this pushed the design towards

Both dead ends turned out to be productive:

- **No programmatic trigger** → stop trying to intercept the gesture. Model
  remote workspaces as macOS Spaces and let the native gesture do the work. The
  edge behaviour ("swipe left off the front to leave") then falls out for free.
- **No portal support** → bypass portals entirely with `uinput`, which no
  compositor can refuse because it looks like real hardware.

The result is fewer moving parts than the off-the-shelf option would have had,
and no dependency on a portal that may never land.
