"""Precheck unit tests (Spec 023 T015).

Covers the mechanical pre-check paths:
- intra-molecule id collision with contradictory modality (exit 20)
- duplicate id + same modality + different body (exit 20)
- duplicate id + same modality + identical normalized body (silent dedupe
  with dedup provenance)
- project-local additive-only (exit 22)
- malformed fragment guard (defensive — parser should catch first)

The Fragment schema validation errors themselves live in T010 (parser
rejects malformed fragments up-front); this test file exercises what
gets past the parser.
"""

from __future__ import annotations

import pytest

from spaex.behavior.fragment import PROJECT_SCOPE, BehaviorFragment, Modality
from spaex.behavior.precheck import (
    DuplicateBodyMismatchError,
    IntraMoleculeCollisionError,
    MalformedFragmentError,
    ProjectLocalOverrideError,
    precheck,
)
from spaex.util import exit_codes


def _frag(
    *,
    id_: str,
    molecule_id: str = "com.example.mol",
    atom_source: str = "atoms.a",
    modality: Modality | None = Modality.MUST,
    body: str = "**MUST** honor.\n",
) -> BehaviorFragment:
    return BehaviorFragment(
        id=id_,
        kind="constitution_fragment",
        atom_source=atom_source,
        modality=modality,
        tags=(),
        body=body,
        molecule_id=molecule_id,
    )


def test_precheck_of_singleton_returns_fragment_unchanged() -> None:
    frag = _frag(id_="rule")
    result = precheck([frag])
    assert result.fragments == (frag,)
    assert result.dedup_provenance == {}


def test_intra_molecule_modality_collision_rejected_with_exit_20() -> None:
    a = _frag(id_="rule", atom_source="atoms.a", modality=Modality.MUST)
    b = _frag(id_="rule", atom_source="atoms.b", modality=Modality.SHOULD)
    with pytest.raises(IntraMoleculeCollisionError) as excinfo:
        precheck([a, b])
    assert excinfo.value.exit_code == exit_codes.BEHAVIOR_PRECHECK_REFUSE == 20


def test_duplicate_id_same_modality_identical_body_dedupes_silently() -> None:
    a = _frag(id_="rule", atom_source="atoms.a", body="**MUST** honor.\n")
    b = _frag(id_="rule", atom_source="atoms.b", body="**MUST** honor.\n")
    result = precheck([a, b])
    assert len(result.fragments) == 1
    canonical = result.fragments[0]
    assert canonical.scoped_id == "com.example.mol/rule"
    assert canonical.scoped_id in result.dedup_provenance
    extras = result.dedup_provenance[canonical.scoped_id]
    assert len(extras) == 1


def test_duplicate_id_same_modality_body_mismatch_rejected_exit_20() -> None:
    a = _frag(id_="rule", atom_source="atoms.a", body="**MUST** honor A.\n")
    b = _frag(id_="rule", atom_source="atoms.b", body="**MUST** honor B.\n")
    with pytest.raises(DuplicateBodyMismatchError) as excinfo:
        precheck([a, b])
    assert excinfo.value.exit_code == 20


def test_duplicate_id_same_body_after_normalization_deduped() -> None:
    """CRLF vs LF must not defeat the dedupe (research.md §7 normalization)."""
    a = _frag(id_="rule", atom_source="atoms.a", body="**MUST** honor.\n")
    b = _frag(id_="rule", atom_source="atoms.b", body="**MUST** honor.\r\n\r\n")
    result = precheck([a, b])
    assert len(result.fragments) == 1


def test_different_molecules_same_id_are_not_a_collision() -> None:
    """Ids are molecule-scoped; cross-molecule same-id is not a collision."""
    a = _frag(id_="rule", molecule_id="com.example.mol-a")
    b = _frag(id_="rule", molecule_id="com.example.mol-b")
    result = precheck([a, b])
    assert {f.scoped_id for f in result.fragments} == {
        "com.example.mol-a/rule",
        "com.example.mol-b/rule",
    }


def test_project_local_matches_atom_id_rejected_exit_22() -> None:
    atom = _frag(id_="rule", molecule_id="com.example.mol")
    local = _frag(id_="rule", molecule_id=PROJECT_SCOPE, atom_source="_project")
    with pytest.raises(ProjectLocalOverrideError) as excinfo:
        precheck([atom, local])
    assert excinfo.value.exit_code == exit_codes.BEHAVIOR_PROJECT_LOCAL_REFUSE == 22
    msg = str(excinfo.value)
    assert "rule" in msg
    assert "com.example.mol/rule" in msg


def test_project_local_matches_any_atom_bare_id_regardless_of_molecule() -> None:
    """FR-020: comparison is bare fragment_id, not scoped."""
    atom_a = _frag(id_="shared", molecule_id="com.example.mol-a")
    atom_b = _frag(id_="shared", molecule_id="com.example.mol-b")
    local = _frag(id_="shared", molecule_id=PROJECT_SCOPE, atom_source="_project")
    with pytest.raises(ProjectLocalOverrideError) as excinfo:
        precheck([atom_a, atom_b, local])
    msg = str(excinfo.value)
    assert "com.example.mol-a/shared" in msg
    assert "com.example.mol-b/shared" in msg


def test_project_local_unique_id_survives() -> None:
    atom = _frag(id_="rule", molecule_id="com.example.mol")
    local = _frag(
        id_="project-only-rule", molecule_id=PROJECT_SCOPE, atom_source="_project"
    )
    result = precheck([atom, local])
    assert len(result.fragments) == 2
    assert any(f.molecule_id == PROJECT_SCOPE for f in result.fragments)


def test_result_fragments_sorted_by_scoped_id_for_reproducibility() -> None:
    frags = [
        _frag(id_="z", molecule_id="com.example.mol-b"),
        _frag(id_="a", molecule_id="com.example.mol-a"),
        _frag(id_="m", molecule_id="com.example.mol-a"),
    ]
    result = precheck(frags)
    assert [f.scoped_id for f in result.fragments] == [
        "com.example.mol-a/a",
        "com.example.mol-a/m",
        "com.example.mol-b/z",
    ]


def test_non_fragment_input_raises_malformed_fragment_error() -> None:
    with pytest.raises(MalformedFragmentError):
        precheck([{"id": "not-a-fragment"}])  # type: ignore[list-item]
