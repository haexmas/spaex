"""LocalManifest parsing and serialization (Spec 029 T005)."""

from __future__ import annotations

import json

import pytest

from spaex.model.local_manifest import LocalManifest
from spaex.schema.validator import SchemaValidationError

_URL = "https://github.com/example/publisher"


def _raw(**compound: object) -> bytes:
    entry = {"source": _URL, "revision": "a" * 40, "molecules": ["com.example.publisher.alpha"]}
    entry.update(compound)
    return json.dumps({"spaex_version": "4", "compounds": [entry]}).encode()


def test_round_trip_is_byte_stable() -> None:
    manifest = LocalManifest.from_json(_raw())

    assert LocalManifest.from_json(manifest.to_json_bytes()) == manifest
    assert manifest.compounds[0].molecules == ("com.example.publisher.alpha",)


def test_consumer_view_carries_project_identity() -> None:
    view = LocalManifest.from_json(_raw()).as_consumer_manifest("com.example.project")

    assert view.identity == "com.example.project"
    assert view.compounds[0].source == _URL
    assert view.skill_installation is None


def test_non_canonical_source_is_rejected() -> None:
    with pytest.raises((ValueError, SchemaValidationError)):
        LocalManifest.from_json(_raw(source="https://GitHub.com/example/publisher/"))


def test_extra_top_level_key_is_rejected() -> None:
    data = json.loads(_raw())
    data["identity"] = "com.example.project"
    with pytest.raises(SchemaValidationError):
        LocalManifest.from_json(json.dumps(data).encode())
