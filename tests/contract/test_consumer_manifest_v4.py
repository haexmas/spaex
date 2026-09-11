"""T040 - consumer-manifest.v4 contract test (Spec 014)."""

from __future__ import annotations

import pytest

from spaex.schema import validator as schema_validator

_SCHEMA = "consumer-manifest.v4.schema.json"
_SHA40 = "0" * 40
_URL = "https://github.com/example/publisher"


def _valid() -> dict:
    """Return a valid v4 consumer manifest."""
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
    """Accept a consumer manifest with the valid v4 shape."""
    schema_validator.validate(_valid(), _SCHEMA)


def test_spaex_version_3_is_rejected() -> None:
    """Reject a consumer manifest that declares spaex version 3."""
    data = _valid()
    data["spaex_version"] = "3"
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_unknown_top_level_property_is_rejected() -> None:
    """Reject unknown properties at the consumer manifest root."""
    data = _valid()
    data["nonsense_field"] = True
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_duplicate_molecule_id_within_compound_is_rejected() -> None:
    """Reject duplicate molecule identifiers within one compound."""
    data = _valid()
    data["compounds"][0]["molecules"] = [
        "com.example.publisher.alpha",
        "com.example.publisher.alpha",
    ]
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_inline_local_fragment_is_accepted() -> None:
    """Accept a Spec 023 FR-018 inline `constitution.local_fragments[]` entry."""
    data = _valid()
    data["constitution"] = {
        "local_fragments": [
            {
                "id": "shared-client",
                "modality": "MUST",
                "body": "**MUST** route HTTP through the shared client.",
            }
        ]
    }
    schema_validator.validate(data, _SCHEMA)


def test_inline_local_fragment_accepts_explicit_kind() -> None:
    """Accept the canonical fragment kind when inline kind is explicit."""
    data = _valid()
    data["constitution"] = {
        "local_fragments": [
            {
                "id": "shared-client",
                "kind": "constitution_fragment",
                "body": "**MUST** route HTTP through the shared client.",
            }
        ]
    }
    schema_validator.validate(data, _SCHEMA)


def test_inline_local_fragment_rejects_unknown_kind() -> None:
    """Reject an inline fragment kind other than constitution_fragment."""
    data = _valid()
    data["constitution"] = {
        "local_fragments": [
            {
                "id": "shared-client",
                "kind": "other",
                "body": "**MUST** route HTTP through the shared client.",
            }
        ]
    }
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_file_reference_local_fragment_is_accepted() -> None:
    """Accept a Spec 023 FR-018 file-reference `constitution.local_fragments[]` entry."""
    data = _valid()
    data["constitution"] = {
        "local_fragments": [{"file": ".spaex/local-fragments/shared-client.md"}]
    }
    schema_validator.validate(data, _SCHEMA)


def test_local_fragment_with_both_file_and_body_is_rejected() -> None:
    """An entry mixing the inline and file-reference shapes matches neither."""
    data = _valid()
    data["constitution"] = {
        "local_fragments": [
            {"file": ".spaex/local-fragments/x.md", "body": "**MUST** x."}
        ]
    }
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_local_fragment_with_neither_file_nor_body_is_rejected() -> None:
    """An entry missing both `file` and `body` matches neither shape."""
    data = _valid()
    data["constitution"] = {"local_fragments": [{"id": "shared-client"}]}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)
