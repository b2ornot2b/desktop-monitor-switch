"""Ships packed input_event records to the receiver on b2omarchy.

TCP rather than UDP on purpose: a dropped key-release datagram leaves a key
stuck down on the far machine, which is much worse than a little latency.
Records are a fixed 24 bytes, so framing is just a matter of reading in
multiples of that.
"""

from __future__ import annotations

import logging
import socket
import threading

from . import evdev
from .config import RemoteConfig

log = logging.getLogger(__name__)

# Tells the receiver this connection carries input events rather than control
# messages; both share a port.
HANDSHAKE = b"EVT\n"


class EventSender:
    """A reconnecting TCP client that also tracks what it has pressed.

    Tracking matters: whenever forwarding stops - cleanly or because the link
    died - anything still held down has to be released, or b2omarchy is left
    with a stuck modifier and no keyboard of its own to clear it.
    """

    def __init__(self, config: RemoteConfig):
        self.config = config
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._pressed: set[tuple[int, int]] = set()  # (ev_type, code)

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> bool:
        with self._lock:
            if self._sock is not None:
                return True
            try:
                sock = socket.create_connection(
                    (self.config.host, self.config.port),
                    timeout=self.config.connect_timeout,
                )
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.sendall(HANDSHAKE)
                sock.settimeout(None)
            except OSError as exc:
                log.error("cannot reach receiver at %s:%s (%s)", self.config.host, self.config.port, exc)
                return False
            self._sock = sock
            log.info("connected to %s:%s", self.config.host, self.config.port)
            return True

    def disconnect(self) -> None:
        """Release anything held down, then close."""
        self.release_all()
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                finally:
                    self._sock = None
                    log.info("disconnected from receiver")

    def _send_raw(self, payload: bytes) -> bool:
        if not payload:
            return True
        with self._lock:
            sock = self._sock
            if sock is None:
                return False
            try:
                sock.sendall(payload)
                return True
            except OSError as exc:
                log.error("send failed, dropping connection: %s", exc)
                try:
                    sock.close()
                finally:
                    self._sock = None
                # Nothing can be released over a dead socket; the receiver's own
                # watchdog clears held keys when the connection drops.
                self._pressed.clear()
                return False

    def send_key(self, linux_key: int, pressed: bool) -> bool:
        self._track(evdev.EV_KEY, linux_key, pressed)
        return self._send_raw(evdev.key_event(linux_key, pressed))

    def send_move(self, dx: int, dy: int) -> bool:
        return self._send_raw(evdev.rel_move(dx, dy))

    def send_scroll(self, dx: int, dy: int) -> bool:
        return self._send_raw(evdev.scroll(dx, dy))

    def _track(self, ev_type: int, code: int, pressed: bool) -> None:
        key = (ev_type, code)
        if pressed:
            self._pressed.add(key)
        else:
            self._pressed.discard(key)

    def release_all(self) -> None:
        """Send a release for every key and button we currently hold down."""
        with self._lock:
            held = sorted(self._pressed)
            self._pressed.clear()
        if not held:
            return
        log.info("releasing %d held key(s)/button(s)", len(held))
        payload = b"".join(
            evdev.pack_event(ev_type, code, evdev.KEY_RELEASE) for ev_type, code in held
        )
        self._send_raw(payload + evdev.sync())
