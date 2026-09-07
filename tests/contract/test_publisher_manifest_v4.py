"""T042 - publisher-manifest.v4 contract test (Spec 014)."""

from __future__ import annotations

import pytest

from spaex.schema import validator as schema_validator

_SCHEMA = "publisher-manifest.v4.schema.json"


def _valid() -> dict:
    """Return a valid v4 publisher manifest."""
    return {
        "spaex_version": "4",
        "publisher": "com.example.publisher",
        "molecules": {
            "com.example.publisher.alpha": {
                "path": "alpha",
                "version": "1.0.0",
            }
        },
    }


def test_valid_molecules_map_passes() -> None:
    """Accept a publisher manifest with a valid molecules map."""
    schema_validator.validate(_valid(), _SCHEMA)


def test_missing_spaex_version_is_rejected() -> None:
    """Reject a publisher manifest without a spaex version."""
    data = _valid()
    del data["spaex_version"]
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_legacy_haex_hive_version_key_is_rejected() -> None:
    """Reject the legacy haex_hive_version key."""
    data = _valid()
    data["haex_hive_version"] = "3"
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)
