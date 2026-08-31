"""Tests for the workspace control channel."""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from dmswitch.config import RemoteConfig
from dmswitch.remote import ControlClient


class FakeControlServer:
    """Answers JSON-line control requests with canned responses."""

    def __init__(self, responses=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(2)
        self.port = self.sock.getsockname()[1]
        self.responses = responses or {}
        self.requests: list[dict] = []
        self.handshake = None
        self._done = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self._done.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        with conn:
            self.handshake = conn.recv(4)
            buffer = b""
            while not self._done.is_set():
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    request = json.loads(line)
                    self.requests.append(request)
                    reply = self.responses.get(request.get("cmd"), {"ok": True})
                    conn.sendall(json.dumps(reply).encode() + b"\n")

    def close(self):
        self._done.set()
        self.sock.close()


@pytest.fixture
def server():
    s = FakeControlServer(
        {
            "workspaces": {
                "ok": True,
                "monitor": "HDMI-A-1",
                "workspaces": [1, 2, 3],
                "active": 2,
            },
            "focus": {"ok": True, "active": 7},
        }
    )
    yield s
    s.close()


@pytest.fixture
def client(server):
    c = ControlClient(RemoteConfig(host="127.0.0.1", port=server.port))
    yield c
    c.close()


def test_control_channel_announces_itself(client, server):
    client.workspaces()
    assert server.handshake == b"CTL\n"


def test_workspaces_returns_the_parsed_reply(client):
    state = client.workspaces()
    assert state["ok"] is True
    assert state["workspaces"] == [1, 2, 3]
    assert state["active"] == 2


def test_unreachable_server_reports_failure_rather_than_raising():
    client = ControlClient(RemoteConfig(host="127.0.0.1", port=1, connect_timeout=0.2))
    state = client.workspaces()
    assert state["ok"] is False


def test_focus_async_sends_the_request(client, server):
    client.focus_async(3)
    deadline = time.time() + 3
    while time.time() < deadline and not any(
        r.get("cmd") == "focus" for r in server.requests
    ):
        time.sleep(0.05)
    focus_requests = [r for r in server.requests if r.get("cmd") == "focus"]
    assert focus_requests and focus_requests[0]["id"] == 3


def test_rapid_swipes_collapse_to_the_last_workspace(client, server):
    """Only the destination matters when swipes queue up faster than the network."""
    for workspace_id in (1, 2, 3, 4, 5):
        client.focus_async(workspace_id)

    deadline = time.time() + 3
    while time.time() < deadline:
        focus_requests = [r for r in server.requests if r.get("cmd") == "focus"]
        if focus_requests and focus_requests[-1]["id"] == 5:
            break
        time.sleep(0.05)

    focus_requests = [r for r in server.requests if r.get("cmd") == "focus"]
    assert focus_requests[-1]["id"] == 5
    # The whole point of coalescing: we must not walk through every workspace.
    assert len(focus_requests) < 5


def test_wake_is_sent_before_handing_over_the_monitor(server):
    """b2omarchy's output sleeps while the Mac owns the monitor."""
    client = ControlClient(RemoteConfig(host="127.0.0.1", port=server.port))
    client.wake()
    client.close()
    assert any(r.get("cmd") == "wake" for r in server.requests)
