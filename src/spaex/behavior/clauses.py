"""Composed-clause parser for `.spaex/constitution.md` (contracts/spaex-md-format.md).

Extracted from `spaex/cli/behavior_commands.py` (Spec 028 research.md R5),
where it originally served only `constitution trace`, so `spaex status`'s
constitution summary can reuse the same parser instead of a second,
independently-drifting implementation of the same clause grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MODALITY_ORDER: tuple[str, ...] = (
    "MUST",
    "MUST_NOT",
    "SHOULD",
    "SHOULD_NOT",
    "MAY",
    "MAY_NOT",
)
_SECTION_HEADER_RE = re.compile(r"^## (?P<modality>[A-Z_]+)\s*$")
_CLAUSE_RE = re.compile(
    r"^- (?P<text>.+?)\. _\[from (?P<provenance>`[^`]+`(?:, `[^`]+`)*)\]_$"
)
_PROVENANCE_ID_RE = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class TracedClause:
    """One `.spaex/constitution.md` clause parsed for provenance/summary purposes."""

    modality: str
    text: str
    provenance: tuple[str, ...]


def parse_clauses(body: str) -> list[TracedClause]:
    """Parse every clause in a composed `.spaex/constitution.md` body.

    Follows contracts/spaex-md-format.md's stable clause regex under each
    `##` modality section header; lines outside a recognized section (the
    title and italic notice lines) are ignored.
    """
    clauses: list[TracedClause] = []
    current_modality: str | None = None
    for line in body.splitlines():
        section_match = _SECTION_HEADER_RE.match(line)
        if section_match and section_match.group("modality") in _MODALITY_ORDER:
            current_modality = section_match.group("modality")
            continue
        if current_modality is None:
            continue
        clause_match = _CLAUSE_RE.match(line)
        if clause_match is None:
            continue
        provenance = tuple(
            _PROVENANCE_ID_RE.findall(clause_match.group("provenance"))
        )
        clauses.append(
            TracedClause(
                modality=current_modality,
                text=clause_match.group("text"),
                provenance=provenance,
            )
        )
    return clauses
