"""Tests for the sender, especially the held-key bookkeeping.

The stuck-key case is the one that actually hurts in practice: the remote machine has no
keyboard of its own, so a modifier left held down there is genuinely hard to
recover from.
"""

from __future__ import annotations

import socket
import threading

import pytest

from dmswitch import evdev
from dmswitch.config import RemoteConfig
from dmswitch.transport import EventSender


class FakeReceiver:
    """A throwaway TCP server that records everything it is sent."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.received = bytearray()
        self.handshake = None
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        conn, _ = self.sock.accept()
        with conn:
            # The sender identifies the channel before streaming events.
            self.handshake = conn.recv(4)
            while not self._done.is_set():
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                self.received += chunk

    def events(self):
        return [
            evdev.unpack_event(bytes(self.received[i : i + evdev.EVENT_SIZE]))
            for i in range(0, len(self.received), evdev.EVENT_SIZE)
        ]

    def close(self):
        self._done.set()
        self.sock.close()


@pytest.fixture
def receiver():
    r = FakeReceiver()
    yield r
    r.close()


@pytest.fixture
def sender(receiver):
    s = EventSender(RemoteConfig(host="127.0.0.1", port=receiver.port))
    assert s.connect()
    yield s
    s.disconnect()


def _settle():
    import time

    time.sleep(0.15)


def test_connect_reports_failure_for_a_dead_port():
    sender = EventSender(RemoteConfig(host="127.0.0.1", port=1, connect_timeout=0.2))
    assert sender.connect() is False
    assert sender.connected is False


def test_key_press_reaches_the_receiver(sender, receiver):
    sender.send_key(evdev.KEY_ENTER, pressed=True)
    _settle()
    assert (evdev.EV_KEY, evdev.KEY_ENTER, 1) in receiver.events()


def test_release_all_releases_every_held_key(sender, receiver):
    sender.send_key(evdev.KEY_LEFTSHIFT, pressed=True)
    sender.send_key(evdev.KEY_LEFTMETA, pressed=True)
    _settle()
    receiver.received.clear()

    sender.release_all()
    _settle()

    released = {
        code for ev_type, code, value in receiver.events()
        if ev_type == evdev.EV_KEY and value == 0
    }
    assert evdev.KEY_LEFTSHIFT in released
    assert evdev.KEY_LEFTMETA in released


def test_released_keys_are_not_released_twice(sender, receiver):
    sender.send_key(evdev.KEY_LEFTSHIFT, pressed=True)
    sender.send_key(evdev.KEY_LEFTSHIFT, pressed=False)
    _settle()
    receiver.received.clear()

    sender.release_all()
    _settle()

    assert receiver.events() == []


def test_disconnect_releases_held_keys_first(sender, receiver):
    sender.send_key(evdev.KEY_LEFTCTRL, pressed=True)
    _settle()
    receiver.received.clear()

    sender.disconnect()
    _settle()

    released = {
        code for ev_type, code, value in receiver.events()
        if ev_type == evdev.EV_KEY and value == 0
    }
    assert evdev.KEY_LEFTCTRL in released
    assert sender.connected is False


def test_mouse_buttons_are_tracked_as_held_too(sender, receiver):
    sender.send_key(evdev.BTN_LEFT, pressed=True)
    _settle()
    receiver.received.clear()

    sender.release_all()
    _settle()

    released = {
        code for ev_type, code, value in receiver.events()
        if ev_type == evdev.EV_KEY and value == 0
    }
    assert evdev.BTN_LEFT in released


def test_sending_without_a_connection_fails_quietly():
    sender = EventSender(RemoteConfig(host="127.0.0.1", port=1))
    assert sender.send_key(evdev.KEY_ENTER, pressed=True) is False


def test_movement_and_scroll_are_forwarded(sender, receiver):
    sender.send_move(4, -2)
    sender.send_scroll(0, 1)
    _settle()

    events = receiver.events()
    assert (evdev.EV_REL, evdev.REL_X, 4) in events
    assert (evdev.EV_REL, evdev.REL_Y, -2) in events
    assert (evdev.EV_REL, evdev.REL_WHEEL, 1) in events


def test_sender_identifies_itself_as_an_event_channel(sender, receiver):
    # The receiver multiplexes input and control on one port, so the sender
    # has to say which it is before streaming.
    sender.send_key(evdev.KEY_ENTER, pressed=True)
    _settle()
    assert receiver.handshake == b"EVT\n"
