"""T020 - v3 -> v4 transform on the consumer manifest shape (Spec 014)."""

from __future__ import annotations

import pytest

from haex_hive.migrate.v3_to_v4 import (
    UnsupportedMinVersionConstraintError,
    rewrite_min_version,
    v3_to_v4,
)


def test_haex_hive_version_renamed_to_spaex_version() -> None:
    v3 = {
        "haex_hive_version": "3",
        "identity": "com.example.project",
        "compounds": [
            {
                "source": "https://example.com/publisher",
                "revision": "a" * 40,
                "molecules": ["com.example.publisher.hello"],
            }
        ],
    }
    v4 = v3_to_v4(v3)
    assert v4["spaex_version"] == "4"
    assert "haex_hive_version" not in v4
    assert v4["identity"] == "com.example.project"
    assert v4["compounds"] == v3["compounds"]


def test_min_version_field_renamed_and_bumped() -> None:
    v3 = {
        "haex_hive_version": "3",
        "identity": "com.example.project",
        "haex_hive_min_version": "3.2.0",
        "compounds": [],
    }
    v4 = v3_to_v4(v3)
    assert "haex_hive_min_version" not in v4
    assert v4["spaex_min_version"] == "4.2.0"


def test_optional_fields_preserved() -> None:
    v3 = {
        "haex_hive_version": "3",
        "identity": "com.example.project",
        "haex_hive_min_version": "3.5.1",
        "groups": ["team-a"],
        "active_feature": "feat-x",
        "identity_note": "hi",
        "compounds": [
            {
                "source": "https://example.com/publisher",
                "revision": "a" * 40,
                "molecules": ["com.example.publisher.hello"],
                "track": "main",
                "config": {"com.example.publisher.hello": {"priority": 50}},
            }
        ],
    }
    v4 = v3_to_v4(v3)
    assert v4["spaex_min_version"] == "4.5.1"
    assert v4["groups"] == ["team-a"]
    assert v4["active_feature"] == "feat-x"
    assert v4["identity_note"] == "hi"
    assert v4["compounds"][0]["track"] == "main"
    assert v4["compounds"][0]["config"] == {
        "com.example.publisher.hello": {"priority": 50}
    }


@pytest.mark.parametrize(
    "v3_value,v4_value",
    [
        ("3.0.0", "4.0.0"),
        ("3.5.1", "4.5.1"),
        ("3.99.99", "4.99.99"),
        (">=3.0.0", ">=4.0.0"),
        (">=3.5.1", ">=4.0.0"),
    ],
)
def test_min_version_rewrite_supported(v3_value: str, v4_value: str) -> None:
    assert rewrite_min_version(v3_value) == v4_value


@pytest.mark.parametrize(
    "value",
    ["2.0.0", "4.0.0", ">=2.0.0", ">=4.0.0", "~2.0.0", "invalid", "3.0", ""],
)
def test_min_version_rewrite_refuses_unsupported(value: str) -> None:
    with pytest.raises(UnsupportedMinVersionConstraintError):
        rewrite_min_version(value)


def test_v4_input_is_returned_unchanged_for_idempotency() -> None:
    v4 = {
        "spaex_version": "4",
        "identity": "com.example.project",
        "compounds": [],
    }
    assert v3_to_v4(v4) is v4
