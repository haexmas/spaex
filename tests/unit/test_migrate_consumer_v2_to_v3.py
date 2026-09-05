"""T040 — v2 → v3 transform on the consumer manifest shape (Spec 013)."""

from __future__ import annotations

import pytest

from haex_hive.migrate.v2_to_v3 import (
    UnsupportedMinVersionConstraintError,
    rewrite_min_version,
    v2_to_v3,
)


def test_atoms_renamed_to_compounds_and_includes_to_molecules() -> None:
    v2 = {
        "haex_hive_version": "2",
        "identity": "com.example.project",
        "atoms": [
            {
                "source": "https://example.com/publisher",
                "revision": "a" * 40,
                "includes": ["com.example.publisher.hello"],
            }
        ],
    }
    v3 = v2_to_v3(v2)
    assert v3["haex_hive_version"] == "3"
    assert "atoms" not in v3
    assert v3["compounds"] == [
        {
            "source": "https://example.com/publisher",
            "revision": "a" * 40,
            "molecules": ["com.example.publisher.hello"],
        }
    ]


def test_optional_fields_preserved() -> None:
    v2 = {
        "haex_hive_version": "2",
        "identity": "com.example.project",
        "haex_hive_min_version": "2.5.1",
        "groups": ["team-a"],
        "active_feature": "feat-x",
        "identity_note": "hi",
        "atoms": [
            {
                "source": "https://example.com/publisher",
                "revision": "a" * 40,
                "includes": ["com.example.publisher.hello"],
                "track": "main",
                "config": {"com.example.publisher.hello": {"priority": 50}},
            }
        ],
    }
    v3 = v2_to_v3(v2)
    assert v3["haex_hive_min_version"] == "3.5.1"
    assert v3["groups"] == ["team-a"]
    assert v3["active_feature"] == "feat-x"
    assert v3["identity_note"] == "hi"
    assert v3["compounds"][0]["track"] == "main"
    assert v3["compounds"][0]["config"] == {
        "com.example.publisher.hello": {"priority": 50}
    }


@pytest.mark.parametrize(
    "v2_value,v3_value",
    [
        ("2.0.0", "3.0.0"),
        ("2.5.1", "3.5.1"),
        ("2.99.99", "3.99.99"),
        (">=2.0.0", ">=3.0.0"),
        (">=2.5.1", ">=3.0.0"),
    ],
)
def test_min_version_rewrite_supported(v2_value: str, v3_value: str) -> None:
    assert rewrite_min_version(v2_value) == v3_value


@pytest.mark.parametrize(
    "value",
    ["1.0.0", "3.0.0", ">=1.0.0", ">=4.0.0", "invalid", "2.0", ""],
)
def test_min_version_rewrite_refuses_unsupported(value: str) -> None:
    with pytest.raises(UnsupportedMinVersionConstraintError):
        rewrite_min_version(value)


def test_v3_input_is_returned_unchanged_for_idempotency() -> None:
    v3 = {
        "haex_hive_version": "3",
        "identity": "com.example.project",
        "compounds": [],
    }
    assert v2_to_v3(v3) is v3
