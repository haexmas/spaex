"""T036-T038 - integration tests for Spec 016 User Story 4.

Multi-molecule ordering, hook-only molecules, and multi-molecule
transaction rollback.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import add as add_cli
from spaex.migrate.transform import clone_dir
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.model.install_lock import InstallLock
from spaex.util.errors import HaexError

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_CANONICAL = "https://example.invalid/example/publisher"
_PUBLISHER = "com.example.publisher"


def _git(cwd: Path, *args: str) -> str:
    """Run Git in a fixture repository and return its stripped standard output."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _molecule_manifest(
    molecule_id: str,
    priority: int,
    *,
    on_failure: str = "abort",
    include_constitution: bool = False,
) -> dict:
    """Build a molecule manifest with an install_hook and optional constitution.

    The schema requires ``atoms`` with at least one category; hook-only
    molecules satisfy that with a non-constitution category (``agents``
    pointing at the hook script itself). Only ``atoms.constitution``
    contributes to the assembled constitution; other categories are
    inert at install time (their consumer-side wiring is out of scope
    for Spec 016).
    """
    atoms: dict[str, list[str]] = {"agents": ["install.py"]}
    if include_constitution:
        atoms["constitution"] = ["constitution.md"]
    manifest = {
        "spaex_version": "4",
        "id": molecule_id,
        "version": "1.0.0",
        "priority": priority,
        "atoms": atoms,
        "install_hook": {
            "interpreter": sys.executable,
            "script": "install.py",
            "on_failure": on_failure,
        },
    }
    return manifest


def _publish_molecules(
    tmp_path: Path,
    molecules: list[tuple[str, dict, str]],
) -> tuple[str, str, Path]:
    """Publish one bare git repo with the requested molecules; return url, sha, state_root.

    ``molecules`` is a list of ``(subdir, manifest_dict, hook_source)`` tuples.
    """
    working = tmp_path / "publisher-working"
    working.mkdir()
    _git(working, "init", "-q", "-b", "main")
    _git(working, "config", "user.email", "author@example.com")
    _git(working, "config", "user.name", "author")
    _git(working, "config", "commit.gpgsign", "false")

    publisher_manifest = {
        "spaex_version": "4",
        "publisher": _PUBLISHER,
        "molecules": {
            manifest["id"]: {"path": subdir, "version": manifest["version"]}
            for subdir, manifest, _ in molecules
        },
    }
    (working / "manifest.json").write_text(
        json.dumps(publisher_manifest, indent=2)
    )

    for subdir, manifest, hook_source in molecules:
        mol_dir = working / subdir
        mol_dir.mkdir()
        (mol_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        if "atoms" in manifest and "constitution" in manifest["atoms"]:
            (mol_dir / "constitution.md").write_text(
                f"# Principle: {manifest['id']}\n"
            )
        (mol_dir / "install.py").write_text(hook_source)

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "publish molecules for US4")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head, state_root


def _make_consumer(tmp_path: Path) -> Path:
    """Create a minimal consumer repository."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [],
            }
        )
    )
    (consumer / ".harness-id").write_text("com.example.project-consumer")
    return consumer


def _run_add(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_url: str,
    molecule_ids: str,
    revision: str,
) -> int:
    """Invoke `spaex add` for the given molecule ids."""
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(
        repo_root=str(consumer),
        source_url=source_url,
        molecule_ids=molecule_ids,
        revision=revision,
        all=False,
        lock_timeout=5.0,
    )
    return add_cli.run(ns)


def _read_lock(consumer: Path) -> InstallLock:
    """Read the consumer repository's published install lock."""
    return InstallLock.from_json(
        (consumer / ".spaex" / "install.lock").read_bytes()
    )


_LOG_APPEND_HOOK = '''#!/usr/bin/env python3
"""Append the caller-supplied molecule id to hook-log.txt in the consumer repo."""
from pathlib import Path

MOLECULE_ID = {molecule_id!r}
log = Path.cwd() / "hook-log.txt"
with log.open("a", encoding="utf-8") as fh:
    fh.write(f"{{MOLECULE_ID}}\\n")
'''


_MARKER_HOOK = '''#!/usr/bin/env python3
"""Write a per-molecule marker file that proves the hook ran."""
from pathlib import Path

MOLECULE_ID = {molecule_id!r}
marker = Path.cwd() / f".hook-marker-{{MOLECULE_ID}}"
marker.write_text("ok\\n", encoding="utf-8")
'''


_ABORTING_HOOK = '''#!/usr/bin/env python3
"""Abort the install by exiting non-zero after logging its own id."""
from pathlib import Path
import sys

MOLECULE_ID = {molecule_id!r}
log = Path.cwd() / "hook-log.txt"
with log.open("a", encoding="utf-8") as fh:
    fh.write(f"{{MOLECULE_ID}}\\n")
sys.exit(1)
'''


# --- T036 AS1: deterministic multi-molecule ordering ----------------------


