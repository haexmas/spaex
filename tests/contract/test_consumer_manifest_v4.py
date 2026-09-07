"""T040 - consumer-manifest.v4 contract test (Spec 014)."""

from __future__ import annotations

import pytest

from spaex.schema import validator as schema_validator

_SCHEMA = "consumer-manifest.v4.schema.json"
_SHA40 = "0" * 40
_URL = "https://github.com/example/publisher"


def _valid() -> dict:
    return {
        "spaex_version": "4",
        "identity": "com.example.consumer",
        "compounds": [
            {
                "source": _URL,
                "revision": _SHA40,
                "molecules": ["com.example.publisher.alpha"],
            }
        ],
    }


def test_valid_v4_shape_passes() -> None:
    schema_validator.validate(_valid(), _SCHEMA)


def test_spaex_version_3_is_rejected() -> None:
    data = _valid()
    data["spaex_version"] = "3"
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_unknown_top_level_property_is_rejected() -> None:
    data = _valid()
    data["nonsense_field"] = True
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_duplicate_molecule_id_within_compound_is_rejected() -> None:
    data = _valid()
    data["compounds"][0]["molecules"] = [
        "com.example.publisher.alpha",
        "com.example.publisher.alpha",
    ]
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)
