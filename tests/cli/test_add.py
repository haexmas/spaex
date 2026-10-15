"""T063 — CLI tests for `spaex add` (Spec 013)."""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import add as add_cli
from spaex.util.errors import (
    ConstitutionAlreadyAdoptedError,
    InteractiveSelectionUnavailableError,
    MoleculeIdNotInSourceError,
    PublisherManifestInvalidError,
    PublisherManifestMissingError,
    UsageError,
    WorkflowMoleculeAlreadyAdoptedError,
)

_HELLO_ID = "com.example.publisher.hello"
_WORLD_ID = "com.example.publisher.world"


@pytest.fixture
def two_molecule_publisher(tmp_path: Path, haex_add_helpers):
    return haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _HELLO_ID: {
                "path": "hello",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
            _WORLD_ID: {
                "path": "world",
                "version": "1.0.0",
                "atoms": {"instructions": ["skill.md"]},
            },
        },
    )


def test_happy_path_adopts_single_molecule(
    tmp_path, two_molecule_publisher, monkeypatch, haex_add_helpers
) -> None:
    canonical, head, state_root = two_molecule_publisher
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    rc = haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_HELLO_ID,
        revision=head,
    )
    assert rc == 0
    written = json.loads((consumer / ".spaex/manifest.json").read_text())
    assert written["compounds"] == [
        {"source": canonical, "revision": head, "molecules": [_HELLO_ID]}
    ]
    assert (consumer / ".spaex" / "install.lock").exists()


def test_mutate_compounds_preserves_non_compound_fields() -> None:
    """Only `compounds` changes; a project-local fragment (Spec 023 FR-018)
    and a persisted skill policy (Spec 018) must survive untouched."""
    from spaex.model.consumer_manifest import ConsumerManifest, SkillInstallationPolicy

    local_fragments = (
        {
            "id": "shared-client",
            "modality": "MUST",
            "body": "**MUST** route HTTP through the shared client.",
        },
    )
    manifest = ConsumerManifest(
        spaex_version="4",
        identity="com.example.project",
        compounds=(),
        local_fragments=local_fragments,
        skill_installation=SkillInstallationPolicy(
            mode="managed", adapter="skillsmd", scope="project", agents=("claude",)
        ),
    )

    result = add_cli._mutate_compounds(
        manifest,
        "https://example.com/publisher",
        "0" * 40,
        (_HELLO_ID,),
    )

    assert result.local_fragments == local_fragments
    assert result.skill_installation == manifest.skill_installation


def test_merge_into_existing_compound_same_source_and_revision(
    tmp_path, two_molecule_publisher, monkeypatch, haex_add_helpers
) -> None:
    canonical, head, state_root = two_molecule_publisher
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_HELLO_ID,
        revision=head,
    )
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_WORLD_ID,
        revision=head,
    )
    written = json.loads((consumer / ".spaex/manifest.json").read_text())
    assert len(written["compounds"]) == 1
    assert written["compounds"][0]["molecules"] == sorted([_HELLO_ID, _WORLD_ID])


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

    def drop_world(working: Path) -> None:
        manifest_file = working / "manifest.json"
        manifest = json.loads(manifest_file.read_text())
        del manifest["molecules"][_WORLD_ID]
        manifest_file.write_text(json.dumps(manifest))

    head2 = _advance_publisher(tmp_path, haex_add_helpers, canonical, state_root, drop_world)
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


