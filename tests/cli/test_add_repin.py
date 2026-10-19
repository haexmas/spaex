"""T063 — CLI tests for `spaex add` re-pinning a source at a new revision (Spec 013 FR-018)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spaex.util.errors import ConstitutionAlreadyAdoptedError, MoleculeIdNotInSourceError

_HELLO_ID = "com.example.publisher.hello"
_WORLD_ID = "com.example.publisher.world"
_GAMMA_ID = "com.example.publisher.gamma"


def _three_molecules() -> dict:
    return {
        _HELLO_ID: {
            "path": "hello",
            "version": "1.0.0",
            "atoms": {"instructions": ["hello.md"]},
        },
        _WORLD_ID: {
            "path": "world",
            "version": "1.0.0",
            "atoms": {"instructions": ["world.md"]},
        },
        _GAMMA_ID: {
            "path": "gamma",
            "version": "1.0.0",
            "atoms": {"instructions": ["gamma.md"]},
        },
    }


def _advance_publisher(tmp_path: Path, helpers, canonical: str, state_root: Path, edit) -> str:
    """Push one more commit to the fixture publisher; `edit(working_dir)` mutates it."""
    import subprocess

    bare = helpers["clone_dir"](state_root, canonical)
    working = tmp_path / "advance-working"
    subprocess.run(["git", "clone", "-q", str(bare), str(working)], check=True)
    helpers["git"](working, "config", "user.email", "t@e")
    helpers["git"](working, "config", "user.name", "t")
    helpers["git"](working, "config", "commit.gpgsign", "false")
    edit(working)
    helpers["git"](working, "add", "-A")
    helpers["git"](working, "commit", "-q", "-m", "advance")
    helpers["git"](working, "push", "-q", "origin", "HEAD:main")
    return helpers["git"](working, "rev-parse", "HEAD")


def _touch_hello(working: Path) -> None:
    (working / "hello" / "hello.md").write_text("# v2\n")


def _drop_world(working: Path) -> None:
    manifest_file = working / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    del manifest["molecules"][_WORLD_ID]
    manifest_file.write_text(json.dumps(manifest))


def _adopt_hello_and_world(tmp_path, monkeypatch, helpers):
    canonical, head1, state_root = helpers["make_publisher"](
        tmp_path, _three_molecules()
    )
    consumer = helpers["make_consumer"](tmp_path)
    helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=f"{_HELLO_ID},{_WORLD_ID}",
        revision=head1,
    )
    manifest_file = consumer / ".spaex/manifest.json"
    existing = json.loads(manifest_file.read_text())
    existing["compounds"][0]["track"] = "stable"
    existing["compounds"][0]["config"] = {
        _HELLO_ID: {"priority": 7, "values": {"mode": "strict"}},
        _WORLD_ID: {"priority": 3, "values": {"mode": "legacy"}},
    }
    manifest_file.write_text(json.dumps(existing))
    return canonical, head1, state_root, consumer


def test_add_at_new_revision_keeps_existing_molecules(
    tmp_path, monkeypatch, haex_add_helpers, capsys
) -> None:
    canonical, head1, state_root, consumer = _adopt_hello_and_world(
        tmp_path, monkeypatch, haex_add_helpers
    )
    head2 = _advance_publisher(tmp_path, haex_add_helpers, canonical, state_root, _touch_hello)
    capsys.readouterr()

    rc = haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_GAMMA_ID,
        revision=head2,
    )

    assert rc == 0
    written = json.loads((consumer / ".spaex/manifest.json").read_text())
    assert len(written["compounds"]) == 1
    compound = written["compounds"][0]
    assert compound["revision"] == head2
    assert compound["molecules"] == sorted([_HELLO_ID, _WORLD_ID, _GAMMA_ID])
    assert compound["track"] == "stable"
    assert compound["config"] == {
        _HELLO_ID: {"priority": 7, "values": {"mode": "strict"}},
        _WORLD_ID: {"priority": 3, "values": {"mode": "legacy"}},
    }
    out = capsys.readouterr().out
    added_part, _, carried_part = out.partition("re-pinned")
    assert _GAMMA_ID in added_part
    assert _HELLO_ID not in added_part
    assert f"{head1[:12]} -> {head2[:12]}" in carried_part
    assert _HELLO_ID in carried_part
    assert _WORLD_ID in carried_part
    assert _GAMMA_ID not in carried_part


def test_add_at_new_revision_without_carried_over_molecules_has_no_repin_section(
    tmp_path, monkeypatch, haex_add_helpers, capsys
) -> None:
    canonical, head1, state_root = haex_add_helpers["make_publisher"](
        tmp_path, _three_molecules()
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_HELLO_ID,
        revision=head1,
    )
    head2 = _advance_publisher(tmp_path, haex_add_helpers, canonical, state_root, _touch_hello)
    capsys.readouterr()

    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_HELLO_ID,
        revision=head2,
    )

    written = json.loads((consumer / ".spaex/manifest.json").read_text())
    assert written["compounds"] == [
        {"source": canonical, "revision": head2, "molecules": [_HELLO_ID]}
    ]
    assert "re-pinned" not in capsys.readouterr().out


def test_add_at_new_revision_refuses_when_carried_over_molecule_is_gone(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    canonical, _, state_root, consumer = _adopt_hello_and_world(
        tmp_path, monkeypatch, haex_add_helpers
    )
    head2 = _advance_publisher(tmp_path, haex_add_helpers, canonical, state_root, _drop_world)
    manifest_file = consumer / ".spaex/manifest.json"
    before = manifest_file.read_bytes()

    with pytest.raises(MoleculeIdNotInSourceError) as exc_info:
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=_GAMMA_ID,
            revision=head2,
        )

    assert _WORLD_ID in exc_info.value.message
    assert "remove" in exc_info.value.hint
    assert manifest_file.read_bytes() == before


def test_add_at_new_revision_checks_carried_over_molecules_for_singleton_conflicts(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    canonical, _, state_root, consumer = _adopt_hello_and_world(
        tmp_path, monkeypatch, haex_add_helpers
    )

    def hello_gains_constitution(working: Path) -> None:
        (working / "hello" / "constitution.md").write_text("# rules\n")
        manifest_file = working / "hello" / "manifest.json"
        manifest = json.loads(manifest_file.read_text())
        manifest["atoms"]["constitution"] = ["constitution.md"]
        manifest_file.write_text(json.dumps(manifest))
        (working / "gamma" / "constitution.md").write_text("# other rules\n")
        gamma_file = working / "gamma" / "manifest.json"
        gamma = json.loads(gamma_file.read_text())
        gamma["atoms"]["constitution"] = ["constitution.md"]
        gamma_file.write_text(json.dumps(gamma))

    head2 = _advance_publisher(
        tmp_path, haex_add_helpers, canonical, state_root, hello_gains_constitution
    )
    manifest_file = consumer / ".spaex/manifest.json"
    before = manifest_file.read_bytes()

    with pytest.raises(ConstitutionAlreadyAdoptedError):
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=_GAMMA_ID,
            revision=head2,
        )

    assert manifest_file.read_bytes() == before


def test_add_local_at_new_revision_keeps_existing_overlay_molecules(
    tmp_path, monkeypatch, haex_add_helpers, capsys
) -> None:
    canonical, head1, state_root = haex_add_helpers["make_publisher"](
        tmp_path, _three_molecules()
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=f"{_HELLO_ID},{_WORLD_ID}",
        revision=head1,
        local=True,
    )
    head2 = _advance_publisher(tmp_path, haex_add_helpers, canonical, state_root, _touch_hello)
    capsys.readouterr()

    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_GAMMA_ID,
        revision=head2,
        local=True,
    )

    overlay = json.loads((consumer / ".spaex/local/manifest.json").read_text())
    assert overlay["compounds"] == [
        {
            "source": canonical,
            "revision": head2,
            "molecules": sorted([_HELLO_ID, _WORLD_ID, _GAMMA_ID]),
        }
    ]
    out = capsys.readouterr().out
    assert f"{head1[:12]} -> {head2[:12]}" in out
    assert json.loads((consumer / ".spaex/manifest.json").read_text())["compounds"] == []


def test_add_local_at_new_revision_checks_singleton_conflicts(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    canonical, head1, state_root = haex_add_helpers["make_publisher"](
        tmp_path, _three_molecules()
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_HELLO_ID,
        revision=head1,
        local=True,
    )

    def hello_and_gamma_gain_constitution(working: Path) -> None:
        for molecule_id in (_HELLO_ID, _GAMMA_ID):
            molecule_dir = working / molecule_id.rsplit(".", 1)[-1]
            (molecule_dir / "constitution.md").write_text("# rules\n")
            manifest_file = molecule_dir / "manifest.json"
            manifest = json.loads(manifest_file.read_text())
            manifest["atoms"]["constitution"] = ["constitution.md"]
            manifest_file.write_text(json.dumps(manifest))

    head2 = _advance_publisher(
        tmp_path,
        haex_add_helpers,
        canonical,
        state_root,
        hello_and_gamma_gain_constitution,
    )
    overlay_file = consumer / ".spaex/local/manifest.json"
    before = overlay_file.read_bytes()

    with pytest.raises(ConstitutionAlreadyAdoptedError):
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=_GAMMA_ID,
            revision=head2,
            local=True,
        )

    assert overlay_file.read_bytes() == before


def test_add_local_refusal_for_gone_carried_over_molecule_hints_local_remove(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    canonical, head1, state_root = haex_add_helpers["make_publisher"](
        tmp_path, _three_molecules()
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=f"{_HELLO_ID},{_WORLD_ID}",
        revision=head1,
        local=True,
    )
    head2 = _advance_publisher(tmp_path, haex_add_helpers, canonical, state_root, _drop_world)
    overlay_file = consumer / ".spaex/local/manifest.json"
    before = overlay_file.read_bytes()

    with pytest.raises(MoleculeIdNotInSourceError) as exc_info:
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=_GAMMA_ID,
            revision=head2,
            local=True,
        )

    assert f"spaex remove --local {_WORLD_ID}" in exc_info.value.hint
    assert overlay_file.read_bytes() == before
