"""Control channel to b2omarchy: query workspaces and switch between them.

Separate from the input stream because it is request/response rather than a
one-way firehose. Both share a port and identify themselves with a handshake.

Focus commands go through a worker thread. Switching a workspace costs a
network round trip plus a couple of hyprctl calls, and that must not block the
Cocoa run loop while the user is mid-swipe.
"""

from __future__ import annotations

import json
import logging
import queue
import socket
import threading

from .config import RemoteConfig

log = logging.getLogger(__name__)

HANDSHAKE = b"CTL\n"


class ControlClient:
    """A reconnecting JSON-line client for the receiver's control channel."""

    def __init__(self, config: RemoteConfig):
        self.config = config
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

    # -- connection --------------------------------------------------------

    def connect(self) -> bool:
        with self._lock:
            return self._connect_locked()

    def _connect_locked(self) -> bool:
        if self._sock is not None:
            return True
        try:
            sock = socket.create_connection(
                (self.config.host, self.config.port), timeout=self.config.connect_timeout
            )
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.sendall(HANDSHAKE)
        except OSError as exc:
            log.error("control channel unreachable: %s", exc)
            return False
        self._sock = sock
        self._buffer = b""
        log.info("control channel open to %s:%s", self.config.host, self.config.port)
        return True

    def close(self) -> None:
        self._stop.set()
        self._queue.put(None)
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                finally:
                    self._sock = None

    # -- requests ----------------------------------------------------------

    def request(self, payload: dict, timeout: float = 5.0) -> dict:
        """Send one request and wait for its reply. Reconnects once if needed."""
        with self._lock:
            for attempt in (1, 2):
                if not self._connect_locked():
                    return {"ok": False, "error": "not connected"}
                try:
                    assert self._sock is not None
                    self._sock.settimeout(timeout)
                    self._sock.sendall(json.dumps(payload).encode() + b"\n")
                    while b"\n" not in self._buffer:
                        chunk = self._sock.recv(4096)
                        if not chunk:
                            raise OSError("control channel closed")
                        self._buffer += chunk
                    line, self._buffer = self._buffer.split(b"\n", 1)
                    return json.loads(line)
                except (OSError, ValueError) as exc:
                    log.warning("control request failed (attempt %d): %s", attempt, exc)
                    if self._sock is not None:
                        self._sock.close()
                        self._sock = None
            return {"ok": False, "error": "control request failed"}

    def workspaces(self) -> dict:
        """Workspace ids on the shared monitor, and which is active."""
        return self.request({"cmd": "workspaces"})

    # -- asynchronous focus ------------------------------------------------

    def start_worker(self) -> None:
        if self._worker is not None:
            return
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._run_worker, name="dmswitch-control", daemon=True
        )
        self._worker.start()

    def focus_async(self, workspace_id: int) -> None:
        """Ask b2omarchy to switch workspace, without blocking the caller."""
        self.start_worker()
        self._queue.put(workspace_id)

    def _run_worker(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                break
            # If several swipes queued up, only the last one matters.
            latest = item
            while True:
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    self._queue.put(None)
                    break
                latest = nxt
            response = self.request({"cmd": "focus", "id": latest})
            if not response.get("ok"):
                log.error("workspace focus failed: %s", response.get("error"))
            else:
                log.info("b2omarchy now on workspace %s", response.get("active"))
