"""T060 — unit tests for `ManifestLockContext` (Spec 013)."""

from __future__ import annotations

import argparse
import multiprocessing
import time
from pathlib import Path

import pytest

from spaex.install.manifest_lock import ManifestLockContext, parse_lock_timeout
from spaex.util.errors import ManifestLockContendedError


def _hold_lock(lock_path: str, seconds: float, ready_file: str) -> None:
    """Child-process helper: hold the lock for `seconds`, signal via ready_file."""
    lock = ManifestLockContext(Path(lock_path), timeout_seconds=5.0)
    with lock:
        Path(ready_file).write_text("ready")
        time.sleep(seconds)


def _await_ready(ready_file: Path, child: multiprocessing.Process) -> None:
    """Wait for a child-process readiness signal without polling forever."""
    deadline = time.monotonic() + 5.0
    while not ready_file.exists():
        if not child.is_alive():
            child.join()
            raise AssertionError(
                f"lock child exited before readiness signal (exitcode={child.exitcode})"
            )
        if time.monotonic() >= deadline:
            child.terminate()
            child.join()
            raise AssertionError("lock child did not signal readiness in time")
        time.sleep(0.02)


def test_lock_file_created_if_absent(tmp_path: Path) -> None:
    lock_path = tmp_path / ".spaex.json.lock"
    assert not lock_path.exists()
    with ManifestLockContext(lock_path, timeout_seconds=1.0):
        assert lock_path.exists()
    assert lock_path.exists()  # NEVER deleted


def test_lock_file_not_renamed_or_deleted_on_exit(tmp_path: Path) -> None:
    lock_path = tmp_path / ".spaex.json.lock"
    lock_path.write_bytes(b"pre-existing")
    with ManifestLockContext(lock_path, timeout_seconds=1.0):
        pass
    assert lock_path.exists()
    assert lock_path.read_bytes() == b"pre-existing"


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "-1"])
def test_lock_timeout_parser_rejects_unsafe_values(raw: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_lock_timeout(raw)


def test_lock_timeout_parser_accepts_finite_values() -> None:
    assert parse_lock_timeout("0") == 0.0
    assert parse_lock_timeout("1.5") == 1.5


def test_bounded_wait_succeeds_when_lock_frees_in_time(tmp_path: Path) -> None:
    lock_path = tmp_path / ".spaex.json.lock"
    ready = tmp_path / "ready"

    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=_hold_lock, args=(str(lock_path), 0.5, str(ready)))
    child.start()
    try:
        _await_ready(ready, child)
        with ManifestLockContext(lock_path, timeout_seconds=5.0):
            pass
    finally:
        child.join(timeout=5)


def test_contention_after_timeout_refuses(tmp_path: Path) -> None:
    lock_path = tmp_path / ".spaex.json.lock"
    ready = tmp_path / "ready"

    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=_hold_lock, args=(str(lock_path), 3.0, str(ready)))
    child.start()
    try:
        _await_ready(ready, child)
        with (
            pytest.raises(ManifestLockContendedError) as exc_info,
            ManifestLockContext(lock_path, timeout_seconds=0.2),
        ):
            pass
        assert "lock_path" in exc_info.value.context
    finally:
        child.join(timeout=5)


def test_fail_fast_with_zero_timeout(tmp_path: Path) -> None:
    lock_path = tmp_path / ".spaex.json.lock"
    ready = tmp_path / "ready"

    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=_hold_lock, args=(str(lock_path), 2.0, str(ready)))
    child.start()
    try:
        _await_ready(ready, child)
        start = time.monotonic()
        with (
            pytest.raises(ManifestLockContendedError),
            ManifestLockContext(lock_path, timeout_seconds=0.0),
        ):
            pass
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"fail-fast took {elapsed}s (expected near-zero)"
    finally:
        child.join(timeout=5)


def test_nested_acquisition_reuses_context(tmp_path: Path) -> None:
    lock_path = tmp_path / ".spaex.json.lock"
    lock = ManifestLockContext(lock_path, timeout_seconds=1.0)
    with lock:
        # Re-entering the SAME context object must not try to re-acquire.
        with lock:
            with lock:
                assert lock._depth == 3
            assert lock._depth == 2
        assert lock._depth == 1
    assert lock._depth == 0