def test_all_rejects_multiple_singleton_declarers(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            "com.example.publisher.const-a": {
                "path": "const-a",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
            "com.example.publisher.const-b": {
                "path": "const-b",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    with pytest.raises(ConstitutionAlreadyAdoptedError):
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            revision=head,
            all=True,
        )
    assert json.loads((consumer / ".spaex/manifest.json").read_text())["compounds"] == []


def test_non_tty_without_ids_or_all_refuses(
    tmp_path, two_molecule_publisher, monkeypatch, haex_add_helpers
) -> None:
    canonical, head, state_root = two_molecule_publisher
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(InteractiveSelectionUnavailableError):
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            revision=head,
        )


def test_interactive_separator_only_selection_refuses(
    tmp_path, two_molecule_publisher, monkeypatch, haex_add_helpers
) -> None:
    canonical, head, state_root = two_molecule_publisher
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    class TTYStringIO(StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", TTYStringIO(",,\n"))

    with pytest.raises(UsageError, match="selection was empty"):
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            revision=head,
        )

    assert json.loads((consumer / ".spaex/manifest.json").read_text())["compounds"] == []


def test_all_adopts_every_molecule(
    tmp_path, two_molecule_publisher, monkeypatch, haex_add_helpers
) -> None:
    canonical, head, state_root = two_molecule_publisher
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    haex_add_helpers["run_add"](
        consumer, state_root, monkeypatch, source_url=canonical, revision=head, all=True
    )
    written = json.loads((consumer / ".spaex/manifest.json").read_text())
    assert written["compounds"][0]["molecules"] == sorted([_HELLO_ID, _WORLD_ID])


def test_all_with_empty_publisher_refuses_without_manifest_edit(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    canonical, head, state_root = haex_add_helpers["make_publisher"](tmp_path, {})
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    monkeypatch.setattr(
        add_cli.PublisherManifest,
        "from_json",
        lambda raw: SimpleNamespace(publisher=canonical, molecules={}),
    )

    with pytest.raises(UsageError, match="selection was empty"):
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            revision=head,
            all=True,
        )

    assert json.loads((consumer / ".spaex/manifest.json").read_text())["compounds"] == []


def test_molecule_id_not_in_source_refuses(
    tmp_path, two_molecule_publisher, monkeypatch, haex_add_helpers
) -> None:
    canonical, head, state_root = two_molecule_publisher
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    with pytest.raises(MoleculeIdNotInSourceError):
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids="com.example.publisher.does-not-exist",
            revision=head,
        )
    written = json.loads((consumer / ".spaex/manifest.json").read_text())
    assert written["compounds"] == []


def test_workflow_molecule_already_adopted_refuses(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    workflow_a = "com.example.publisher.workflow-a"
    workflow_b = "com.example.publisher.workflow-b"
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            workflow_a: {
                "path": "wa",
                "version": "1.0.0",
                "atoms": {"workflow": ["speckit.md"]},
            },
            workflow_b: {
                "path": "wb",
                "version": "1.0.0",
                "atoms": {"workflow": ["speckit.md"]},
            },
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    constitution_canonical, con_head, _ = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            "com.example.publisher.const": {
                "path": "c",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
        },
        name="constitution-source",
    )
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=constitution_canonical,
        molecule_ids="com.example.publisher.const",
        revision=con_head,
    )
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=workflow_a,
        revision=head,
    )
    with pytest.raises(WorkflowMoleculeAlreadyAdoptedError):
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=workflow_b,
            revision=head,
        )


def test_multiple_new_workflow_molecules_refuse_as_singleton_conflict(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    workflow_a = "com.example.publisher.workflow-a"
    workflow_b = "com.example.publisher.workflow-b"
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            workflow_a: {
                "path": "wa",
                "version": "1.0.0",
                "atoms": {"workflow": ["speckit.md"]},
            },
            workflow_b: {
                "path": "wb",
                "version": "1.0.0",
                "atoms": {"workflow": ["speckit.md"]},
            },
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    with pytest.raises(WorkflowMoleculeAlreadyAdoptedError, match="multiple molecules"):
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=f"{workflow_a},{workflow_b}",
            revision=head,
        )

    assert json.loads((consumer / ".spaex/manifest.json").read_text())["compounds"] == []


def test_all_with_positional_ids_is_usage_error(
    tmp_path, two_molecule_publisher, monkeypatch, haex_add_helpers
) -> None:
    canonical, head, state_root = two_molecule_publisher
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    with pytest.raises(UsageError):
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=_HELLO_ID,
            revision=head,
            all=True,
        )


