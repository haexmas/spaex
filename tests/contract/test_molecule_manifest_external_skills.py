"""Contract tests for Spec 018 structured external skill references."""

from __future__ import annotations

import pytest

from spaex.schema import validator as schema_validator

_SCHEMA = "molecule-manifest.v4.schema.json"
_REPO = "https://github.com/example/atoms"
_REV = "0" * 40


def _valid() -> dict:
    return {
        "spaex_version": "4",
        "id": "com.example.publisher.skills",
        "version": "1.0.0",
        "priority": 100,
        "atoms": {"constitution": ["constitution.md"]},
    }


def _reference(
    *, repository: str = _REPO, revision: str = _REV, path: str = "skills/example"
) -> dict:
    return {"repository": repository, "revision": revision, "path": path}


def _with_external_skills(*references: dict) -> dict:
    data = _valid()
    data["external_skills"] = list(references)
    return data


def test_external_skills_are_valid_metadata_without_install_hook() -> None:
    schema_validator.validate(_with_external_skills(_reference()), _SCHEMA)


def test_reference_only_molecule_with_empty_atoms_is_valid() -> None:
    data = _valid()
    data["atoms"] = {}
    data["external_skills"] = [_reference()]
    schema_validator.validate(data, _SCHEMA)


@pytest.mark.parametrize("field", ["repository", "revision", "path"])
def test_reference_missing_required_field_is_rejected(field: str) -> None:
    reference = _reference()
    del reference[field]
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_external_skills(reference), _SCHEMA)


def test_reference_rejects_unknown_property() -> None:
    reference = _reference()
    reference["installer"] = "skillsmd"
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_external_skills(reference), _SCHEMA)


@pytest.mark.parametrize("revision", ["short", "0" * 39, "0" * 41, "G" * 40, "main"])
def test_reference_rejects_non_full_sha_revision(revision: str) -> None:
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(
            _with_external_skills(_reference(revision=revision)), _SCHEMA
        )


@pytest.mark.parametrize("repository", ["", " ", "example\norg/atoms", "example\x00org/atoms"])
def test_reference_rejects_empty_or_control_repository(repository: str) -> None:
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(
            _with_external_skills(_reference(repository=repository)), _SCHEMA
        )


@pytest.mark.parametrize("path", ["", "/abs/path", "../escape", "a/../b", "a\\b"])
def test_reference_rejects_invalid_path(path: str) -> None:
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_external_skills(_reference(path=path)), _SCHEMA)


def test_duplicate_external_skill_references_are_rejected() -> None:
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(
            _with_external_skills(_reference(), _reference()), _SCHEMA
        )


def test_empty_external_skills_array_is_rejected() -> None:
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_external_skills(), _SCHEMA)


@pytest.mark.parametrize("category", ["skill", "skills"])
def test_retired_skill_atom_categories_are_rejected(category: str) -> None:
    data = _valid()
    data["atoms"] = {category: ["SKILL.md"]}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_other_open_atom_categories_remain_valid() -> None:
    data = _valid()
    data["atoms"] = {"instructions": ["instructions.md"]}
    schema_validator.validate(data, _SCHEMA)
