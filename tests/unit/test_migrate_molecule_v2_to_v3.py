"""T041 — v2 → v3 transform on the per-molecule manifest shape (Spec 013)."""

from __future__ import annotations

import pytest

from haex_hive.migrate.v2_to_v3 import (
    DirectoryFormContributesUnsupportedError,
    v2_to_v3,
)


def test_scalar_contributes_becomes_atoms_list() -> None:
    v2 = {
        "haex_hive_version": "2",
        "id": "com.example.publisher.hello",
        "version": "1.0.0",
        "contributes": {"constitution": "constitution.md"},
    }
    v3 = v2_to_v3(v2)
    assert v3["haex_hive_version"] == "3"
    assert v3["priority"] == 100
    assert v3["atoms"] == {"constitution": ["constitution.md"]}
    assert "contributes" not in v3


def test_existing_integer_priority_preserved() -> None:
    v2 = {
        "haex_hive_version": "2",
        "id": "com.example.publisher.hello",
        "version": "1.0.0",
        "priority": 42,
        "contributes": {"constitution": "constitution.md"},
    }
    assert v2_to_v3(v2)["priority"] == 42


def test_directory_form_contributes_refused() -> None:
    v2 = {
        "haex_hive_version": "2",
        "id": "com.example.publisher.hello",
        "version": "1.0.0",
        "contributes": {"skills": "skills/", "constitution": "constitution.md"},
    }
    with pytest.raises(DirectoryFormContributesUnsupportedError) as exc_info:
        v2_to_v3(v2)
    assert "skills" in exc_info.value.context["categories"]


def test_defaults_and_config_schema_preserved() -> None:
    v2 = {
        "haex_hive_version": "2",
        "id": "com.example.publisher.hello",
        "version": "1.0.0",
        "contributes": {"constitution": "constitution.md"},
        "defaults": {"greeting": "hi"},
        "config_schema": "config.schema.json",
    }
    v3 = v2_to_v3(v2)
    assert v3["defaults"] == {"greeting": "hi"}
    assert v3["config_schema"] == "config.schema.json"


def test_multi_file_contributes_list_becomes_atoms_list() -> None:
    v2 = {
        "haex_hive_version": "2",
        "id": "com.example.publisher.hello",
        "version": "1.0.0",
        "contributes": {"rules": ["a.md", "b.md"]},
    }
    assert v2_to_v3(v2)["atoms"] == {"rules": ["a.md", "b.md"]}
