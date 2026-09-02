# Contributing

This is a personal tool shared in case it is useful. It has been run on exactly
one pair of machines, so the most valuable contribution is usually a report
that it did or did not work on yours.

## Before you start

Read the security note in [SECURITY.md](SECURITY.md). This project injects
input into a remote desktop and captures its screen over an unauthenticated
connection. Changes that widen that exposure need a good reason.

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

The tests deliberately avoid hardware: they cover workspace planning,
coordinate conversion, key mapping, config and the wire protocol, so they run
on any Mac and in CI. Anything that needs a real monitor, a real event tap or a
real Hyprland has to be tested by hand — see
[docs/development.md](docs/development.md).

`--no-forward --no-monitor-switch` is the safe way to run changes: it cannot
take over your keyboard or move your monitor.

## What to know before changing things

Much of this code is shaped by failures that are not obvious from reading it —
a command that exits 0 and does nothing, an API that works from a shell but not
from launchd, a query answered by the wrong Hyprland instance.
[learnings.md](learnings.md) records those. If a comment explains why something
is done a strange way, it is usually load-bearing.

If you find a new one, add it to `learnings.d/` in the same shape: what was
observed, what it actually was, and how to tell next time.

## Pull requests

- Keep the tests passing, and add one where a change is testable without
  hardware.
- Say which machines you tested on. "Works on my LG 34WN750 + Arch/Hyprland
  0.56" is worth more than a green CI run here.
- Match the surrounding style. Comments explain *why*, not what.

Portability beyond Hyprland (other compositors, other DDC backends) is welcome
but should go behind the existing interfaces rather than into the call sites.
