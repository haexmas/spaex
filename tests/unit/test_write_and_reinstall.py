"""T061 — unit tests for `install.write_and_reinstall` (Spec 013)."""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.install.manifest_lock import ManifestLockContext
from spaex.install.write_and_reinstall import write_and_reinstall
from spaex.io import atomic
from spaex.util.errors import (
    HaexError,
    InstallTransactionFailedError,
    ManifestRollbackFailedError,
    NoSourcesDeclaredError,
)


def _held_lock(tmp_path: Path) -> ManifestLockContext:
    lock = ManifestLockContext(
        tmp_path / ".spaex/manifest.json.lock", timeout_seconds=1.0
    )
    lock.__enter__()
    return lock


def test_atomic_write_via_tmp_and_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spaex.cli import install as install_cli

    manifest = tmp_path / ".spaex/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b'{"old": true}\n')

    calls: list[str] = []

    def fake_install(args, *, held_manifest_lock=None):
        calls.append(str(args.repo_root))
        return 0

    monkeypatch.setattr(install_cli, "run", fake_install)

    lock = _held_lock(tmp_path)
    try:
        rc = write_and_reinstall(tmp_path, b'{"new": true}\n', lock)
    finally:
        lock.__exit__(None, None, None)

    assert rc == 0
    assert calls == [str(tmp_path)]
    assert manifest.read_bytes() == b'{"new": true}\n'
    assert not (tmp_path / ".spaex/manifest.json.tmp").exists()


def test_install_failure_rolls_back_manifest_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spaex.cli import install as install_cli

    manifest = tmp_path / ".spaex/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b'{"original": true}\n')

    def failing_install(args, *, held_manifest_lock=None):
        raise NoSourcesDeclaredError(message="no constitution sources declared")

    monkeypatch.setattr(install_cli, "run", failing_install)

    lock = _held_lock(tmp_path)
    try:
        with pytest.raises(InstallTransactionFailedError) as exc_info:
            write_and_reinstall(tmp_path, b'{"never": true}\n', lock)
    finally:
        lock.__exit__(None, None, None)

    assert manifest.read_bytes() == b'{"original": true}\n'
    assert exc_info.value.context["install_key"] == "no-sources-declared"


def test_install_failure_deletes_manifest_when_no_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spaex.cli import install as install_cli

    manifest = tmp_path / ".spaex/manifest.json"
    assert not manifest.exists()

    def failing_install(args, *, held_manifest_lock=None):
        raise HaexError(
            message="boom",
            diagnostic_key="boom",
            exit_code=2,
        )

    monkeypatch.setattr(install_cli, "run", failing_install)

    lock = _held_lock(tmp_path)
    try:
        with pytest.raises(InstallTransactionFailedError):
            write_and_reinstall(tmp_path, b'{"first": true}\n', lock)
    finally:
        lock.__exit__(None, None, None)

    assert not manifest.exists()


def test_initial_manifest_write_failure_is_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spaex.cli import install as install_cli

    manifest = tmp_path / ".spaex/manifest.json"
    manifest.parent.mkdir(parents=True)
    original_bytes = b'{"original": true}\n'
    manifest.write_bytes(original_bytes)

    def unexpected_install(args, *, held_manifest_lock=None):
        raise AssertionError("install must not run after manifest publication failed")

    monkeypatch.setattr(install_cli, "run", unexpected_install)
    original_atomic_write = atomic.write_replace
    calls = 0

    def fail_after_initial_write(target: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            target.write_bytes(payload)
            raise OSError("manifest fsync failed")
        original_atomic_write(target, payload)

    monkeypatch.setattr(atomic, "write_replace", fail_after_initial_write)

    lock = _held_lock(tmp_path)
    try:
        with pytest.raises(OSError, match="manifest fsync failed"):
            write_and_reinstall(tmp_path, b'{"new": true}\n', lock)
    finally:
        lock.__exit__(None, None, None)

    assert manifest.read_bytes() == original_bytes


def test_rollback_failure_surfaces_recovery_path_with_lock_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spaex.cli import install as install_cli

    manifest = tmp_path / ".spaex/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b'{"original": true}\n')

    def failing_install(args, *, held_manifest_lock=None):
        raise NoSourcesDeclaredError(message="no constitution sources declared")

    monkeypatch.setattr(install_cli, "run", failing_install)
    original_atomic_write = atomic.write_replace
    calls = 0

    def fail_during_rollback(target: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            original_atomic_write(target, payload)
            return
        raise OSError("rollback storage failure")

    monkeypatch.setattr(atomic, "write_replace", fail_during_rollback)

    lock = _held_lock(tmp_path)
    try:
        with pytest.raises(ManifestRollbackFailedError) as exc_info:
            write_and_reinstall(tmp_path, b'{"new": true}\n', lock)
        assert exc_info.value.context["manifest_path"] == str(manifest)
        assert lock._depth == 1
        assert lock._fd is not None or lock._handle is not None
    finally:
        lock.__exit__(None, None, None)


def test_non_haex_install_failure_is_rolled_back_and_reraised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spaex.cli import install as install_cli

    manifest = tmp_path / ".spaex/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b'{"original": true}\n')

    def failing_install(args, *, held_manifest_lock=None):
        raise RuntimeError("unexpected install failure")

    monkeypatch.setattr(install_cli, "run", failing_install)

    lock = _held_lock(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="unexpected install failure"):
            write_and_reinstall(tmp_path, b'{"new": true}\n', lock)
    finally:
        lock.__exit__(None, None, None)

    assert manifest.read_bytes() == b'{"original": true}\n'


def test_install_receives_held_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spaex.cli import install as install_cli

    manifest = tmp_path / ".spaex/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b'{}\n')

    captured: dict[str, ManifestLockContext | None] = {"lock": None}

    def fake_install(args, *, held_manifest_lock=None):
        captured["lock"] = held_manifest_lock
        return 0

    monkeypatch.setattr(install_cli, "run", fake_install)

    lock = _held_lock(tmp_path)
    try:
        write_and_reinstall(tmp_path, b'{}\n', lock)
    finally:
        lock.__exit__(None, None, None)

    assert captured["lock"] is lock
