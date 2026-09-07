"""JSON Schema Draft 2020-12 validation with FR-034/SC-006 diagnostics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from spaex.schema import loader

_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _is_uri(value: object) -> bool:
    """Check the URI format omitted by jsonschema's default checker set."""
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return False
    if not _URI_SCHEME_RE.match(value):
        return False
    try:
        urlsplit(value)
    except ValueError:
        return False
    return True


Draft202012Validator.FORMAT_CHECKER.checks("uri")(_is_uri)

_SCHEMA_BY_KIND = {
    "consumer": "consumer-manifest.v4.schema.json",
    "publisher": "publisher-manifest.v4.schema.json",
    "molecule": "molecule-manifest.v4.schema.json",
    "install-lock": "install-lock.v4.schema.json",
}


def schema_name_for_kind(kind: str) -> str:
    """Return the v3 schema payload name for a manifest kind.

    `kind` is one of "consumer", "publisher", "molecule", "install-lock".
    """
    try:
        return _SCHEMA_BY_KIND[kind]
    except KeyError:
        raise KeyError(f"unknown manifest kind: {kind!r}") from None


@dataclass(frozen=True)
class SchemaError:
    field_path: str
    message: str


class SchemaValidationError(ValueError):
    def __init__(self, schema_name: str, errors: list[SchemaError]) -> None:
        """Create a validation error with the first field diagnostic in its message."""
        self.schema_name = schema_name
        self.errors = errors
        first = errors[0] if errors else None
        formatted = (
            f"{schema_name}: {first.field_path} {first.message}"
            if first
            else f"{schema_name}: unknown error"
        )
        super().__init__(formatted)


def _json_pointer(path: list[Any]) -> str:
    """Render a jsonschema path as an escaped JSON Pointer."""
    if not path:
        return "/"
    return "/" + "/".join(
        str(token).replace("~", "~0").replace("/", "~1") for token in path
    )


def validate(data: Any, schema_name: str) -> None:
    """Validate JSON structurally and apply schema-specific semantic checks."""
    schema = loader.load(schema_name)
    validator = Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    formatted = [
        SchemaError(
            field_path=_json_pointer(list(e.absolute_path)),
            message=e.message,
        )
        for e in errors
    ]
    if not formatted:
        formatted = _semantic_errors(data, schema_name)
    if not formatted:
        return
    raise SchemaValidationError(schema_name, formatted)


def _semantic_errors(data: Any, schema_name: str) -> list[SchemaError]:
    """Return semantic errors that Draft 2020-12 cannot express."""
    if not isinstance(data, dict):
        return []

    errors: list[SchemaError] = []
    if schema_name == "install-lock.v4.schema.json":
        _check_molecules_canonical_order(data, errors)
    return errors


def _check_molecules_canonical_order(data: dict[str, Any], errors: list[SchemaError]) -> None:
    """Ensure molecules[] is sorted by the canonical (id, source, revision, paths) tuple.

    JSON Schema cannot compare properties across array items (data-model.md
    §InstallLock); `uniqueItems` on the array only rejects exact duplicate
    entries, not out-of-order ones.
    """
    molecules = data.get("molecules")
    if not isinstance(molecules, list) or not all(
        isinstance(molecule, dict) for molecule in molecules
    ):
        return

    keys = [
        (
            molecule.get("id", ""),
            molecule.get("source", ""),
            molecule.get("revision", ""),
            tuple(molecule.get("paths", ())),
        )
        for molecule in molecules
    ]
    if keys != sorted(keys):
        errors.append(
            SchemaError(
                field_path="/molecules",
                message="molecules must be sorted by (id, source, revision, paths)",
            )
        )
