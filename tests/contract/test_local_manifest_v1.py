"""local-manifest.v1 contract test (Spec 029)."""

from __future__ import annotations

import pytest

from spaex.schema import validator as schema_validator

_SCHEMA = "local-manifest.v1.schema.json"


def _valid() -> dict:
    return {
        "spaex_version": "4",
        "compounds": [
            {
                "source": "https://github.com/example/publisher",
                "revision": "0" * 40,
                "molecules": ["com.example.publisher.alpha"],
            }
        ],
    }


def test_valid_shape_passes() -> None:
    schema_validator.validate(_valid(), _SCHEMA)


def test_empty_compounds_pass() -> None:
    schema_validator.validate({"spaex_version": "4", "compounds": []}, _SCHEMA)


@pytest.mark.parametrize(
    "key", ["identity", "skill_installation", "constitution", "spaex_min_version"]
)
def test_project_level_keys_are_rejected(key: str) -> None:
    data = _valid()
    data[key] = "x"
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_short_revision_is_rejected() -> None:
    data = _valid()
    data["compounds"][0]["revision"] = "abc123"
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)
