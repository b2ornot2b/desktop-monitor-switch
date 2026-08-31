#!/usr/bin/env python3
"""Receives input events from b2umini and replays them into this machine.

Listens on TCP, reads fixed 24-byte ``struct input_event`` records, and relays
each one to ydotoold's unix datagram socket, which owns the uinput device.

The reason this exists rather than a plain socat bridge is the held-key
watchdog: if the Mac disappears mid-keystroke - crash, sleep, network drop -
anything still held down is released here. Otherwise b2omarchy is left with a
stuck modifier and, since its keyboard lives on the other machine, no easy way
to clear it.

Stdlib only, so it can just be copied across and run.

    python3 dmswitch_receiver.py --port 24810
"""

from __future__ import annotations

import argparse
import logging
import signal
import socket
import struct
import sys

EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

EV_SYN = 0x00
EV_KEY = 0x01
SYN_REPORT = 0
KEY_RELEASE = 0

DEFAULT_YDOTOOL_SOCKET = "/tmp/.ydotool_socket"

log = logging.getLogger("dmswitch-receiver")


class YdotoolSink:
    """Relays packed input_event records into ydotoold."""

    def __init__(self, path: str):
        self.path = path
        self._sock: socket.socket | None = None

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(self.path)
        self._sock = sock
        log.info("connected to ydotoold at %s", self.path)

    def send(self, record: bytes) -> None:
        if self._sock is None:
            self.connect()
        assert self._sock is not None
        self._sock.send(record)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None


class Session:
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


def serve(host: str, port: int, socket_path: str) -> int:
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

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(1)
    log.info("listening on %s:%s", host, port)

    while True:
        try:
            conn, addr = listener.accept()
        except KeyboardInterrupt:
            log.info("shutting down")
            break

        log.info("sender connected from %s", addr[0])
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        session = Session(sink)
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
            log.warning("connection error: %s", exc)
        finally:
            session.release_all()
            conn.close()
            log.info("sender disconnected")

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
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    return serve(args.host, args.port, args.ydotool_socket)


if __name__ == "__main__":
    sys.exit(main())
