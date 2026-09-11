"""Fragment schema validation (Spec 023 T010).

Covers every validation error class listed in
`specs/023-behavior-harness/contracts/fragment-format.md` §Validation errors,
excluding the two duplicate-id cases (those are handled by the mechanical
pre-check, not fragment parsing).
"""

from __future__ import annotations

import pytest

from spaex.behavior.fragment import (
    BehaviorFragment,
    EmptyBodyError,
    InvalidIdError,
    InvalidKindError,
    InvalidModalityError,
    MalformedHeaderError,
    MissingFieldError,
    MissingHeaderError,
    Modality,
    ReservedCommentError,
    UnknownFieldError,
)

MOL = "com.example.mol"


def _bytes(header: str, body: str = "**MUST** do a thing.\n") -> bytes:
    return f"---\n{header}\n---\n{body}".encode()


def test_minimal_valid_fragment_parses() -> None:
    raw = _bytes("id: rule\nkind: constitution_fragment\natom_source: pkg.a")
    frag = BehaviorFragment.from_bytes(raw, molecule_id=MOL, path="x.md")
    assert frag.id == "rule"
    assert frag.molecule_id == MOL
    assert frag.scoped_id == f"{MOL}/rule"
    assert frag.modality is None
    assert frag.tags == ()


def test_all_fields_including_modality_and_tags_round_trip() -> None:
    raw = _bytes(
        "id: rule-a\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.a\n"
        "modality: SHOULD_NOT\n"
        "tags: [alpha, beta]"
    )
    frag = BehaviorFragment.from_bytes(raw, molecule_id=MOL)
    assert frag.modality is Modality.SHOULD_NOT
    assert frag.tags == ("alpha", "beta")


def test_missing_opening_fence_raises_missing_header() -> None:
    raw = b"id: x\nkind: constitution_fragment\natom_source: a\n---\nbody\n"
    with pytest.raises(MissingHeaderError):
        BehaviorFragment.from_bytes(raw, molecule_id=MOL)


def test_missing_closing_fence_raises_missing_header() -> None:
    raw = b"---\nid: x\nkind: constitution_fragment\natom_source: a\nbody without fence\n"
    with pytest.raises(MissingHeaderError):
        BehaviorFragment.from_bytes(raw, molecule_id=MOL)


def test_malformed_yaml_header_raises_malformed_header() -> None:
    raw = b"---\nid: [unterminated\n---\nbody\n"
    with pytest.raises(MalformedHeaderError):
        BehaviorFragment.from_bytes(raw, molecule_id=MOL)


def test_non_mapping_header_raises_malformed_header() -> None:
    raw = b"---\n- just_a_list_item\n---\nbody\n"
    with pytest.raises(MalformedHeaderError):
        BehaviorFragment.from_bytes(raw, molecule_id=MOL)


@pytest.mark.parametrize("missing", ["id", "kind", "atom_source"])
def test_missing_required_field(missing: str) -> None:
    fields = {
        "id": "rule",
        "kind": "constitution_fragment",
        "atom_source": "pkg.a",
    }
    del fields[missing]
    header = "\n".join(f"{k}: {v}" for k, v in fields.items())
    with pytest.raises(MissingFieldError):
        BehaviorFragment.from_bytes(_bytes(header), molecule_id=MOL)


@pytest.mark.parametrize(
    "bad_id",
    ["Rule", "-leading", "with_underscore", "has space", "", "UPPER"],
)
def test_invalid_id_rejected(bad_id: str) -> None:
    header = f"id: {bad_id!r}\nkind: constitution_fragment\natom_source: pkg.a"
    with pytest.raises(InvalidIdError):
        BehaviorFragment.from_bytes(_bytes(header), molecule_id=MOL)


def test_invalid_kind_rejected() -> None:
    header = "id: rule\nkind: something_else\natom_source: pkg.a"
    with pytest.raises(InvalidKindError):
        BehaviorFragment.from_bytes(_bytes(header), molecule_id=MOL)


def test_invalid_modality_rejected() -> None:
    header = (
        "id: rule\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.a\n"
        "modality: MAYBE"
    )
    with pytest.raises(InvalidModalityError):
        BehaviorFragment.from_bytes(_bytes(header), molecule_id=MOL)


def test_empty_body_rejected() -> None:
    header = "id: rule\nkind: constitution_fragment\natom_source: pkg.a"
    raw = _bytes(header, body="   \n\t\n")
    with pytest.raises(EmptyBodyError):
        BehaviorFragment.from_bytes(raw, molecule_id=MOL)


def test_reserved_spaex_comment_in_body_rejected() -> None:
    header = "id: rule\nkind: constitution_fragment\natom_source: pkg.a"
    body = "**MUST** honor.\n<!-- spaex-composed:evil -->\n"
    with pytest.raises(ReservedCommentError):
        BehaviorFragment.from_bytes(_bytes(header, body=body), molecule_id=MOL)


def test_unknown_header_field_rejected() -> None:
    header = (
        "id: rule\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.a\n"
        "extra_field: nope"
    )
    with pytest.raises(UnknownFieldError):
        BehaviorFragment.from_bytes(_bytes(header), molecule_id=MOL)


def test_tags_must_be_list_of_strings() -> None:
    header = (
        "id: rule\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.a\n"
        "tags: [1, 2, 3]"
    )
    with pytest.raises(MalformedHeaderError):
        BehaviorFragment.from_bytes(_bytes(header), molecule_id=MOL)


def test_from_inline_uses_enclosing_atom_id_when_atom_source_absent() -> None:
    frag = BehaviorFragment.from_inline(
        {
            "id": "spec-first",
            "modality": "MUST",
            "body": "**MUST** run /speckit-specify first.",
        },
        molecule_id=MOL,
        enclosing_atom_id="speckit-strict",
        path="manifest.json:constitution_fragments[0]",
    )
    assert frag.atom_source == "speckit-strict"
    assert frag.modality is Modality.MUST


def test_from_inline_missing_body_raises_missing_field() -> None:
    with pytest.raises(MissingFieldError):
        BehaviorFragment.from_inline(
            {"id": "spec-first", "modality": "MUST"},
            molecule_id=MOL,
            enclosing_atom_id="speckit-strict",
        )


def test_scoped_id_uses_molecule_from_caller_not_header() -> None:
    header = "id: rule\nkind: constitution_fragment\natom_source: pkg.a"
    frag = BehaviorFragment.from_bytes(_bytes(header), molecule_id="different.mol")
    assert frag.scoped_id == "different.mol/rule"