def _make_publisher_without_root_manifest(
    tmp_path: Path, haex_add_helpers
) -> tuple[str, str, Path]:
    """Build a publisher whose resolved SHA has NO manifest.json at root.

    Uses the shared fixture to lay down the tree, then rewrites HEAD to a
    commit whose tree omits manifest.json entirely. This exercises the
    `publisher-manifest-missing` path distinct from `publisher-manifest-invalid`.
    """
    import subprocess

    canonical, _initial_head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _HELLO_ID: {
                "path": "hello",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
        },
    )
    bare = haex_add_helpers["clone_dir"](state_root, canonical)
    working = tmp_path / "no-root-working"
    subprocess.run(["git", "clone", "-q", str(bare), str(working)], check=True)
    haex_add_helpers["git"](working, "config", "user.email", "t@e")
    haex_add_helpers["git"](working, "config", "user.name", "t")
    haex_add_helpers["git"](working, "config", "commit.gpgsign", "false")
    haex_add_helpers["git"](working, "rm", "-q", "manifest.json")
    haex_add_helpers["git"](working, "commit", "-q", "-m", "drop root manifest")
    haex_add_helpers["git"](working, "push", "-q", "origin", "HEAD:main")
    new_head = haex_add_helpers["git"](working, "rev-parse", "HEAD")
    return canonical, new_head, state_root


def test_missing_publisher_root_manifest_refuses_with_missing_key(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    """The resolved SHA has no manifest.json at root -> publisher-manifest-missing.

    Distinct from `publisher-manifest-invalid`, which fires when the file is
    present but malformed or wrong-schema. Contract requires the two to be
    surfaced with different diagnostic keys.
    """
    canonical, head, state_root = _make_publisher_without_root_manifest(
        tmp_path, haex_add_helpers
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    with pytest.raises(PublisherManifestMissingError) as exc_info:
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=_HELLO_ID,
            revision=head,
        )
    assert exc_info.value.diagnostic_key == "publisher-manifest-missing"
    assert exc_info.value.context["source"] == canonical
    assert exc_info.value.context["revision"] == head
    # Manifest untouched.
    assert json.loads((consumer / ".spaex/manifest.json").read_text())["compounds"] == []


def test_malformed_publisher_root_manifest_refuses_with_invalid_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, haex_add_helpers
) -> None:
    """Present but schema-invalid publisher manifest -> publisher-manifest-invalid.

    Uses a v2 publisher manifest (top-level `atoms:` instead of `molecules:`)
    at the resolved SHA to exercise the schema-mismatch branch. Confirms it
    stays on the -invalid key, not the -missing one.
    """
    import subprocess

    canonical, _initial_head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _HELLO_ID: {
                "path": "hello",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
        },
    )
    bare = haex_add_helpers["clone_dir"](state_root, canonical)
    working = tmp_path / "v2-root-working"
    subprocess.run(["git", "clone", "-q", str(bare), str(working)], check=True)
    haex_add_helpers["git"](working, "config", "user.email", "t@e")
    haex_add_helpers["git"](working, "config", "user.name", "t")
    haex_add_helpers["git"](working, "config", "commit.gpgsign", "false")
    (working / "manifest.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "2",
                "publisher": "com.example.publisher",
                "atoms": {
                    _HELLO_ID: {"path": "hello", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )
    haex_add_helpers["git"](working, "commit", "-q", "-am", "regress root to v2")
    haex_add_helpers["git"](working, "push", "-q", "origin", "HEAD:main")
    v2_head = haex_add_helpers["git"](working, "rev-parse", "HEAD")

    consumer = haex_add_helpers["make_consumer"](tmp_path)
    with pytest.raises(PublisherManifestInvalidError) as exc_info:
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=_HELLO_ID,
            revision=v2_head,
        )
    assert exc_info.value.diagnostic_key == "publisher-manifest-invalid"
