"""T041 - molecule-manifest.v4 contract test (Spec 014).

Cross-category path overlap is a *runtime* check (data-model.md
"Cross-category path overlap is refused"), not a JSON Schema constraint,
so that case goes through `MoleculeManifest.from_json`.
"""

from __future__ import annotations

import json

import pytest

from spaex.model.molecule_manifest import MoleculeManifest
from spaex.schema import validator as schema_validator
from spaex.util.errors import MoleculeAtomsCategoryOverlapError

_SCHEMA = "molecule-manifest.v4.schema.json"


def _valid() -> dict:
    """Return a valid v4 molecule manifest."""
    return {
        "spaex_version": "4",
        "id": "com.example.publisher.alpha",
        "version": "1.0.0",
        "priority": 100,
        "atoms": {
            "constitution": [".spaex/constitution.md"],
        },
    }


def test_valid_v4_shape_passes() -> None:
    """Accept a molecule manifest with the valid v4 shape."""
    schema_validator.validate(_valid(), _SCHEMA)


def test_empty_category_array_is_rejected() -> None:
    """Reject a molecule manifest with an empty atom category."""
    data = _valid()
    data["atoms"]["constitution"] = []
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_cross_category_path_overlap_is_rejected() -> None:
    """Reject a path assigned to more than one atom category."""
    data = _valid()
    data["atoms"] = {
        "constitution": [".spaex/shared.md"],
        "slash_commands": [".spaex/shared.md"],
    }
    with pytest.raises(MoleculeAtomsCategoryOverlapError):
        MoleculeManifest.from_json(json.dumps(data).encode("utf-8"))


def test_missing_priority_is_rejected() -> None:
    """Reject a molecule manifest without a priority."""
    data = _valid()
    del data["priority"]
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


# --- Spec 023 T011c: inline constitution_fragments -----------------------


def _fragment_entry(**overrides: object) -> dict:
    entry = {
        "id": "spec-first",
        "modality": "MUST",
        "body": "**MUST** run /speckit-specify before implementation.",
    }
    entry.update(overrides)
    return entry


def test_manifest_without_constitution_fragments_still_valid() -> None:
    """Absent constitution_fragments block is fine (backwards-compat)."""
    schema_validator.validate(_valid(), _SCHEMA)


def test_manifest_with_valid_inline_constitution_fragments_passes_schema() -> None:
    """Inline fragments keyed by enclosing typed-atom id validate."""
    data = _valid()
    data["constitution_fragments"] = {
        "speckit-strict": [_fragment_entry()],
    }
    schema_validator.validate(data, _SCHEMA)


def test_parser_preserves_inline_constitution_fragments() -> None:
    """MoleculeManifest exposes the parsed inline block keyed by atom-id."""
    data = _valid()
    data["constitution_fragments"] = {
        "speckit-strict": [
            _fragment_entry(),
            _fragment_entry(
                id="plan-before-code",
                modality="SHOULD",
                body="**SHOULD** run /speckit-plan before coding.",
            ),
        ],
        "hooks-runner": [
            _fragment_entry(
                id="tests-before-commit",
                body="**MUST** run tests before committing.",
                tags=["testing", "git"],
            ),
        ],
    }
    parsed = MoleculeManifest.from_json(json.dumps(data).encode("utf-8"))

    assert set(parsed.constitution_fragments) == {"speckit-strict", "hooks-runner"}
    assert len(parsed.constitution_fragments["speckit-strict"]) == 2
    first = parsed.constitution_fragments["speckit-strict"][0]
    assert first["id"] == "spec-first"
    assert first["modality"] == "MUST"
    assert "run /speckit-specify" in first["body"]


def test_inline_fragment_missing_required_body_rejected() -> None:
    data = _valid()
    entry = _fragment_entry()
    del entry["body"]
    data["constitution_fragments"] = {"speckit-strict": [entry]}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_inline_fragment_missing_required_id_rejected() -> None:
    data = _valid()
    entry = _fragment_entry()
    del entry["id"]
    data["constitution_fragments"] = {"speckit-strict": [entry]}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_inline_fragment_invalid_id_rejected() -> None:
    data = _valid()
    data["constitution_fragments"] = {
        "speckit-strict": [_fragment_entry(id="BadID")],
    }
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_inline_fragment_invalid_modality_rejected() -> None:
    data = _valid()
    data["constitution_fragments"] = {
        "speckit-strict": [_fragment_entry(modality="MAYBE")],
    }
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_inline_fragment_unknown_field_rejected() -> None:
    data = _valid()
    data["constitution_fragments"] = {
        "speckit-strict": [_fragment_entry(extra="nope")],
    }
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_inline_fragments_empty_atom_list_rejected() -> None:
    """A typed-atom key with an empty fragment list is rejected."""
    data = _valid()
    data["constitution_fragments"] = {"speckit-strict": []}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_manifest_without_constitution_fragments_field_parses_to_empty_map() -> None:
    """Absent field means empty mapping in the parsed model."""
    parsed = MoleculeManifest.from_json(json.dumps(_valid()).encode("utf-8"))
    assert parsed.constitution_fragments == {}
