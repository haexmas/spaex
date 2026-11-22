"""Emit the composed constitution to `<repo-root>/.spaex/constitution.md`.

Spec 030: spaex renders the text itself (`render.py`), so this module only
computes the fragment fingerprint for the header and writes files atomically.
Empty-set behavior (FR-017d): `remove_if_exists` removes the composed
constitution when no fragment is active.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from spaex.behavior.fragment import BehaviorFragment
from spaex.paths import composed_constitution_path

SPAEX_MD_FILENAME = ".spaex/constitution.md"


@dataclass(frozen=True)
class EmitOutcome:
    """Where the composed constitution was written and whether it changed."""

    path: Path
    changed: bool


class _SourceRecord(TypedDict):
    molecule_id: str
    fragment_id: str
    atom_source: str
    modality: str | None
    tags: list[str]
    body_sha256: str


def compute_source_hash(fragments: Sequence[BehaviorFragment]) -> str:
    """Canonical `source_hash`: one compact-JSON record per fragment, sorted, hashed.

    Records carry the scoped id, atom source, modality, tags and the normalized
    body hash; sorted by `(molecule_id, fragment_id, atom_source, modality,
    tags, body_sha256)`, joined by LF, hashed as UTF-8.
    """
    records = [_source_record(f) for f in fragments]
    records.sort(
        key=lambda r: (
            r["molecule_id"],
            r["fragment_id"],
            r["atom_source"],
            "" if r["modality"] is None else r["modality"],
            tuple(r["tags"]),
            r["body_sha256"],
        )
    )
    payload = "\n".join(
        json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        for record in records
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def emit_rendered(text: str, *, target: Path) -> EmitOutcome:
    """Atomically write the rendered constitution; leave an identical file alone."""
    if target.exists() and target.read_text(encoding="utf-8") == text:
        return EmitOutcome(path=target, changed=False)
    _atomic_write(target, text)
    return EmitOutcome(path=target, changed=True)


def remove_if_exists(repo_root: Path, target: Path | None = None) -> bool:
    """FR-017d empty-set path: remove the composed constitution when present.

    Returns True iff a file was removed. Callers use the return value to
    surface a "removed" hint at the end of install.
    """
    target = target if target is not None else composed_constitution_path(repo_root)
    if not target.exists():
        return False
    target.unlink()
    return True


def _source_record(fragment: BehaviorFragment) -> _SourceRecord:
    return {
        "molecule_id": fragment.molecule_id,
        "fragment_id": fragment.id,
        "atom_source": fragment.atom_source,
        "modality": fragment.modality.value if fragment.modality else None,
        "tags": list(fragment.tags),
        "body_sha256": fragment.body_hash,
    }


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


__all__ = [
    "EmitOutcome",
    "SPAEX_MD_FILENAME",
    "compute_source_hash",
    "emit_rendered",
    "remove_if_exists",
]
