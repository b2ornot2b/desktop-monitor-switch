---
name: Bug report
about: Something does not work
---

**What happened, and what you expected instead**

**Setup**
- macOS version:
- Linux distro and Hyprland version (`hyprctl version`):
- Shared monitor make/model, and how each machine connects to it:
- Output of `.venv/bin/python -m dmswitch --check`:

**Logs** — run with `-v` and include the relevant part.
- Mac: `~/Library/Logs/dmswitch.log`
- Linux: `journalctl --user -u dmswitch-receiver -n 50`

**Note:** several failures in this stack are silent — a command reports success
and does nothing. Please say what you *observed* (the monitor did not switch,
the cursor did not move) rather than only what exit codes you saw.
