"""T022 - v3 -> v4 transform on the molecule manifest shape (Spec 014)."""

from __future__ import annotations

from haex_hive.migrate.v3_to_v4 import v3_to_v4


def test_molecule_version_field_renamed() -> None:
    v3 = {
        "haex_hive_version": "3",
        "id": "com.example.publisher.hello",
        "version": "1.0.0",
        "priority": 100,
        "atoms": {"constitution": ["constitution.md"]},
    }
    v4 = v3_to_v4(v3)
    assert v4["spaex_version"] == "4"
    assert "haex_hive_version" not in v4
    assert v4["id"] == v3["id"]
    assert v4["version"] == v3["version"]
    assert v4["priority"] == v3["priority"]


def test_atoms_category_map_preserved_byte_for_byte() -> None:
    v3 = {
        "haex_hive_version": "3",
        "id": "com.example.publisher.hello",
        "version": "1.0.0",
        "priority": 50,
        "atoms": {
            "constitution": ["constitution.md"],
            "slash_commands": ["cmd/foo.md", "cmd/bar.md"],
            "agents": ["agent/rev.md"],
        },
    }
    v4 = v3_to_v4(v3)
    assert v4["atoms"] == v3["atoms"]
    assert list(v4["atoms"]) == list(v3["atoms"])  # order preserved


def test_optional_defaults_and_config_schema_preserved() -> None:
    v3 = {
        "haex_hive_version": "3",
        "id": "com.example.publisher.hello",
        "version": "1.0.0",
        "priority": 100,
        "atoms": {"constitution": ["constitution.md"]},
        "defaults": {"greeting": "hello"},
        "config_schema": "schema.json",
    }
    v4 = v3_to_v4(v3)
    assert v4["defaults"] == {"greeting": "hello"}
    assert v4["config_schema"] == "schema.json"


def test_v4_molecule_input_returned_unchanged() -> None:
    v4 = {
        "spaex_version": "4",
        "id": "com.example.publisher.hello",
        "version": "1.0.0",
        "priority": 100,
        "atoms": {"constitution": ["constitution.md"]},
    }
    assert v3_to_v4(v4) is v4
