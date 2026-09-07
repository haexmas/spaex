"""Repo-relative POSIX path validation (data-model.md §RepoRelativePath).

Reject: absolute paths, backslashes, drive prefixes, control characters,
empty segments, `.`, and `..`.
"""

from __future__ import annotations

import re

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class RepoRelativePath:
    __slots__ = ()

    @staticmethod
    def validate(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"path must be a string, got {type(value).__name__}")
        if value == "":
            raise ValueError("path is empty")
        if value.startswith("/"):
            raise ValueError(f"path is absolute: {value!r}")
        if "\\" in value:
            raise ValueError(f"path contains backslash: {value!r}")
        if _DRIVE_RE.match(value):
            raise ValueError(f"path is drive-qualified: {value!r}")
        for ch in value:
            if ord(ch) < 0x20 or ch == "\x7f":
                raise ValueError(f"path contains control character: {value!r}")
        segments = value.split("/")
        for segment in segments:
            if segment == "":
                raise ValueError(f"path has empty segment: {value!r}")
            if segment in (".", ".."):
                raise ValueError(f"path has `{segment}` segment: {value!r}")
        return value
