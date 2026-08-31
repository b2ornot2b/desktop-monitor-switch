"""Tests for the single-instance lock.

Two copies running at once is not a harmless duplicate: each builds its own
strip of Spaces and installs its own event tap, and the taps then compete for
the same keystrokes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from dmswitch import single_instance


@pytest.fixture
def lock_path(tmp_path):
    path = tmp_path / "dmswitch.lock"
    yield path
    single_instance.release()


def test_first_acquire_succeeds(lock_path):
    acquired, other = single_instance.acquire(lock_path)
    assert acquired is True
    assert other is None


def test_lock_records_the_holding_pid(lock_path):
    single_instance.acquire(lock_path)
    assert lock_path.read_text().strip() == str(os.getpid())


def test_a_second_process_is_refused(lock_path):
    single_instance.acquire(lock_path)

    # flock is per open file description, so the contending acquire has to come
    # from a genuinely separate process to be a fair test.
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(_src_dir())!r})
        from dmswitch import single_instance
        acquired, other = single_instance.acquire({str(lock_path)!r})
        print("acquired" if acquired else f"refused:{{other}}")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
    )
    assert result.stdout.strip() == f"refused:{os.getpid()}", result.stderr


def test_lock_is_reusable_after_release(lock_path):
    single_instance.acquire(lock_path)
    single_instance.release()
    acquired, _ = single_instance.acquire(lock_path)
    assert acquired is True


def _src_dir() -> str:
    import dmswitch

    return os.path.dirname(os.path.dirname(dmswitch.__file__))
