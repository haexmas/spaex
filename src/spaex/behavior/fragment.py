"""Behavior Fragment schema (Spec 023).

Parses the two-part fragment file format defined in
`specs/023-behavior-harness/contracts/fragment-format.md`: a YAML header
enclosed in `---` fences followed by a Markdown body.

The public surface is `BehaviorFragment.from_file()` and
`BehaviorFragment.from_bytes()` for standalone fragments,
`BehaviorFragment.from_inline()` for `constitution_fragments[]` entries
declared inline in a typed atom's manifest, and `body_sha256()` for the
normalized-body hash used by clarification-key derivation (research.md §7).
"""

from __future__ import annotations

import enum
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_HEADER_FENCE = "---"
_RESERVED_COMMENT_RE = re.compile(r"<!--\s*spaex-")
_REQUIRED_FIELDS: tuple[str, ...] = ("id", "kind", "atom_source")
_OPTIONAL_FIELDS: tuple[str, ...] = ("modality", "tags")
_ALLOWED_FIELDS: frozenset[str] = frozenset(_REQUIRED_FIELDS + _OPTIONAL_FIELDS)
_KIND_LITERAL = "constitution_fragment"

PROJECT_SCOPE = "_project"


class Modality(str, enum.Enum):
    MUST = "MUST"
    MUST_NOT = "MUST_NOT"
    SHOULD = "SHOULD"
    SHOULD_NOT = "SHOULD_NOT"
    MAY = "MAY"
    MAY_NOT = "MAY_NOT"


class FragmentValidationError(ValueError):
    """Base for every fragment validation error surfaced by the pre-check."""

    kind: str = "fragment-validation-error"

    def __init__(self, message: str, *, path: str | None = None) -> None:
        self.path = path
        prefix = f"{path}: " if path else ""
        super().__init__(f"{prefix}{message}")


class MissingHeaderError(FragmentValidationError):
    kind = "missing-header"


class MalformedHeaderError(FragmentValidationError):
    kind = "malformed-header"


class MissingFieldError(FragmentValidationError):
    kind = "missing-field"


class InvalidIdError(FragmentValidationError):
    kind = "invalid-id"


class InvalidKindError(FragmentValidationError):
    kind = "invalid-kind"


class InvalidModalityError(FragmentValidationError):
    kind = "invalid-modality"


class EmptyBodyError(FragmentValidationError):
    kind = "empty-body"


class ReservedCommentError(FragmentValidationError):
    kind = "reserved-comment"


class UnknownFieldError(FragmentValidationError):
    kind = "malformed-header"


@dataclass(frozen=True)
class BehaviorFragment:
    """One materialized constitution fragment."""

    id: str
    kind: str
    atom_source: str
    modality: Modality | None
    tags: tuple[str, ...]
    body: str
    molecule_id: str

    @property
    def scoped_id(self) -> str:
        """The `<molecule-id>/<fragment-id>` form used in provenance and hashing."""
        return f"{self.molecule_id}/{self.id}"

    @property
    def body_hash(self) -> str:
        """Lowercase hex SHA256 of the normalized body (research.md §7)."""
        return body_sha256(self.body)

    @staticmethod
    def from_file(path: Path, *, molecule_id: str) -> BehaviorFragment:
        """Read and parse a fragment file at `path`.

        `molecule_id` is inferred by the caller from the on-disk layout
        (`.spaex/constitution.d/<molecule-id>/<id>.md`), never from the header.
        Pass the sentinel `PROJECT_SCOPE` for project-local fragments.
        """
        raw = path.read_bytes()
        return BehaviorFragment.from_bytes(
            raw, molecule_id=molecule_id, path=str(path)
        )

    @staticmethod
    def from_bytes(
        raw: bytes, *, molecule_id: str, path: str | None = None
    ) -> BehaviorFragment:
        """Parse raw fragment bytes into a validated `BehaviorFragment`."""
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedHeaderError(
                "fragment must be valid UTF-8", path=path
            ) from exc
        header, body = _split_header_and_body(text, path=path)
        return _build(header, body, molecule_id=molecule_id, path=path)

    @staticmethod
    def from_inline(
        entry: Mapping[str, Any],
        *,
        molecule_id: str,
        enclosing_atom_id: str,
        path: str | None = None,
    ) -> BehaviorFragment:
        """Build a fragment from a `constitution_fragments[]` entry.

        `enclosing_atom_id` becomes the fragment's `atom_source` when the
        inline entry omits it, matching contracts/fragment-format.md
        §"Inline behavior blocks in typed atoms".
        """
        if not isinstance(entry, Mapping):
            raise MalformedHeaderError(
                "inline fragment entry must be a JSON object", path=path
            )
        header = dict(entry)
        body = header.pop("body", None)
        if not isinstance(body, str):
            raise MissingFieldError(
                "missing required field 'body' in inline fragment", path=path
            )
        # Standalone fragment files are parsed with their terminal LF intact.
        # Keep the inline representation equivalent before it reaches the
        # Composer, whose input includes the raw body as well as its hash.
        if not body.endswith("\n"):
            body += "\n"
        header.setdefault("kind", _KIND_LITERAL)
        header.setdefault("atom_source", enclosing_atom_id)
        return _build(header, body, molecule_id=molecule_id, path=path)


