#!/usr/bin/env python3
"""Receives input events and workspace commands from b2umini.

Two kinds of client connect to the same port and say which they are with a
four byte handshake:

``EVT\\n``
    A stream of fixed 24-byte ``struct input_event`` records, relayed to
    ydotoold's unix datagram socket, which owns the uinput device. This exists
    rather than a plain socat bridge because of the held-key watchdog: if the
    Mac disappears mid-keystroke, anything still held down is released here.
    Otherwise this machine is left with a stuck modifier and, since its
    keyboard lives on the other machine, no easy way to clear it.

``CTL\\n``
    Newline-delimited JSON request/response, used to list workspaces on the
    shared monitor and to focus one. The Mac mirrors these workspaces as macOS
    Spaces, so swiping between Spaces switches workspaces here.

Stdlib only, so it can just be copied across and run.

    python3 dmswitch_receiver.py --port 24810
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

EV_SYN = 0x00
EV_KEY = 0x01
SYN_REPORT = 0
KEY_RELEASE = 0

HANDSHAKE_SIZE = 4
HANDSHAKE_EVENTS = b"EVT\n"
HANDSHAKE_CONTROL = b"CTL\n"

DEFAULT_YDOTOOL_SOCKET = "/tmp/.ydotool_socket"
DEFAULT_MONITOR = "HDMI-A-1"

log = logging.getLogger("dmswitch-receiver")


# --------------------------------------------------------------------------
# Hyprland


class Hyprland:
    """Talks to the Hyprland instance that owns the shared monitor.

    Picking the instance matters: this machine runs more than one compositor,
    and the others do not drive the shared monitor at all. Selecting by which
    instance actually lists the target monitor avoids acting on the wrong one.
    """

    def __init__(self, monitor: str):
        self.monitor = monitor
        self._signature: str | None = None

    def _run(
        self, args: list[str], signature: str | None = None, quiet: bool = False
    ) -> str | None:
        sig = signature or self._signature
        cmd = ["hyprctl"]
        if sig:
            cmd += ["-i", sig]
        cmd += args
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5, env=env
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.error("hyprctl failed: %s", exc)
            return None
        if result.returncode != 0:
            # Probing stale instance directories is expected and not worth
            # reporting: the runtime dir keeps one per compositor ever started.
            level = log.debug if quiet else log.error
            level("hyprctl %s failed: %s", args, result.stderr.strip())
            return None
        return result.stdout

    def _instances(self) -> list[str]:
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        hypr = runtime / "hypr"
        if not hypr.is_dir():
            return []
        return [p.name for p in hypr.iterdir() if p.is_dir()]

    def signature(self) -> str | None:
        """The instance that lists our monitor, re-resolved if it went away."""
        if self._signature and self._monitor_names(self._signature) is not None:
            return self._signature

        self._signature = None
        for candidate in self._instances():
            names = self._monitor_names(candidate)
            if names and self.monitor in names:
                log.info("using Hyprland instance %s for %s", candidate, self.monitor)
                self._signature = candidate
                return candidate
        log.error("no Hyprland instance drives monitor %s", self.monitor)
        return None

    def _monitor_names(self, signature: str) -> list[str] | None:
        out = self._run(["monitors", "-j"], signature=signature, quiet=True)
        if not out:
            return None
        try:
            return [m["name"] for m in json.loads(out)]
        except (ValueError, KeyError):
            return None

    def workspaces(self) -> dict:
        """Workspace ids on the shared monitor, plus which one is active."""
        if not self.signature():
            return {"ok": False, "error": "no hyprland instance for monitor"}

        out = self._run(["workspaces", "-j"])
        active_out = self._run(["activeworkspace", "-j"])
        if out is None or active_out is None:
            return {"ok": False, "error": "hyprctl query failed"}

        try:
            all_ws = json.loads(out)
            active = json.loads(active_out)
        except ValueError as exc:
            return {"ok": False, "error": f"bad hyprctl json: {exc}"}

        ids = sorted(w["id"] for w in all_ws if w.get("monitor") == self.monitor and w["id"] > 0)
        # Ids taken on *any* monitor. Spare slots must avoid these: focusing a
        # workspace that lives on another output drags focus over there.
        taken = sorted(w["id"] for w in all_ws if w["id"] > 0)
        return {
            "ok": True,
            "monitor": self.monitor,
            "workspaces": ids,
            "taken": taken,
            "active": active.get("id"),
            "active_monitor": active.get("monitor"),
        }

    def dpms_on(self) -> bool | None:
        """Whether the shared monitor's output is awake, or None if unknown."""
        out = self._run(["monitors", "-j"])
        if not out:
            return None
        try:
            for m in json.loads(out):
                if m.get("name") == self.monitor:
                    return bool(m.get("dpmsStatus"))
        except (ValueError, KeyError):
            return None
        return None

    def wake(self) -> dict:
        """Make sure the shared monitor's output is awake.

        The output sleeps while the monitor is showing the other machine, so
        switching the monitor back to it would otherwise land on a blank input.

        Careful here: ``hl.dsp.dpms`` *toggles*. The ``on`` key is accepted but
        ignored, so calling it unconditionally would blank the screen on every
        second engage. Read the state first and only toggle when actually
        asleep, which makes this idempotent from the caller's point of view.
        """
        if not self.signature():
            return {"ok": False, "error": "no hyprland instance for monitor"}

        state = self.dpms_on()
        if state is True:
            return {"ok": True, "dpms": True, "changed": False}

        self._run(["dispatch", "hl.dsp.dpms({on=true})"])
        state = self.dpms_on()
        if state is not True:
            # One retry: the toggle can race with the output coming back after
            # the monitor switches its input.
            self._run(["dispatch", "hl.dsp.dpms({on=true})"])
            state = self.dpms_on()

        return {
            "ok": state is True,
            "dpms": state,
            "changed": True,
            "error": None if state is True else "could not wake the output",
        }

    def focus(self, workspace_id: int) -> dict:
        """Switch the shared monitor to a workspace.

        Absolute ids only. Relative selectors such as ``e+1`` wrap around and
        walk onto other monitors, which would make the ends of the strip
        impossible to detect.
        """
        if not self.signature():
            return {"ok": False, "error": "no hyprland instance for monitor"}

        # Newer Hyprland uses a Lua dispatcher API; older builds take the
        # classic string form. Try the modern one, then fall back.
        attempts = [
            ["dispatch", f"hl.dsp.focus({{workspace={workspace_id}}})"],
            ["dispatch", "workspace", str(workspace_id)],
        ]
        for args in attempts:
            out = self._run(args)
            if out is not None and "error" not in out.lower():
                state = self.workspaces()
                if state.get("active") == workspace_id:
                    return {"ok": True, "active": workspace_id}
        state = self.workspaces()
        return {
            "ok": state.get("active") == workspace_id,
            "active": state.get("active"),
            "error": None if state.get("active") == workspace_id else "focus failed",
        }


