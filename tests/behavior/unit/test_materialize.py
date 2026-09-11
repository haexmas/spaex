"""Materialize unit tests (Spec 023 T013).

Covers the three fragment-source variants materialize handles:
- Standalone fragment atom (file listed in manifest.atoms.behavior).
- Typed-atom inline block (MoleculeManifest.constitution_fragments).
- Project-local fragment (routes to `_project` scope, FR-018 stub).

The full install-transaction wiring lands in T029; here we exercise
materialize directly against a caller-owned staging tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spaex.behavior.fragment import PROJECT_SCOPE, BehaviorFragment, Modality
from spaex.behavior.materialize import MoleculeInput, materialize, project_local_from_config
from spaex.model.molecule_manifest import MoleculeManifest

MOL_A = "com.example.mol-a"
MOL_B = "com.example.mol-b"


def _manifest_bytes(
    *,
    molecule_id: str,
    behavior_paths: list[str] | None = None,
    constitution_fragments: dict | None = None,
) -> bytes:
    manifest: dict = {
        "spaex_version": "4",
        "id": molecule_id,
        "version": "1.0.0",
        "priority": 100,
        "atoms": {"behavior": behavior_paths} if behavior_paths else {"other": ["README.md"]},
    }
    if constitution_fragments is not None:
        manifest["constitution_fragments"] = constitution_fragments
    return json.dumps(manifest).encode("utf-8")


def _write_standalone_fragment(
    root: Path, *, rel: str, id_: str, body: str, atom_source: str = "behavior.rule"
) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "---\n"
        f"id: {id_}\n"
        "kind: constitution_fragment\n"
        f"atom_source: {atom_source}\n"
        "modality: MUST\n"
        "---\n"
    )
    target.write_text(header + body, encoding="utf-8")


def test_materialize_standalone_fragment_atom(tmp_path: Path) -> None:
    """A molecule shipping one standalone fragment file gets it staged."""
    molecule_dir = tmp_path / "molecule-a"
    _write_standalone_fragment(
        molecule_dir,
        rel="atoms/behavior/rule.md",
        id_="rule",
        body="**MUST** do a thing.\n",
    )
    manifest = MoleculeManifest.from_json(
        _manifest_bytes(molecule_id=MOL_A, behavior_paths=["atoms/behavior/rule.md"])
    )
    staging = tmp_path / "staging"
    result = materialize(
        [MoleculeInput(molecule_id=MOL_A, manifest=manifest, molecule_dir=molecule_dir)],
        staging_root=staging,
    )
    assert len(result) == 1
    (m,) = result
    assert m.fragment.scoped_id == f"{MOL_A}/rule"
    assert m.fragment.modality is Modality.MUST
    expected_path = staging / MOL_A / "rule.md"
    assert m.staging_path == expected_path
    assert expected_path.exists()
    # Written file must be reparseable back into an equivalent BehaviorFragment.
    reparsed = BehaviorFragment.from_file(expected_path, molecule_id=MOL_A)
    assert reparsed.body_hash == m.fragment.body_hash
    assert reparsed.id == "rule"


def test_materialize_typed_atom_inline_block(tmp_path: Path) -> None:
    """An inline constitution_fragments block materializes identically."""
    manifest = MoleculeManifest.from_json(
        _manifest_bytes(
            molecule_id=MOL_A,
            constitution_fragments={
                "speckit-strict": [
                    {
                        "id": "spec-first",
                        "modality": "MUST",
                        "tags": ["speckit"],
                        "body": "**MUST** run /speckit-specify first.",
                    }
                ]
            },
        )
    )
    staging = tmp_path / "staging"
    result = materialize(
        [
            MoleculeInput(
                molecule_id=MOL_A,
                manifest=manifest,
                molecule_dir=tmp_path / "unused-because-inline-only",
            )
        ],
        staging_root=staging,
    )
    assert len(result) == 1
    (m,) = result
    assert m.fragment.id == "spec-first"
    assert m.fragment.atom_source == "speckit-strict"
    assert m.fragment.tags == ("speckit",)
    assert m.staging_path == staging / MOL_A / "spec-first.md"


def test_project_local_fragment_routes_to_project_scope(tmp_path: Path) -> None:
    """Project-local fragments materialize under `_project/<fragment-id>.md`."""
    local = project_local_from_config(
        [
            {
                "id": "http-through-shared-client",
                "modality": "MUST",
                "body": "**MUST** route HTTP through the shared client.",
            }
        ]
    )
    staging = tmp_path / "staging"
    result = materialize([], staging_root=staging, project_local=local)
    assert len(result) == 1
    (m,) = result
    assert m.fragment.molecule_id == PROJECT_SCOPE
    assert m.fragment.scoped_id == f"{PROJECT_SCOPE}/http-through-shared-client"
    assert m.staging_path == staging / PROJECT_SCOPE / "http-through-shared-client.md"


def test_project_local_from_config_resolves_file_reference(tmp_path: Path) -> None:
    """A `{"file": ...}` entry (T044) resolves against repo_root and parses
    the referenced fragment file, same as a standalone atom fragment."""
    (tmp_path / ".spaex" / "local-fragments").mkdir(parents=True)
    (tmp_path / ".spaex" / "local-fragments" / "no-secrets.md").write_text(
        "---\n"
        "id: no-secrets\n"
        "kind: constitution_fragment\n"
        "atom_source: project\n"
        "modality: MUST_NOT\n"
        "---\n"
        "**MUST NOT** commit secrets to git.\n"
    )

    fragments = project_local_from_config(
        [{"file": ".spaex/local-fragments/no-secrets.md"}], repo_root=tmp_path
    )

    assert len(fragments) == 1
    assert fragments[0].id == "no-secrets"
    assert fragments[0].molecule_id == PROJECT_SCOPE
    assert fragments[0].modality == Modality.MUST_NOT


def test_project_local_from_config_file_reference_without_repo_root_raises() -> None:
    """A file-reference entry cannot resolve without a repo_root anchor."""
    with pytest.raises(ValueError, match="repo_root"):
        project_local_from_config([{"file": "fragments/x.md"}])


def test_project_local_from_config_rejects_symlink_escape(tmp_path: Path) -> None:
    """Reject a file reference whose symlink target leaves the repository."""
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text(
        "---\nid: outside\nkind: constitution_fragment\n---\nbody\n",
        encoding="utf-8",
    )
    link = tmp_path / "fragments" / "escape.md"
    link.parent.mkdir()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available")

    with pytest.raises(ValueError, match="escapes repository root"):
        project_local_from_config([{"file": "fragments/escape.md"}], repo_root=tmp_path)


def test_materialize_orders_fragments_stably(tmp_path: Path) -> None:
    """Result order is (molecule_id, fragment_id) so downstream hashing is stable."""
    dir_b = tmp_path / "mol-b"
    _write_standalone_fragment(
        dir_b, rel="b1.md", id_="alpha", body="**MUST** a.\n"
    )
    _write_standalone_fragment(
        dir_b, rel="b2.md", id_="beta", body="**MUST** b.\n"
    )
    dir_a = tmp_path / "mol-a"
    _write_standalone_fragment(dir_a, rel="a.md", id_="gamma", body="**MUST** g.\n")

    manifest_b = MoleculeManifest.from_json(
        _manifest_bytes(molecule_id=MOL_B, behavior_paths=["b1.md", "b2.md"])
    )
    manifest_a = MoleculeManifest.from_json(
        _manifest_bytes(molecule_id=MOL_A, behavior_paths=["a.md"])
    )
    staging = tmp_path / "staging"

    result = materialize(
        [
            MoleculeInput(MOL_B, manifest_b, dir_b),
            MoleculeInput(MOL_A, manifest_a, dir_a),
        ],
        staging_root=staging,
    )
    scoped = [m.fragment.scoped_id for m in result]
    assert scoped == [
        f"{MOL_A}/gamma",
        f"{MOL_B}/alpha",
        f"{MOL_B}/beta",
    ]


def test_materialize_writes_to_staging_not_constitution_d(tmp_path: Path) -> None:
    """Assert nothing gets written outside the caller-owned staging tree."""
    molecule_dir = tmp_path / "mol"
    _write_standalone_fragment(
        molecule_dir, rel="r.md", id_="rule", body="**MUST** honor.\n"
    )
    manifest = MoleculeManifest.from_json(
        _manifest_bytes(molecule_id=MOL_A, behavior_paths=["r.md"])
    )
    consumer_root = tmp_path / "consumer"
    consumer_root.mkdir()
    (consumer_root / ".spaex").mkdir()  # would-be publish target
    staging = tmp_path / "custom-staging"
    materialize(
        [MoleculeInput(MOL_A, manifest, molecule_dir)],
        staging_root=staging,
    )
    # Nothing landed under the consumer's .spaex tree.
    assert list((consumer_root / ".spaex").iterdir()) == []
    # Everything landed under the caller-owned staging root.
    assert (staging / MOL_A / "rule.md").exists()


def test_materialize_deduplicates_before_writing(tmp_path: Path) -> None:
    molecule_dir = tmp_path / "mol"
    _write_standalone_fragment(
        molecule_dir, rel="a.md", id_="rule", body="**MUST** same.\n", atom_source="a"
    )
    _write_standalone_fragment(
        molecule_dir, rel="b.md", id_="rule", body="**MUST** same.\n", atom_source="b"
    )
    manifest = MoleculeManifest.from_json(
        _manifest_bytes(molecule_id=MOL_A, behavior_paths=["b.md", "a.md"])
    )

    result = materialize(
        [MoleculeInput(MOL_A, manifest, molecule_dir)],
        staging_root=tmp_path / "staging",
    )

    assert len(result) == 1
    assert result[0].fragment.atom_source == "a"
    assert [item.atom_source for item in result[0].dedup_provenance] == ["b"]
    assert list((tmp_path / "staging" / MOL_A).glob("*.md")) == [
        tmp_path / "staging" / MOL_A / "rule.md"
    ]


def test_materialize_quotes_yaml_scalar_strings(tmp_path: Path) -> None:
    manifest = MoleculeManifest.from_json(
        _manifest_bytes(
            molecule_id=MOL_A,
            constitution_fragments={
                "true": [
                    {
                        "id": "123",
                        "atom_source": "null",
                        "modality": "MUST",
                        "tags": ["true", "123"],
                        "body": "**MUST** preserve strings.",
                    }
                ]
            },
        )
    )

    result = materialize(
        [MoleculeInput(MOL_A, manifest, tmp_path)],
        staging_root=tmp_path / "staging",
    )
    reparsed = BehaviorFragment.from_file(
        result[0].staging_path, molecule_id=MOL_A
    )

    assert reparsed.id == "123"
    assert reparsed.atom_source == "null"
    assert reparsed.tags == ("true", "123")


def test_project_local_fragment_with_wrong_scope_raises(tmp_path: Path) -> None:
    """Guard: caller must build project-local fragments via project_local_from_config."""
    bad = BehaviorFragment.from_bytes(
        b"---\nid: x\nkind: constitution_fragment\natom_source: a\n---\nbody\n",
        molecule_id="not-project",
    )
    with pytest.raises(ValueError, match="_project"):
        materialize([], staging_root=tmp_path / "staging", project_local=[bad])
