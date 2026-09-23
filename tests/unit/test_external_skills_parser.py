"""Parser tests for Spec 018 structured external skill references."""

from __future__ import annotations

import json

from spaex.model.molecule_manifest import ExternalSkillReference, MoleculeManifest

_REV_A = "a" * 40
_REV_B = "b" * 40


def _base() -> dict:
    return {
        "spaex_version": "4",
        "id": "com.example.publisher.skills",
        "version": "1.0.0",
        "priority": 100,
        "atoms": {"constitution": ["constitution.md"]},
    }


def test_external_skills_preserve_order_and_are_immutable() -> None:
    data = _base()
    data["external_skills"] = [
        {"repository": "https://github.com/example/first", "revision": _REV_A, "path": "skills/a"},
        {"repository": "https://github.com/example/second", "revision": _REV_B, "path": "skills/b"},
    ]

    parsed = MoleculeManifest.from_json(json.dumps(data).encode())

    assert parsed.external_skills == (
        ExternalSkillReference(
            repository="https://github.com/example/first", revision=_REV_A, path="skills/a"
        ),
        ExternalSkillReference(
            repository="https://github.com/example/second", revision=_REV_B, path="skills/b"
        ),
    )
    assert isinstance(parsed.external_skills, tuple)


def test_missing_external_skills_parses_to_empty_tuple() -> None:
    parsed = MoleculeManifest.from_json(json.dumps(_base()).encode())
    assert parsed.external_skills == ()


def test_external_skills_do_not_require_install_hook() -> None:
    data = _base()
    data["external_skills"] = [
        {"repository": "https://github.com/example/first", "revision": _REV_A, "path": "skills/a"}
    ]

    parsed = MoleculeManifest.from_json(json.dumps(data).encode())

    assert parsed.install_hook is None
    assert len(parsed.external_skills) == 1


def test_reference_only_molecule_with_empty_atoms_parses() -> None:
    data = _base()
    data["atoms"] = {}
    data["external_skills"] = [
        {"repository": "https://github.com/example/first", "revision": _REV_A, "path": "skills/a"}
    ]

    parsed = MoleculeManifest.from_json(json.dumps(data).encode())

    assert parsed.atoms == {}
    assert len(parsed.external_skills) == 1