# --------------------------------------------------------------------------
# Input relay


class YdotoolSink:
    """Relays packed input_event records into ydotoold.

    Shared between connection threads, so sends are serialised: interleaving
    halves of two records would desynchronise the stream.
    """

    def __init__(self, path: str):
        self.path = path
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(self.path)
        self._sock = sock
        log.info("connected to ydotoold at %s", self.path)

    def send(self, record: bytes) -> None:
        with self._lock:
            if self._sock is None:
                self.connect()
            assert self._sock is not None
            self._sock.send(record)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None


class EventSession:
    """One connected sender, tracking what it currently holds down."""

    def __init__(self, sink: YdotoolSink):
        self.sink = sink
        self.pressed: set[int] = set()

    def handle(self, record: bytes) -> None:
        _sec, _usec, ev_type, code, value = struct.unpack(EVENT_FORMAT, record)
        if ev_type == EV_KEY:
            if value:
                self.pressed.add(code)
            else:
                self.pressed.discard(code)
        self.sink.send(record)

    def release_all(self) -> None:
        if not self.pressed:
            return
        log.warning("connection ended with %d key(s) held; releasing", len(self.pressed))
        for code in sorted(self.pressed):
            self.sink.send(struct.pack(EVENT_FORMAT, 0, 0, EV_KEY, code, KEY_RELEASE))
        self.sink.send(struct.pack(EVENT_FORMAT, 0, 0, EV_SYN, SYN_REPORT, 0))
        self.pressed.clear()


