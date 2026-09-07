"""Version constraint grammar (FR-006, R10).

Exactly two shapes: `X.Y.Z` (exact) and `>=X.Y.Z` (lower bound). Leading zeros
in any component are rejected explicitly by the regex character class.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_VERSION_RE = re.compile(r"^(?:(>=)?)(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

Operator = Literal["==", ">="]


@dataclass(frozen=True)
class VersionConstraint:
    operator: Operator
    version: tuple[int, int, int]

    @staticmethod
    def parse(s: str) -> VersionConstraint:
        if not isinstance(s, str):
            raise ValueError(f"version constraint must be a string, got {type(s).__name__}")
        match = _VERSION_RE.match(s)
        if not match:
            raise ValueError(
                f"version constraint {s!r} does not match `X.Y.Z` or `>=X.Y.Z`"
            )
        prefix, major, minor, patch = match.groups()
        operator: Operator = ">=" if prefix == ">=" else "=="
        return VersionConstraint(
            operator=operator,
            version=(int(major), int(minor), int(patch)),
        )

    def satisfied_by(self, installed: tuple[int, int, int]) -> bool:
        if self.operator == "==":
            return installed == self.version
        return installed >= self.version
