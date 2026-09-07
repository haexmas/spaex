"""T021 - v3 -> v4 transform on the publisher-root manifest shape (Spec 014)."""

from __future__ import annotations

from haex_hive.migrate.v3_to_v4 import v3_to_v4


def test_publisher_root_version_field_renamed() -> None:
    v3 = {
        "haex_hive_version": "3",
        "publisher": "com.example.publisher",
        "molecules": {
            "com.example.publisher.hello": {
                "path": "hello",
                "version": "1.0.0",
            }
        },
    }
    v4 = v3_to_v4(v3)
    assert v4["spaex_version"] == "4"
    assert "haex_hive_version" not in v4
    assert v4["publisher"] == "com.example.publisher"


def test_molecules_map_preserved_byte_for_byte() -> None:
    v3 = {
        "haex_hive_version": "3",
        "publisher": "com.example.publisher",
        "molecules": {
            "com.example.publisher.hello": {
                "path": "hello",
                "version": "1.2.3",
                "description": "A friendly greeting.",
            },
            "com.example.publisher.other": {
                "path": "other/dir",
                "version": "0.0.1",
            },
        },
    }
    v4 = v3_to_v4(v3)
    assert v4["molecules"] == v3["molecules"]


def test_v4_publisher_input_is_returned_unchanged() -> None:
    v4 = {
        "spaex_version": "4",
        "publisher": "com.example.publisher",
        "molecules": {
            "com.example.publisher.hello": {"path": "hello", "version": "1.0.0"}
        },
    }
    assert v3_to_v4(v4) is v4