# --------------------------------------------------------------------------
# Connection handling


def _recv_exactly(conn: socket.socket, count: int) -> bytes | None:
    buf = b""
    while len(buf) < count:
        chunk = conn.recv(count - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def handle_events(conn: socket.socket, sink: YdotoolSink) -> None:
    session = EventSession(sink)
    buffer = b""
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk
            # Records are fixed width, so framing is just chunking.
            while len(buffer) >= EVENT_SIZE:
                record, buffer = buffer[:EVENT_SIZE], buffer[EVENT_SIZE:]
                session.handle(record)
    except OSError as exc:
        log.warning("event connection error: %s", exc)
    finally:
        session.release_all()


def handle_control(conn: socket.socket, hypr: Hyprland) -> None:
    buffer = b""
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                response = dispatch_control(line, hypr)
                conn.sendall(json.dumps(response).encode() + b"\n")
    except OSError as exc:
        log.warning("control connection error: %s", exc)


def dispatch_control(line: bytes, hypr: Hyprland) -> dict:
    try:
        request = json.loads(line)
    except ValueError as exc:
        return {"ok": False, "error": f"bad json: {exc}"}

    command = request.get("cmd")
    if command == "workspaces":
        return hypr.workspaces()
    if command == "focus":
        workspace_id = request.get("id")
        if not isinstance(workspace_id, int):
            return {"ok": False, "error": "focus needs an integer id"}
        log.info("focusing workspace %s", workspace_id)
        return hypr.focus(workspace_id)
    if command == "wake":
        result = hypr.wake()
        if result.get("changed"):
            log.info("woke the %s output (dpms now %s)", hypr.monitor, result.get("dpms"))
        return result
    if command == "ping":
        return {"ok": True}
    return {"ok": False, "error": f"unknown command {command!r}"}


def serve(host: str, port: int, socket_path: str, monitor: str) -> int:
    sink = YdotoolSink(socket_path)
    try:
        sink.connect()
    except OSError as exc:
        log.error(
            "cannot reach ydotoold at %s (%s). Start it with:\n"
            "  sudo ydotoold --socket-own=$(id -u):$(getent group input | cut -d: -f3) "
            "--socket-perm=0660",
            socket_path,
            exc,
        )
        return 1

    hypr = Hyprland(monitor)
    hypr.signature()  # resolve early so problems are visible at startup

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(4)
    log.info("listening on %s:%s (monitor %s)", host, port, monitor)

    def serve_connection(conn: socket.socket, addr) -> None:
        try:
            handshake = _recv_exactly(conn, HANDSHAKE_SIZE)
            if handshake == HANDSHAKE_EVENTS:
                log.info("event sender connected from %s", addr[0])
                handle_events(conn, sink)
                log.info("event sender disconnected")
            elif handshake == HANDSHAKE_CONTROL:
                log.info("control client connected from %s", addr[0])
                handle_control(conn, hypr)
                log.info("control client disconnected")
            else:
                log.warning("unknown handshake %r from %s", handshake, addr[0])
        except OSError as exc:
            log.warning("connection failed: %s", exc)
        finally:
            conn.close()

    while True:
        try:
            conn, addr = listener.accept()
        except KeyboardInterrupt:
            log.info("shutting down")
            break

        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # A thread per connection, because both channels are long lived: the
        # control client holds its connection open for the whole session, so
        # handling connections in turn would leave the event stream sitting
        # unaccepted in the backlog. The sender still connects successfully and
        # its writes still succeed into the socket buffer, so input just
        # vanishes with no error anywhere - which is exactly what happened.
        threading.Thread(
            target=serve_connection, args=(conn, addr), daemon=True
        ).start()

    sink.close()
    listener.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="bind address")
    parser.add_argument("--port", type=int, default=24810, help="listen port")
    parser.add_argument(
        "--ydotool-socket", default=DEFAULT_YDOTOOL_SOCKET, help="ydotoold socket path"
    )
    parser.add_argument(
        "--monitor", default=DEFAULT_MONITOR, help="the shared monitor's output name"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    return serve(args.host, args.port, args.ydotool_socket, args.monitor)


if __name__ == "__main__":
    sys.exit(main())
