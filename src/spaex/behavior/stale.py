"""Add-time plausibility check sidecar (Spec 023 FR-024a).

`spaex add`/`spaex remove` run the Composer's plausibility check whenever the
active fragment set changes. When the Composer flags a cross-molecule
semantic contradiction (Shape B), the add/remove operation completes without
aborting: it prints a WARN and writes this `.spaex/.stale` sidecar so the
next `spaex install` can detect the finding and route it through the
reconciliation prompt (FR-010a) before `.spaex.md` is rewritten.

The file is gitignored (Spec 023 T006): it is per-checkout state, not a
tracked artifact.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spaex.behavior.composer.invoke import ClarificationQuestion

STALE_FILENAME = ".stale"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StaleQuestion:
    """One Composer Shape B question recorded in the sidecar."""

    kind: str
    question: str
    cited_fragments: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class StaleMarker:
    """Parsed `.spaex/.stale` content."""

    detected_at: str
    questions: tuple[StaleQuestion, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "detected_at": self.detected_at,
            "questions": [
                {
                    "kind": q.kind,
                    "question": q.question,
                    "cited_fragments": list(q.cited_fragments),
                }
                for q in self.questions
            ],
        }


def write_stale(
    path: Path,
    questions: Sequence[ClarificationQuestion],
    *,
    detected_at: str,
) -> None:
    """Atomically write the sidecar summarizing an unresolved contradiction."""
    marker = StaleMarker(
        detected_at=detected_at,
        questions=tuple(
            StaleQuestion(
                kind=q.kind,
                question=q.question,
                cited_fragments=q.cited_fragments,
            )
            for q in questions
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"{path.name}.tmp"
    tmp.write_text(
        json.dumps(marker.as_json(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def read_stale(path: Path) -> StaleMarker | None:
    """Read the sidecar; `None` when absent or unreadable (best-effort)."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    questions_raw = data.get("questions", ())
    if not isinstance(questions_raw, list):
        questions_raw = ()
    questions = tuple(
        StaleQuestion(
            kind=str(q.get("kind", "")),
            question=str(q.get("question", "")),
            cited_fragments=tuple(q.get("cited_fragments", ()) or ()),
        )
        for q in questions_raw
        if isinstance(q, dict)
    )
    return StaleMarker(detected_at=str(data.get("detected_at", "")), questions=questions)


def clear_stale(path: Path) -> None:
    """Remove the sidecar once the composition it describes is resolved."""
    if path.exists():
        path.unlink()


__all__ = [
    "SCHEMA_VERSION",
    "STALE_FILENAME",
    "StaleMarker",
    "StaleQuestion",
    "clear_stale",
    "read_stale",
    "write_stale",
]
