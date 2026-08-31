"""Guard against more than one dmswitch running at a time.

Two copies is not a harmless duplicate: each builds its own strip of Spaces and
installs its own event tap, so Spaces double up and the taps compete for the
same keystrokes. It is also easy to do by accident, since the app is
full-screen and quietly keeps running when you swipe away from it.
"""

from __future__ import annotations

import errno
import fcntl
import os
import tempfile
from pathlib import Path

LOCK_PATH = Path(tempfile.gettempdir()) / "dmswitch.lock"

# Held open for the lifetime of the process: closing the file drops the lock.
_lock_file = None


def acquire(path: Path | str | None = None) -> tuple[bool, int | None]:
    """Take the single-instance lock.

    Returns ``(acquired, other_pid)``. ``other_pid`` is best effort: the holder
    writes its pid into the file, but the read races with it, so it may be None
    even when the lock is genuinely held.
    """
    global _lock_file
    path = Path(path) if path is not None else LOCK_PATH

    existing_pid: int | None = None
    try:
        existing_pid = int(path.read_text().strip())
    except (OSError, ValueError):
        pass

    handle = open(path, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return False, existing_pid
        raise

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _lock_file = handle
    return True, None


def release() -> None:
    """Drop the lock. Process exit does this too."""
    global _lock_file
    if _lock_file is not None:
        try:
            fcntl.flock(_lock_file, fcntl.LOCK_UN)
        finally:
            _lock_file.close()
            _lock_file = None