def test_priority_order_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two molecules with priorities 10 and 20 append to a shared log in that order."""
    low_id = f"{_PUBLISHER}.low"
    high_id = f"{_PUBLISHER}.high"
    canonical, head, state_root = _publish_molecules(
        tmp_path,
        [
            (
                "low",
                _molecule_manifest(low_id, priority=10),
                _LOG_APPEND_HOOK.format(molecule_id=low_id),
            ),
            (
                "high",
                _molecule_manifest(high_id, priority=20),
                _LOG_APPEND_HOOK.format(molecule_id=high_id),
            ),
        ],
    )
    consumer = _make_consumer(tmp_path)

    rc = _run_add(
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=f"{low_id},{high_id}",
        revision=head,
    )
    assert rc == 0

    log = (consumer / "hook-log.txt").read_text(encoding="utf-8").splitlines()
    assert log == [low_id, high_id], (
        f"expected low priority ({low_id}) before high priority ({high_id}); "
        f"got {log}"
    )


# --- T037 AS2: hook-only molecule (no atoms.constitution) -----------------


def test_hook_only_molecule_hook_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A molecule with install_hook but no atoms.constitution adopts cleanly."""
    hook_only_id = f"{_PUBLISHER}.hookonly"
    canonical, head, state_root = _publish_molecules(
        tmp_path,
        [
            (
                "hook-only",
                _molecule_manifest(hook_only_id, priority=10),
                _MARKER_HOOK.format(molecule_id=hook_only_id),
            ),
        ],
    )
    consumer = _make_consumer(tmp_path)

    rc = _run_add(
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=hook_only_id,
        revision=head,
    )
    assert rc == 0

    marker = consumer / f".hook-marker-{hook_only_id}"
    assert marker.exists(), "hook-only molecule's install_hook did not run"
    assert marker.read_text(encoding="utf-8").strip() == "ok"

    lock = _read_lock(consumer)
    assert len(lock.molecules) == 1
    entry = lock.molecules[0]
    assert entry.id == hook_only_id
    assert entry.paths == ()
    assert entry.hook_status == "ok"

    # No constitution was contributed, so .spaex/constitution.md does not exist.
    assert not (consumer / ".spaex" / "constitution.md").exists()


# --- T038 AS3: abort in the middle rolls back later hooks + all writes ----


def test_abort_stops_later_hooks_total_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three ordered hooks; middle aborts. Third never runs and every write rolls back."""
    first_id = f"{_PUBLISHER}.aa-first"
    middle_id = f"{_PUBLISHER}.bb-middle"
    third_id = f"{_PUBLISHER}.cc-third"
    canonical, head, state_root = _publish_molecules(
        tmp_path,
        [
            (
                "aa-first",
                _molecule_manifest(first_id, priority=10),
                _LOG_APPEND_HOOK.format(molecule_id=first_id),
            ),
            (
                "bb-middle",
                _molecule_manifest(
                    middle_id, priority=20, on_failure="abort"
                ),
                _ABORTING_HOOK.format(molecule_id=middle_id),
            ),
            (
                "cc-third",
                _molecule_manifest(third_id, priority=30),
                _LOG_APPEND_HOOK.format(molecule_id=third_id),
            ),
        ],
    )
    consumer = _make_consumer(tmp_path)
    original_spaex_json_bytes = (consumer / ".spaex.json").read_bytes()

    with pytest.raises(HaexError) as exc_info:
        _run_add(
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=f"{first_id},{middle_id},{third_id}",
            revision=head,
        )
    # `spaex add` wraps the install failure but preserves its diagnostic key
    # and failing-molecule context in the transaction error.
    assert exc_info.value.context.get("install_key") == "install-failed"
    cause = exc_info.value.__cause__
    assert isinstance(cause, HaexError)
    assert cause.diagnostic_key == "install-failed"
    assert cause.context.get("molecule_id") == middle_id

    log_path = consumer / "hook-log.txt"
    log = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
    # The first two hooks appended (first cleanly, middle before exiting 1);
    # the third never ran.
    assert third_id not in log, (
        f"third molecule's hook ran despite prior abort; log={log}"
    )

    # ALL .spaex writes rolled back: no constitution.md, no install.lock, no
    # published .spaex/ tree at all is required by the spec's "no .spaex-writes"
    # assertion. Any residual .spaex/ directory MUST NOT contain either file.
    spaex_dir = consumer / ".spaex"
    if spaex_dir.exists():
        assert not (spaex_dir / "constitution.md").exists(), (
            "constitution.md persisted after abort"
        )
        assert not (spaex_dir / "install.lock").exists(), (
            "install.lock persisted after abort"
        )

    # The .spaex.json compound entries were reverted to the pre-add state.
    restored_bytes = (consumer / ".spaex.json").read_bytes()
    assert restored_bytes == original_spaex_json_bytes, (
        ".spaex.json compound entries not rolled back"
    )
    restored_manifest = ConsumerManifest.from_json(restored_bytes)
    assert restored_manifest.compounds == ()
