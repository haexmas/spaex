"""T043 - install-lock.v4 contract test (Spec 014)."""

from __future__ import annotations

import pytest

from spaex.schema import validator as schema_validator

_SCHEMA = "install-lock.v4.schema.json"
_SHA40 = "0" * 40
_URL = "https://github.com/example/publisher"


def _valid() -> dict:
    return {
        "spaex_version": "4",
        "generation_id": "g_20260907T120000Z_abcd",
        "molecules": [
            {
                "id": "com.example.publisher.alpha",
                "source": _URL,
                "revision": _SHA40,
                "paths": [".spaex/constitution.md"],
            }
        ],
    }


def test_valid_molecules_array_passes() -> None:
    schema_validator.validate(_valid(), _SCHEMA)


def test_unknown_root_property_is_rejected() -> None:
    data = _valid()
    data["nonsense_root"] = 1
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


@pytest.mark.parametrize(
    "retired_field, retired_value",
    [
        ("generated_by", "spaex 4.0.0"),
        ("constitution", {"sources": []}),
        ("participating_roots", [".spaex"]),
        ("generation_inputs", []),
    ],
)
def test_retired_top_level_field_is_rejected(
    retired_field: str, retired_value: object
) -> None:
    data = _valid()
    data[retired_field] = retired_value
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)
