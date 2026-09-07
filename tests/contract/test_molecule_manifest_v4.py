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
