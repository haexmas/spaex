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
                "atoms": {"skills": ["skill.md"]},
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
    written = json.loads((consumer / ".spaex.json").read_text())
    assert written["compounds"] == [
        {"source": canonical, "revision": head, "molecules": [_HELLO_ID]}
    ]
    assert (consumer / ".spaex" / "install.lock").exists()


def test_mutate_compounds_preserves_constitution_local_fragments() -> None:
    """`_mutate_compounds` reconstructs `ConsumerManifest` field-by-field; a
    project-local fragment (Spec 023 FR-018) must survive untouched."""
    from spaex.model.consumer_manifest import ConsumerManifest

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
    )

    result = add_cli._mutate_compounds(
        manifest,
        "https://example.com/publisher",
        "0" * 40,
        (_HELLO_ID,),
    )

    assert result.local_fragments == local_fragments


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
    written = json.loads((consumer / ".spaex.json").read_text())
    assert len(written["compounds"]) == 1
    assert written["compounds"][0]["molecules"] == sorted([_HELLO_ID, _WORLD_ID])


def test_replace_compound_when_same_source_different_revision(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    import subprocess

    canonical, head1, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _HELLO_ID: {
                "path": "hello",
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
        molecule_ids=_HELLO_ID,
        revision=head1,
    )
    existing = json.loads((consumer / ".spaex.json").read_text())
    existing["compounds"][0]["molecules"] = [_HELLO_ID, _WORLD_ID]
    existing["compounds"][0]["track"] = "stable"
    existing["compounds"][0]["config"] = {
        _HELLO_ID: {"priority": 7, "values": {"mode": "strict"}},
        _WORLD_ID: {"priority": 3, "values": {"mode": "legacy"}},
    }
    (consumer / ".spaex.json").write_text(json.dumps(existing))

    bare = haex_add_helpers["clone_dir"](state_root, canonical)
    advance = tmp_path / "advance-working"
    subprocess.run(["git", "clone", "-q", str(bare), str(advance)], check=True)
    haex_add_helpers["git"](advance, "config", "user.email", "t@e")
    haex_add_helpers["git"](advance, "config", "user.name", "t")
    haex_add_helpers["git"](advance, "config", "commit.gpgsign", "false")
    (advance / "hello" / "constitution.md").write_text("# v2\n")
    haex_add_helpers["git"](advance, "commit", "-q", "-am", "advance")
    haex_add_helpers["git"](advance, "push", "-q", "origin", "HEAD:main")
    head2 = haex_add_helpers["git"](advance, "rev-parse", "HEAD")

    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_HELLO_ID,
        revision=head2,
    )
    written = json.loads((consumer / ".spaex.json").read_text())
    assert len(written["compounds"]) == 1
    assert written["compounds"][0]["revision"] == head2
    assert written["compounds"][0]["track"] == "stable"
    assert written["compounds"][0]["config"] == {
        _HELLO_ID: {"priority": 7, "values": {"mode": "strict"}}
    }


def test_replace_compound_allows_renamed_singleton_molecule(
    tmp_path, monkeypatch, haex_add_helpers
) -> None:
    import subprocess

    canonical, head1, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _HELLO_ID: {
                "path": "hello",
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
        molecule_ids=_HELLO_ID,
        revision=head1,
    )

    bare = haex_add_helpers["clone_dir"](state_root, canonical)
    advance = tmp_path / "advance-renamed-working"
    subprocess.run(["git", "clone", "-q", str(bare), str(advance)], check=True)
    haex_add_helpers["git"](advance, "config", "user.email", "t@e")
    haex_add_helpers["git"](advance, "config", "user.name", "t")
    haex_add_helpers["git"](advance, "config", "commit.gpgsign", "false")
    manifest_path = advance / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["molecules"] = {
        _WORLD_ID: {
            "path": "world",
            "version": "1.0.0",
        }
    }
    manifest_path.write_text(json.dumps(manifest))
    (advance / "world").mkdir()
    (advance / "world" / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _WORLD_ID,
                "version": "1.0.0",
                "priority": 100,
                "atoms": {"constitution": ["constitution.md"]},
            }
        )
    )
    (advance / "world" / "constitution.md").write_text("# renamed\n")
    haex_add_helpers["git"](advance, "add", "manifest.json", "world")
    haex_add_helpers["git"](
        advance, "commit", "-q", "-m", "rename constitution molecule"
    )
    haex_add_helpers["git"](advance, "push", "-q", "origin", "HEAD:main")
    head2 = haex_add_helpers["git"](advance, "rev-parse", "HEAD")

    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_WORLD_ID,
        revision=head2,
    )
    written = json.loads((consumer / ".spaex.json").read_text())
    assert written["compounds"] == [
        {"source": canonical, "revision": head2, "molecules": [_WORLD_ID]}
    ]


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
    assert json.loads((consumer / ".spaex.json").read_text())["compounds"] == []


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

    assert json.loads((consumer / ".spaex.json").read_text())["compounds"] == []


def test_all_adopts_every_molecule(
    tmp_path, two_molecule_publisher, monkeypatch, haex_add_helpers
) -> None:
    canonical, head, state_root = two_molecule_publisher
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    haex_add_helpers["run_add"](
        consumer, state_root, monkeypatch, source_url=canonical, revision=head, all=True
    )
    written = json.loads((consumer / ".spaex.json").read_text())
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

    assert json.loads((consumer / ".spaex.json").read_text())["compounds"] == []


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
    written = json.loads((consumer / ".spaex.json").read_text())
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

    assert json.loads((consumer / ".spaex.json").read_text())["compounds"] == []


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
    assert json.loads((consumer / ".spaex.json").read_text())["compounds"] == []


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
