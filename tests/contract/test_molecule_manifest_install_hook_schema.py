"""T004 - molecule-manifest.v4 install_hook schema contract (Spec 016)."""

from __future__ import annotations

import pytest

from spaex.schema import validator as schema_validator

_SCHEMA = "molecule-manifest.v4.schema.json"


def _valid() -> dict:
    """Return a valid v4 molecule manifest (no install_hook)."""
    return {
        "spaex_version": "4",
        "id": "com.example.publisher.alpha",
        "version": "1.0.0",
        "priority": 100,
        "atoms": {
            "constitution": [".spaex/constitution.md"],
        },
    }


def _with_hook(**overrides: object) -> dict:
    data = _valid()
    hook: dict = {"interpreter": "python3", "script": "install.py"}
    hook.update(overrides)
    data["install_hook"] = hook
    return data


def test_manifest_without_install_hook_still_valid() -> None:
    """SC-006 backwards-compat: no install_hook is fine."""
    schema_validator.validate(_valid(), _SCHEMA)


def test_install_hook_minimal_form_is_accepted() -> None:
    """FR-001: interpreter + script only is a valid install_hook."""
    schema_validator.validate(_with_hook(), _SCHEMA)


def test_install_hook_full_form_is_accepted() -> None:
    """FR-001: interpreter + script + args + on_failure is valid."""
    data = _with_hook(args=["--verbose", "--flag=1"], on_failure="warn")
    schema_validator.validate(data, _SCHEMA)


def test_install_hook_missing_interpreter_is_rejected() -> None:
    """FR-001: interpreter is required."""
    data = _valid()
    data["install_hook"] = {"script": "install.py"}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_install_hook_missing_script_is_rejected() -> None:
    """FR-001: script is required."""
    data = _valid()
    data["install_hook"] = {"interpreter": "python3"}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_install_hook_empty_interpreter_is_rejected() -> None:
    """FR-001: interpreter minLength 1."""
    data = _with_hook(interpreter="")
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_install_hook_unknown_property_is_rejected() -> None:
    """FR-001: additionalProperties: false on the install_hook object."""
    data = _with_hook(foobar="nope")
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


@pytest.mark.parametrize(
    "bad_value",
    [
        "not-an-object",
        None,
        ["python3", "install.py"],
        7,
        True,
    ],
)
def test_install_hook_non_object_types_are_rejected(bad_value: object) -> None:
    """FR-003: reject non-object install_hook (string, null, array, number, boolean)."""
    data = _valid()
    data["install_hook"] = bad_value
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


@pytest.mark.parametrize("bad_policy", ["ignore", "retry", "", "ABORT"])
def test_install_hook_on_failure_outside_enum_is_rejected(bad_policy: str) -> None:
    """FR-004: on_failure enum is {abort, warn} only."""
    data = _with_hook(on_failure=bad_policy)
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_install_hook_script_traversal_is_rejected() -> None:
    """script uses repoRelativePath: no `..` segments (defense in depth vs FR-014)."""
    data = _with_hook(script="../escape.py")
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)


def test_install_hook_args_non_string_element_is_rejected() -> None:
    """FR-001: args items are strings."""
    data = _with_hook(args=["--ok", 42])
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(data, _SCHEMA)