def body_sha256(body: str) -> str:
    """Return the lowercase-hex SHA256 of the normalized body.

    Normalization per research.md §7:

    1. Convert CRLF to LF.
    2. Strip trailing whitespace from each line.
    3. Collapse any trailing run of blank lines to exactly one trailing LF.
    """
    normalized = _normalize_body(body)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_body(body: str) -> str:
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while len(lines) > 1 and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _split_header_and_body(text: str, *, path: str | None) -> tuple[str, str]:
    stripped = text.lstrip("﻿")
    lines = stripped.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != _HEADER_FENCE:
        raise MissingHeaderError("missing YAML header", path=path)
    header_lines: list[str] = []
    body_start: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].rstrip("\r\n") == _HEADER_FENCE:
            body_start = idx + 1
            break
        header_lines.append(lines[idx])
    if body_start is None:
        raise MissingHeaderError("missing YAML header", path=path)
    header_text = "".join(header_lines)
    body_text = "".join(lines[body_start:])
    return header_text, body_text


def _build(
    header_source: Mapping[str, Any] | str,
    body: str,
    *,
    molecule_id: str,
    path: str | None,
) -> BehaviorFragment:
    if isinstance(header_source, str):
        try:
            header_obj = yaml.safe_load(header_source) if header_source.strip() else {}
        except yaml.YAMLError as exc:
            raise MalformedHeaderError(
                f"header YAML parse error: {exc}", path=path
            ) from exc
        if header_obj is None:
            header_obj = {}
        if not isinstance(header_obj, dict):
            raise MalformedHeaderError(
                "header must be a mapping", path=path
            )
        header: dict[str, Any] = header_obj
    else:
        header = dict(header_source)

    unknown = set(header) - _ALLOWED_FIELDS
    if unknown:
        raise UnknownFieldError(
            f"unknown header field(s): {sorted(unknown)!r}", path=path
        )

    for required in _REQUIRED_FIELDS:
        if required not in header:
            raise MissingFieldError(
                f"missing required field '{required}'", path=path
            )

    id_value = header["id"]
    if not isinstance(id_value, str) or not _ID_RE.match(id_value):
        raise InvalidIdError(
            f"id {id_value!r} does not match [a-z0-9][a-z0-9-]*", path=path
        )

    kind_value = header["kind"]
    if kind_value != _KIND_LITERAL:
        raise InvalidKindError(
            f"kind must be {_KIND_LITERAL!r}, got {kind_value!r}", path=path
        )

    atom_source = header["atom_source"]
    if not isinstance(atom_source, str) or not atom_source:
        raise MissingFieldError(
            "atom_source must be a non-empty string", path=path
        )

    modality_raw = header.get("modality")
    modality: Modality | None
    if modality_raw is None:
        modality = None
    else:
        try:
            modality = Modality(modality_raw)
        except ValueError as exc:
            allowed = "|".join(m.value for m in Modality)
            raise InvalidModalityError(
                f"modality {modality_raw!r} not in {allowed}",
                path=path,
            ) from exc

    tags_raw = header.get("tags", [])
    if not isinstance(tags_raw, (list, tuple)) or not all(
        isinstance(tag, str) for tag in tags_raw
    ):
        raise MalformedHeaderError(
            "tags must be a list of strings", path=path
        )
    tags = tuple(tags_raw)

    if not body.strip():
        raise EmptyBodyError("body must not be empty", path=path)

    if _RESERVED_COMMENT_RE.search(body):
        raise ReservedCommentError(
            "body contains reserved 'spaex-' HTML comment", path=path
        )

    return BehaviorFragment(
        id=id_value,
        kind=kind_value,
        atom_source=atom_source,
        modality=modality,
        tags=tags,
        body=body,
        molecule_id=molecule_id,
    )
