"""Semantic checks on install.lock's molecules[] (2026-09-03 amendment)."""

from __future__ import annotations

import json

import pytest

from spaex.model.install_lock import InstallLock
from spaex.util.errors import CredentialInUrlError, InstallLockSchemaInvalidError

_BASE = {
    "spaex_version": "4",
    "generation_id": "g_20260831T142011Z_a4c2",
    "molecules": [],
}


def _payload(molecules: list[dict]) -> bytes:
    """Build an install lock payload containing the supplied molecules."""
    data = json.loads(json.dumps(_BASE))
    data["molecules"] = molecules
    return json.dumps(data).encode("utf-8")


def _molecule(molecule_id: str, *, paths: list[str] | None = None) -> dict:
    return {
        "id": molecule_id,
        "revision": "0" * 40,
        "source": "https://github.com/a/b",
        "paths": paths if paths is not None else [".spaex/constitution.md"],
    }


def test_rejects_wrong_sort_order() -> None:
    """Reject molecules outside canonical (id, source, revision, paths) order."""
    molecules = [_molecule("com.b.b"), _molecule("com.a.b")]
    with pytest.raises(InstallLockSchemaInvalidError):
        InstallLock.from_json(_payload(molecules))


def test_accepts_canonical_sort_order() -> None:
    molecules = [_molecule("com.a.b"), _molecule("com.b.b")]
    lock = InstallLock.from_json(_payload(molecules))
    assert [m.id for m in lock.molecules] == ["com.a.b", "com.b.b"]


def test_rejects_credentials_in_molecule_source() -> None:
    """Reject source URL userinfo before it can be stored or serialized."""
    molecules = [
        {
            "id": "com.a.b",
            "revision": "0" * 40,
            "source": "https://user:pass@example.com/publisher",
            "paths": [".spaex/constitution.md"],
        }
    ]
    with pytest.raises(CredentialInUrlError):
        InstallLock.from_json(_payload(molecules))


def test_preserves_unknown_top_level_fields() -> None:
    """Forward-compatible lock fields survive parsing and serialization."""
    data = json.loads(json.dumps(_BASE))
    data["future_field"] = {"nested": [1, "value"]}

    lock = InstallLock.from_json(json.dumps(data).encode())
    serialized = json.loads(lock.to_json_bytes())

    assert lock.unknown_top_level["future_field"]["nested"] == (1, "value")
    assert serialized["future_field"] == data["future_field"]


def test_rejects_path_without_leading_dot_segment() -> None:
    """A path must start with a dot-segment root; there is no separate root list."""
    molecules = [_molecule("com.example.molecule", paths=["README.md"])]
    with pytest.raises(InstallLockSchemaInvalidError):
        InstallLock.from_json(_payload(molecules))


def test_allows_empty_paths() -> None:
    molecules = [_molecule("com.example.molecule", paths=[])]
    lock = InstallLock.from_json(_payload(molecules))
    assert lock.molecules[0].paths == ()


@pytest.mark.parametrize(
    "retired_field, value",
    [
        ("generated_by", "haex 3.0.0"),
        ("constitution", {"sources": [], "assembled_by": {}}),
        ("atoms", []),
        ("participating_roots", [".spaex/"]),
        ("generation_inputs", []),
        ("visibility_marker", {"generation_id": "g_20260831T142011Z_a4c2"}),
    ],
)
def test_from_json_rejects_retired_top_level_fields(
    retired_field: str, value: object
) -> None:
    """Retired v2-era / pre-amendment fields must refuse at the runtime read gate.

    Without this the parser would stash them in `unknown_top_level` and
    `to_json_bytes` would republish them, defeating the FR-005 schema gate.
    """
    data = json.loads(json.dumps(_BASE))
    data[retired_field] = value
    with pytest.raises(InstallLockSchemaInvalidError) as exc_info:
        InstallLock.from_json(json.dumps(data).encode())
    assert retired_field in exc_info.value.context.get("retired_fields", "")


def test_from_json_preserves_unrelated_future_field_across_round_trip() -> None:
    """A field the schema does not yet describe still round-trips.

    Retired-field rejection must not regress forward-compat: any unknown field
    that is not on the retired list continues to survive read/write cycles.
    """
    data = json.loads(json.dumps(_BASE))
    data["future_v4_field"] = {"nested": ["value"]}

    lock = InstallLock.from_json(json.dumps(data).encode())
    round_tripped = json.loads(lock.to_json_bytes())

    assert round_tripped["future_v4_field"] == data["future_v4_field"]
