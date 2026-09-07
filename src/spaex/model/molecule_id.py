"""Reverse-DNS molecule-ID grammar (D3, R8; renamed from atom-id by Spec 013).

Lowercase-only, at least two dot-joined segments, each segment 1–63 chars,
starts with `[a-z0-9]` and continues with `[a-z0-9-]`, ends alphanumeric.
Total length 1–253 characters. `MoleculeId.parse` returns the input string
unchanged on success and raises `ValueError` otherwise; `parse_identity`
reuses the same grammar for the top-level `identity` field.
"""

from __future__ import annotations

import re

_MAX_LENGTH = 253
_SEGMENT_RE = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_MOLECULE_ID_RE = re.compile(rf"^{_SEGMENT_RE}(?:\.{_SEGMENT_RE})+$")


class MoleculeId:
    __slots__ = ()

    @staticmethod
    def parse(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"molecule-id must be a string, got {type(value).__name__}")
        length = len(value)
        if length == 0:
            raise ValueError("molecule-id is empty")
        if length > _MAX_LENGTH:
            raise ValueError(f"molecule-id is {length} chars; max {_MAX_LENGTH}")
        if not _MOLECULE_ID_RE.match(value):
            raise ValueError(f"molecule-id does not match reverse-DNS grammar: {value!r}")
        return value

    @staticmethod
    def parse_identity(value: str) -> str:
        return MoleculeId.parse(value)
