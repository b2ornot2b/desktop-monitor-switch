"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import CONFIG_PATH, Config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dmswitch",
        description="Hand the shared monitor and this Mac's keyboard/trackpad to "
        "b2omarchy when its dedicated Space is active.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument(
        "--no-monitor-switch",
        action="store_true",
        help="forward input only, leave the monitor input alone (useful when testing)",
    )
    parser.add_argument(
        "--no-forward",
        action="store_true",
        help="do not capture or forward input; just report Space transitions. "
        "Recommended for a first run, since it cannot take over your keyboard.",
    )
    parser.add_argument("--host", help="override the receiver host")
    parser.add_argument("--port", type=int, help="override the receiver port")
    parser.add_argument(
        "--write-config",
        action="store_true",
        help=f"write the current settings to {CONFIG_PATH} and exit",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check connectivity and permissions, then exit",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = Config.load()
    if args.no_monitor_switch:
        config.switch_monitor = False
    if args.no_forward:
        config.forward_input = False
    if args.host:
        config.remote.host = args.host
    if args.port:
        config.remote.port = args.port

    if args.write_config:
        path = config.save()
        print(f"wrote {path}")
        return 0

    if args.check:
        return _check(config)

    from .app import run

    return run(config)


def _check(config: Config) -> int:
    """Verify the receiver is reachable and the event tap can be created."""
    import Quartz

    from .transport import EventSender

    ok = True

    sender = EventSender(config.remote)
    if sender.connect():
        print(f"receiver:      reachable at {config.remote.host}:{config.remote.port}")
        sender.disconnect()
    else:
        print(f"receiver:      UNREACHABLE at {config.remote.host}:{config.remote.port}")
        ok = False

    trusted = Quartz.CGPreflightListenEventAccess()
    print(f"input access:  {'granted' if trusted else 'NOT GRANTED'}")
    if not trusted:
        print(
            "               grant Accessibility + Input Monitoring to the binary "
            "running this,\n               in System Settings > Privacy & Security."
        )
        ok = False

    from .monitor import MonitorSwitcher

    import shutil

    if shutil.which(config.monitor.cli):
        print(f"betterdisplay: {config.monitor.cli} found")
    else:
        print(f"betterdisplay: {config.monitor.cli} NOT FOUND")
        ok = False
    del MonitorSwitcher

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
