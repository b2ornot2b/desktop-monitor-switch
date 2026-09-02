# Security

## What this tool is

dmswitch forwards keyboard and pointer input from a Mac to another machine and
can capture that machine's screen. Understand the following before running it.

**The receiver is unauthenticated.** Anyone who can reach its port (default
24810) can:

- inject arbitrary keystrokes into the desktop, which is remote code execution
  in practice — they can type into a terminal
- capture the screen of the shared monitor and read it back

**Nothing is encrypted.** Keystrokes — including passwords typed on the remote
machine — and screenshots cross the network in clear text.

**It is persistent.** The receiver installs as an enabled systemd user unit and
returns after a reboot.

**The Mac side is a keylogger by construction.** An active `CGEventTap` with
Accessibility and Input Monitoring can observe everything typed on that machine.

## Using it more safely

- Bind one trusted interface rather than all of them:
  `dmswitch_receiver.py --host 100.x.y.z`. The receiver warns when it binds
  `0.0.0.0`.
- Run it only over a private link you control, such as a VPN between two
  machines on the same desk. Never on untrusted or shared networks.
- Firewall the port to the single peer that needs it.
- Remember the units are enabled: `systemctl --user disable --now
  dmswitch-receiver ydotoold` when you are done with it.

## Reporting a vulnerability

This is a personal project with no security guarantees and no support
commitment. If you find something, please open an issue — or, if you would
rather not disclose it publicly, contact the maintainer through GitHub.

Please do not expect a fast response.
