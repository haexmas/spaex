"""Passages of fragment bodies (Spec 030, research R3).

A passage is a run of lines of one fragment body, named by the fragment's
scoped id and a 1-based inclusive line range. Findings of the check and
decisions of the operator refer to passages. Lines are those of the body with
CRLF and CR canonicalized to LF and nothing else changed (trailing whitespace
stays), the same lines `render` writes into the composed constitution.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from spaex.behavior.fragment import BehaviorFragment

_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


class PassageError(ValueError):
    """Raised when a named passage cannot exist in the fragment set."""


def canonical_body(body: str) -> str:
    """The body as the composed constitution carries it.

    CRLF and CR become LF; a body without a final newline gets one so a
    fragment block always ends on a line boundary. Trailing whitespace and the
    number of trailing newlines are otherwise kept.
    """
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def canonical_lines(body: str) -> list[str]:
    """Lines of `canonical_body` without their line terminators."""
    return canonical_body(body).split("\n")[:-1]


def text_hash(text: str) -> str:
    """Lowercase-hex SHA256 of a passage text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Passage:
    """Lines `start`..`end` (1-based, inclusive) of one fragment body."""

    scoped_id: str
    start: int
    end: int
    text: str

    @property
    def text_hash(self) -> str:
        return text_hash(self.text)


def validate_range(fragment: BehaviorFragment, start: int, end: int) -> Passage:
    """Return the passage `start`..`end` of `fragment`, or raise `PassageError`.

    Rejected: a range outside the body, a blank range, and a range that cuts a
    fenced code block (it starts inside one, or holds an odd number of fence
    lines), because a comment placed there would break the Markdown.
    """
    lines = canonical_lines(fragment.body)
    if start < 1 or end < start or end > len(lines):
        raise PassageError(
            f"{fragment.scoped_id}: lines {start}-{end} lie outside the body "
            f"(1-{len(lines)})"
        )
    chosen = lines[start - 1 : end]
    if all(not line.strip() for line in chosen):
        raise PassageError(f"{fragment.scoped_id}: lines {start}-{end} are blank")
    fence: tuple[str, int] | None = None
    for line in lines[: start - 1]:
        match = _FENCE_RE.match(line)
        if match is None:
            continue
        marker, suffix = match.groups()
        if fence is None:
            if marker[0] == "`" and "`" in suffix:
                continue
            fence = (marker[0], len(marker))
        elif marker[0] == fence[0] and len(marker) >= fence[1] and not suffix.strip():
            fence = None
    if fence is not None:
        raise PassageError(
            f"{fragment.scoped_id}: lines {start}-{end} start inside a fenced code block"
        )
    for line in chosen:
        match = _FENCE_RE.match(line)
        if match is None:
            continue
        marker, suffix = match.groups()
        if fence is None:
            if marker[0] == "`" and "`" in suffix:
                continue
            fence = (marker[0], len(marker))
        elif marker[0] == fence[0] and len(marker) >= fence[1] and not suffix.strip():
            fence = None
    if fence is not None:
        raise PassageError(
            f"{fragment.scoped_id}: lines {start}-{end} cut a fenced code block"
        )
    return Passage(
        scoped_id=fragment.scoped_id, start=start, end=end, text="\n".join(chosen)
    )


def locate(fragment: BehaviorFragment, text: str) -> tuple[int, int] | None:
    """Line range where `text` occurs exactly once, line-aligned, else `None`."""
    lines = canonical_lines(fragment.body)
    needle = text.split("\n")
    size = len(needle)
    hits = [
        index
        for index in range(len(lines) - size + 1)
        if lines[index : index + size] == needle
    ]
    if len(hits) != 1:
        return None
    return hits[0] + 1, hits[0] + size


def finding_key(passages: Iterable[Passage | tuple[str, str]]) -> str:
    """Key of a finding: sha256 over its sorted `(scoped_id, text_hash)` pairs."""
    pairs = sorted(
        (p.scoped_id, p.text_hash) if isinstance(p, Passage) else p for p in passages
    )
    payload = "\n".join(f"{scoped_id}|{digest}" for scoped_id, digest in pairs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fragment_index(
    fragments: Sequence[BehaviorFragment],
) -> Mapping[str, BehaviorFragment]:
    return {fragment.scoped_id: fragment for fragment in fragments}


__all__ = [
    "Passage",
    "PassageError",
    "canonical_body",
    "canonical_lines",
    "finding_key",
    "fragment_index",
    "locate",
    "text_hash",
    "validate_range",
]
