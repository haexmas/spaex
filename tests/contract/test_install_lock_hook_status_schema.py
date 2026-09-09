"""T005 - install-lock.v4 hook_status schema contract (Spec 016)."""

from __future__ import annotations

import pytest

from spaex.schema import validator as schema_validator

_SCHEMA = "install-lock.v4.schema.json"
_SHA40 = "0" * 40
_URL = "https://github.com/example/publisher"


def _valid_lock() -> dict:
    """Return a valid v4 install lock (single molecule, no hook_status)."""
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


def _with_hook_status(status: object) -> dict:
    """Return a valid lock whose molecule carries the supplied hook status."""
    data = _valid_lock()
    data["molecules"][0]["hook_status"] = status
    return data


@pytest.mark.parametrize("status", ["ok", "failed", "skipped"])
def test_hook_status_enum_values_are_accepted(status: str) -> None:
    """FR-020: hook_status accepts ok, failed, skipped."""
    schema_validator.validate(_with_hook_status(status), _SCHEMA)


def test_hook_status_absent_is_accepted() -> None:
    """FR-020: hook_status is optional; absence is valid."""
    schema_validator.validate(_valid_lock(), _SCHEMA)


def test_pre_spec_016_lock_still_valid() -> None:
    """SC-006 backwards-compat: existing lock shapes without hook_status remain valid."""
    schema_validator.validate(_valid_lock(), _SCHEMA)


@pytest.mark.parametrize("bad", ["unknown", "OK", "", "success"])
def test_hook_status_unknown_string_is_rejected(bad: str) -> None:
    """FR-020: unknown enum values are rejected."""
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_hook_status(bad), _SCHEMA)


@pytest.mark.parametrize("bad", [None, True, 42, [], {}])
def test_hook_status_non_string_types_are_rejected(bad: object) -> None:
    """FR-020: hook_status must be an enum string."""
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_hook_status(bad), _SCHEMA)


def test_unknown_property_still_rejected_on_molecule_entry() -> None:
    """FR-020 preserves moleculeEntry.additionalProperties: false."""
    data = _valid_lock()
    data["molecules"][0]["nonsense"] = "x"
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)
