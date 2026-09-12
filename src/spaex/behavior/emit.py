"""Emit the composed constitution to `<repo-root>/.spaex/constitution.md`.

Two responsibilities:

- Compute the canonical `source_hash` and `build_input_hash` outside the LLM
  per contracts/composer-interface.md §"Build fingerprints" and
  research.md §5.
- Verify the Composer's Shape A response echoes those hashes in the
  `<!-- spaex-composed:... -->` header, then write the body atomically to
  `.spaex/constitution.md`. A mismatch is an `invalid-output` failure (FR-012a).

Empty-set behavior (FR-017d): install.py decides whether the composed
Constitution should
be removed for an empty fragment set; `emit.py` exposes `remove_if_exists`
for that path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from spaex.behavior.composer.clarifications import Clarification
from spaex.behavior.composer.failure import (
    ComposerFailureCategory,
    raise_for,
)
from spaex.behavior.composer.invoke import ComposedShape
from spaex.behavior.fragment import BehaviorFragment
from spaex.paths import composed_constitution_path

SPAEX_MD_FILENAME = ".spaex/constitution.md"

_HEADER_RE = re.compile(
    r'^<!--\s*spaex-composed:'
    r'source_hash="(?P<source_hash>[0-9a-f]{64})"\s+'
    r'build_input_hash="(?P<build_input_hash>[0-9a-f]{64})"\s+'
    r'version="(?P<version>\d+)"\s*-->\s*$',
    re.MULTILINE,
)


@dataclass(frozen=True)
class EmitOutcome:
    """Return type of `emit_composed`: path + verified hashes."""

    path: Path
    source_hash: str
    build_input_hash: str


class _SourceRecord(TypedDict):
    molecule_id: str
    fragment_id: str
    atom_source: str
    modality: str | None
    tags: list[str]
    body_sha256: str


def compute_source_hash(fragments: Sequence[BehaviorFragment]) -> str:
    """Canonical `source_hash` per contracts/composer-interface.md §Build fingerprints.

    One compact-JSON record per fragment, sorted by
    `(molecule_id, fragment_id, atom_source, modality, tags, body_sha256)`,
    joined by LF, hashed as UTF-8.
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


def compute_build_input_hash(
    *,
    effective_prompt_sha256: str,
    composer_prompt_version: str,
    valid_clarifications: Iterable[Clarification],
) -> str:
    """Canonical `build_input_hash` per contracts §Build fingerprints.

    LF-joined records:

    - `composer_prompt_version=<version>`
    - `effective_prompt_sha256=<hex>`
    - one `<key>|<normalized-answer>` per valid clarification (sorted by key).

    Normalization: CRLF -> LF, trailing whitespace stripped per line, one
    trailing LF collapsed. Matches fragment body normalization so hand-edits
    of answers only change the hash when their semantic content changes.
    """
    ordered = sorted(valid_clarifications, key=lambda c: c.key)
    lines = [
        f"composer_prompt_version={composer_prompt_version}",
        f"effective_prompt_sha256={effective_prompt_sha256}",
    ]
    for entry in ordered:
        lines.append(f"{entry.key}|{_normalize_answer(entry.answer)}")
    payload = "\n".join(lines)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def emit_composed(
    shape: ComposedShape,
    *,
    repo_root: Path,
    expected_source_hash: str,
    expected_build_input_hash: str,
) -> EmitOutcome:
    """Verify the Composer's header hashes, then atomically write the artifact.

    Mismatches (missing header, wrong hash, wrong version) raise
    `ComposerInvalidOutputError` (exit 32) so the fail-fast contract holds
    (FR-012a) and no `.spaex/constitution.md` is published from a suspect Composer output.
    """
    header = _parse_header(shape.body)
    if header is None:
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            "Composer body missing the spaex-composed header line",
        )
        raise AssertionError("unreachable")
    if header["source_hash"] != expected_source_hash:
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            (
                "Composer source_hash does not match spaex-computed value "
                f"(composer={header['source_hash']!r}, "
                f"expected={expected_source_hash!r})"
            ),
        )
    if header["build_input_hash"] != expected_build_input_hash:
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            (
                "Composer build_input_hash does not match spaex-computed value "
                f"(composer={header['build_input_hash']!r}, "
                f"expected={expected_build_input_hash!r})"
            ),
        )
    if header["version"] != "1":
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            f"Composer header version {header['version']!r} is not '1'",
        )

    target = composed_constitution_path(repo_root)
    _atomic_write(target, shape.body)
    return EmitOutcome(
        path=target,
        source_hash=header["source_hash"],
        build_input_hash=header["build_input_hash"],
    )


def remove_if_exists(repo_root: Path) -> bool:
    """FR-017d empty-set path: remove the composed Constitution when present.

    Returns True iff a file was removed. Callers use the return value to
    surface a "removed" hint at the end of install.
    """
    target = composed_constitution_path(repo_root)
    if not target.exists():
        return False
    target.unlink()
    return True


def read_header_hashes(repo_root: Path) -> tuple[str, str] | None:
    """Return hashes from the existing composed Constitution artifact.

    Used by the reproducibility skip-path (FR-009, Phase 8): if the on-disk
    hashes match the freshly computed ones for the current fragment set and
    effective prompt, the Composer is not invoked.
    """
    target = composed_constitution_path(repo_root)
    if not target.exists():
        return None
    header = _parse_header(target.read_text(encoding="utf-8"))
    if header is None:
        return None
    return header["source_hash"], header["build_input_hash"]


def _source_record(fragment: BehaviorFragment) -> _SourceRecord:
    return {
        "molecule_id": fragment.molecule_id,
        "fragment_id": fragment.id,
        "atom_source": fragment.atom_source,
        "modality": fragment.modality.value if fragment.modality else None,
        "tags": list(fragment.tags),
        "body_sha256": fragment.body_hash,
    }


def _parse_header(body: str) -> Mapping[str, str] | None:
    match = _HEADER_RE.match(body)
    if match is None:
        return None
    return {
        "source_hash": match.group("source_hash"),
        "build_input_hash": match.group("build_input_hash"),
        "version": match.group("version"),
    }


def _normalize_answer(answer: str) -> str:
    text = answer.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while len(lines) > 1 and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


__all__ = [
    "EmitOutcome",
    "SPAEX_MD_FILENAME",
    "compute_build_input_hash",
    "compute_source_hash",
    "emit_composed",
    "read_header_hashes",
    "remove_if_exists",
]
