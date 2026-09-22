"""Unit tests for `read_with_consistent_generation` (Spec 028 T012, research.md R9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.io import transaction
from spaex.model.install_lock import InstallLock, read_with_consistent_generation
from spaex.util.errors import InstallLockGenerationInconsistentError


def _write_lock(repo_root: Path, generation_id: str) -> None:
    """Write an install lock with the supplied generation for read tests."""
    lock_path = repo_root / transaction.SPAEX_DIR / transaction.INSTALL_LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = InstallLock("4", generation_id, ())
    lock_path.write_bytes(lock.to_json_bytes())


def test_matching_generation_returns_immediately(tmp_path: Path) -> None:
    """A generation that does not change while `build` runs returns its result."""
    _write_lock(tmp_path, "g_20260101T000000Z_0000")

    result = read_with_consistent_generation(tmp_path, lambda lock: lock.generation_id)

    assert result == "g_20260101T000000Z_0000"


def test_mismatch_then_match_on_retry_succeeds(tmp_path: Path) -> None:
    """A generation that changes once, then holds steady on the retry, still succeeds."""
    _write_lock(tmp_path, "g_20260101T000000Z_0000")
    calls = 0

    def build(lock: InstallLock) -> str:
        """Publish one newer lock during the first bracketed read."""
        nonlocal calls
        calls += 1
        if calls == 1:
            # Simulate a concurrent `spaex install` completing mid-read.
            _write_lock(tmp_path, "g_20260101T000001Z_0000")
        return lock.generation_id

    result = read_with_consistent_generation(tmp_path, build)

    assert result == "g_20260101T000001Z_0000"
    assert calls == 2


def test_persistent_mismatch_raises(tmp_path: Path) -> None:
    """A generation that keeps changing through the retry raises, naming both ids."""
    _write_lock(tmp_path, "g_20260101T000000Z_0000")
    counter = 0

    def build(lock: InstallLock) -> str:
        """Publish a newer lock during every bracketed read."""
        nonlocal counter
        counter += 1
        _write_lock(tmp_path, f"g_20260101T00000{counter}Z_0000")
        return lock.generation_id

    with pytest.raises(InstallLockGenerationInconsistentError) as excinfo:
        read_with_consistent_generation(tmp_path, build)

    assert excinfo.value.context["first_generation_id"] == "g_20260101T000001Z_0000"
    assert excinfo.value.context["second_generation_id"] == "g_20260101T000002Z_0000"
