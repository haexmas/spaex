"""T042 — v2 → v3 transform on the publisher-root manifest shape (Spec 013)."""

from __future__ import annotations

from haex_hive.migrate.v2_to_v3 import v2_to_v3


def test_atoms_map_renamed_to_molecules_map() -> None:
    v2 = {
        "haex_hive_version": "2",
        "publisher": "com.example.publisher",
        "atoms": {
            "com.example.publisher.hello": {"path": "hello", "version": "1.0.0"},
            "com.example.publisher.world": {
                "path": "world",
                "version": "2.3.4",
                "description": "greets the world",
            },
        },
    }
    v3 = v2_to_v3(v2)
    assert v3["haex_hive_version"] == "3"
    assert "atoms" not in v3
    assert v3["publisher"] == "com.example.publisher"
    assert v3["molecules"] == {
        "com.example.publisher.hello": {"path": "hello", "version": "1.0.0"},
        "com.example.publisher.world": {
            "path": "world",
            "version": "2.3.4",
            "description": "greets the world",
        },
    }


def test_v3_publisher_returned_unchanged() -> None:
    v3 = {
        "haex_hive_version": "3",
        "publisher": "com.example.publisher",
        "molecules": {},
    }
    assert v2_to_v3(v3) is v3
