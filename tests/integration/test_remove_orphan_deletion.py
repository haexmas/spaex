"""T081 — retracted molecules' contributed paths are deleted (Spec 008 US3)."""

from __future__ import annotations

import json
from pathlib import Path

from spaex.model.install_lock import InstallLock

_CONST_ID = "com.example.publisher.const"
_SKILL_ID = "com.example.publisher.skill"


def test_orphan_paths_are_deleted_after_remove(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    """Retracting the sole constitution lands the empty state and drops its files."""
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _CONST_ID: {
                "path": "const",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_CONST_ID,
        revision=head,
    )
    lock_path = consumer / ".spaex" / "install.lock"
    installed_lock = InstallLock.from_json(lock_path.read_bytes())
    published_paths = tuple(installed_lock.molecules[0].paths)
    for rel in published_paths:
        assert (consumer / rel).exists(), f"expected {rel} to exist after add"

    rc = haex_add_helpers["run_remove"](
        consumer, state_root, monkeypatch, molecule_ids=_CONST_ID
    )
    assert rc == 0
    written = json.loads((consumer / ".spaex/manifest.json").read_text())
    assert written["compounds"] == []
    for rel in published_paths:
        assert not (consumer / rel).exists(), (
            f"retracted molecule's path {rel} should be gone after empty publish"
        )
    lock_after = InstallLock.from_json(lock_path.read_bytes())
    assert lock_after.molecules == ()


def test_survivor_files_untouched_when_one_of_many_retracted(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    """Retract one molecule of two; only the retracted molecule's files go."""
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _CONST_ID: {
                "path": "const",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
            _SKILL_ID: {
                "path": "skill",
                "version": "1.0.0",
                # A skills-only molecule contributes nothing under the tracked
                # roots — install writes an install.lock entry for it but with
                # no `paths[]` — so the manifest can drop it without any
                # orphan-deletion work. This still exercises the retraction
                # path end-to-end while keeping the surviving constitution
                # untouched.
                "atoms": {"skills": ["skill.md"]},
            },
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        revision=head,
        all=True,
    )
    lock_before = InstallLock.from_json(
        (consumer / ".spaex" / "install.lock").read_bytes()
    )
    const_paths = tuple(
        m.paths for m in lock_before.molecules if m.id == _CONST_ID
    )
    assert const_paths, "constitution molecule must record its published paths"

    # Seed a recorded path for the non-constitution molecule to model a
    # previously installed contribution. Current v3 resolution filters that
    # category, but removal must still discard every path in the prior lock.
    lock_data = json.loads((consumer / ".spaex" / "install.lock").read_text())
    retracted_path = ".codex/retracted-skill.md"
    lock_data["molecules"].append(
        {
            "id": _SKILL_ID,
            "source": canonical,
            "revision": head,
            "paths": [retracted_path],
        }
    )
    (consumer / ".spaex" / "install.lock").write_text(json.dumps(lock_data))
    (consumer / retracted_path).parent.mkdir(parents=True, exist_ok=True)
    (consumer / retracted_path).write_text("# previously installed skill\n")
    lock_before = InstallLock.from_json(
        (consumer / ".spaex" / "install.lock").read_bytes()
    )
    retracted_entries = tuple(m for m in lock_before.molecules if m.id == _SKILL_ID)
    assert retracted_entries and retracted_entries[0].paths == (retracted_path,)

    rc = haex_add_helpers["run_remove"](
        consumer, state_root, monkeypatch, molecule_ids=_SKILL_ID
    )
    assert rc == 0

    lock_after = InstallLock.from_json(
        (consumer / ".spaex" / "install.lock").read_bytes()
    )
    surviving_ids = {m.id for m in lock_after.molecules}
    assert _CONST_ID in surviving_ids
    assert _SKILL_ID not in surviving_ids
    for entry in retracted_entries:
        for rel in entry.paths:
            assert not (consumer / rel).exists(), f"orphan {rel} was not deleted"
    for path_tuple in const_paths:
        for rel in path_tuple:
            assert (consumer / rel).exists(), f"survivor {rel} was deleted"
