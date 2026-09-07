"""T023 - v3 -> v4 chain-level behavior (idempotency, determinism, dispatch).

Spec 014.
"""

from __future__ import annotations

import pytest

from haex_hive.migrate.v2_to_v3 import v2_to_v3
from haex_hive.migrate.v3_to_v4 import (
    UnrecognizedManifestShapeError,
    is_v4,
    v3_to_v4,
    v3_to_v4_bytes,
)


def test_is_v4_true_on_v4_input() -> None:
    assert is_v4({"spaex_version": "4"}) is True


def test_is_v4_false_on_v3_input() -> None:
    assert is_v4({"haex_hive_version": "3"}) is False


def test_idempotent_on_v4_consumer() -> None:
    v4 = {"spaex_version": "4", "identity": "com.x.y", "compounds": []}
    assert v3_to_v4(v4) is v4


def test_dispatch_refuses_unrecognized_shape() -> None:
    with pytest.raises(UnrecognizedManifestShapeError):
        v3_to_v4({"haex_hive_version": "3", "unknown_shape": True})


def test_v2_then_v3_chain_reaches_v4() -> None:
    v2 = {
        "haex_hive_version": "2",
        "identity": "com.example.project",
        "haex_hive_min_version": "2.5.0",
        "atoms": [
            {
                "source": "https://example.com/pub",
                "revision": "a" * 40,
                "includes": ["com.example.pub.hello"],
            }
        ],
    }
    v3 = v2_to_v3(v2)
    v4 = v3_to_v4(v3)
    assert v4["spaex_version"] == "4"
    assert v4["spaex_min_version"] == "4.5.0"
    assert v4["compounds"][0]["molecules"] == ["com.example.pub.hello"]


def test_deterministic_bytes() -> None:
    v3 = {
        "haex_hive_version": "3",
        "identity": "com.example.project",
        "compounds": [
            {
                "source": "https://example.com/pub",
                "revision": "b" * 40,
                "molecules": ["com.example.pub.hello"],
            }
        ],
    }
    import json as _json

    raw = _json.dumps(v3).encode("utf-8")
    first = v3_to_v4_bytes(raw)
    second = v3_to_v4_bytes(raw)
    assert first == second


def test_install_lock_shape_handled_by_transform() -> None:
    """Contract says migrate CLI skips install.lock, but the transform is
    defensive and handles the shape too."""
    v3 = {
        "haex_hive_version": "3",
        "generation_id": "g_20260907T120000Z_abcd",
        "molecules": [
            {
                "id": "com.example.pub.hello",
                "source": "https://example.com/pub",
                "revision": "c" * 40,
                "paths": [".spaex/constitution.md"],
            }
        ],
    }
    v4 = v3_to_v4(v3)
    assert v4["spaex_version"] == "4"
    assert "haex_hive_version" not in v4
    assert v4["generation_id"] == v3["generation_id"]
    assert v4["molecules"] == v3["molecules"]
