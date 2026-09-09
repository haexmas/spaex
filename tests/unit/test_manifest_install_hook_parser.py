"""T008 - MoleculeManifest.install_hook parser rules (Spec 016).

The parser MUST explicitly set defaults rather than relying on the JSON
Schema's `default` metadata. To prove that, one test stubs out the
schema validator so nothing from schema-space can populate the value.
"""

from __future__ import annotations

import json

import pytest

from spaex.model.molecule_manifest import InstallHook, MoleculeManifest
from spaex.schema import validator as schema_validator


def _base_manifest() -> dict:
    """Return a valid molecule manifest without an install hook."""
    return {
        "spaex_version": "4",
        "id": "com.example.publisher.alpha",
        "version": "1.0.0",
        "priority": 100,
        "atoms": {
            "constitution": [".spaex/constitution.md"],
        },
    }


def _encode(data: dict) -> bytes:
    """Encode a manifest mapping as UTF-8 JSON bytes."""
    return json.dumps(data).encode("utf-8")


def test_absent_field_parses_to_none() -> None:
    """Parse a missing install_hook field as None."""
    manifest = MoleculeManifest.from_json(_encode(_base_manifest()))
    assert manifest.install_hook is None


def test_present_min_form_produces_dataclass() -> None:
    """Parse the minimal install-hook form with explicit default values."""
    data = _base_manifest()
    data["install_hook"] = {"interpreter": "python3", "script": "install.py"}
    manifest = MoleculeManifest.from_json(_encode(data))
    assert manifest.install_hook == InstallHook(
        interpreter="python3",
        script="install.py",
        args=(),
        on_failure="abort",
    )


def test_all_fields_populated() -> None:
    """Preserve every explicitly populated install-hook field."""
    data = _base_manifest()
    data["install_hook"] = {
        "interpreter": "bash",
        "script": "setup.sh",
        "args": ["--verbose", "--flag=1"],
        "on_failure": "warn",
    }
    manifest = MoleculeManifest.from_json(_encode(data))
    assert manifest.install_hook == InstallHook(
        interpreter="bash",
        script="setup.sh",
        args=("--verbose", "--flag=1"),
        on_failure="warn",
    )


def test_args_are_immutable_tuple() -> None:
    """Freeze the parsed hook argument list as a tuple."""
    data = _base_manifest()
    data["install_hook"] = {
        "interpreter": "python3",
        "script": "install.py",
        "args": ["one", "two"],
    }
    manifest = MoleculeManifest.from_json(_encode(data))
    assert manifest.install_hook is not None
    assert isinstance(manifest.install_hook.args, tuple)
    assert manifest.install_hook.args == ("one", "two")


def test_on_failure_default_is_set_by_parser_not_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove the parser assigns on_failure='abort' independently of the schema.

    Stub `schema_validator.validate` to a no-op so nothing from schema-space
    can populate the default; the parsed dataclass still holds "abort".
    """
    monkeypatch.setattr(schema_validator, "validate", lambda data, name: None)
    data = _base_manifest()
    data["install_hook"] = {"interpreter": "python3", "script": "install.py"}
    manifest = MoleculeManifest.from_json(_encode(data))
    assert manifest.install_hook is not None
    assert manifest.install_hook.on_failure == "abort"


def test_manifest_is_frozen() -> None:
    """InstallHook and MoleculeManifest are both frozen dataclasses."""
    data = _base_manifest()
    data["install_hook"] = {"interpreter": "python3", "script": "install.py"}
    manifest = MoleculeManifest.from_json(_encode(data))
    with pytest.raises(Exception):
        manifest.install_hook.interpreter = "other"  # type: ignore[misc]
    with pytest.raises(Exception):
        manifest.install_hook = None  # type: ignore[misc]
