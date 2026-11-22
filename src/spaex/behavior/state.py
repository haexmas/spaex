"""What the composed constitution should be, and whether the file on disk is (Spec 030).

Shared by `orchestrate.run` (which writes it), `spaex constitution build --check`
and the status report (which only look). Everything here is free of model calls:
the expected text is a pure function of the fragments and the valid decisions.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from spaex.behavior.composer.prompt import effective_prompt_sha256, load_effective_check_prompt
from spaex.behavior.decisions import (
    DECISIONS_FILENAME,
    Checked,
    Decision,
    DecisionStore,
    build_input_hash,
    valid_decisions,
)
from spaex.behavior.decisions import load as load_decisions
from spaex.behavior.emit import compute_source_hash
from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.passages import canonical_body
from spaex.behavior.render import render

Diagnosis = Literal["current", "missing", "version", "out-of-date", "unchecked"]


def fragments_fingerprint(fragments: Sequence[BehaviorFragment]) -> str:
    """Hash of the exact text and declared modality of every fragment.

    The check state records this, not the whitespace-normalized `source_hash`,
    so an edit that only changes whitespace inside a passage still triggers a
    new check and cannot silently void a decision.
    """
    lines = [
        f"{fragment.scoped_id}|{fragment.modality.value if fragment.modality else ''}|"
        f"{hashlib.sha256(canonical_body(fragment.body).encode()).hexdigest()}"
        for fragment in sorted(fragments, key=lambda f: f.scoped_id)
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Assessment:
    """The fragments, the persisted decisions and what follows from them."""

    fragments: tuple[BehaviorFragment, ...]
    source_hash: str
    fingerprint: str
    prompt_hash: str
    prompt_text: str
    store: DecisionStore
    valid: tuple[Decision, ...]

    @property
    def check_needed(self) -> bool:
        """True unless a completed check covers exactly these fragments and prompt."""
        return self.store.checked != Checked(self.fingerprint, self.prompt_hash)


def assess(
    fragments: Sequence[BehaviorFragment], *, repo_root: Path, spaex_dir: Path
) -> Assessment:
    """Load the decisions next to `spaex_dir` and relate them to `fragments`."""
    store = load_decisions(spaex_dir / DECISIONS_FILENAME)
    prompt_text = load_effective_check_prompt(repo_root)
    return Assessment(
        fragments=tuple(fragments),
        source_hash=compute_source_hash(fragments),
        fingerprint=fragments_fingerprint(fragments),
        prompt_hash=effective_prompt_sha256(prompt_text),
        prompt_text=prompt_text,
        store=store,
        valid=valid_decisions(store, fragments),
    )


def expected_text(
    fragments: Sequence[BehaviorFragment],
    decisions: Sequence[Decision],
    *,
    preamble: str = "",
) -> str:
    """The composed constitution for these fragments and valid decisions."""
    return render(
        fragments,
        decisions,
        source_hash=compute_source_hash(fragments),
        build_input_hash=build_input_hash(decisions),
        preamble=preamble,
    )


def diagnose(
    assessment: Assessment, existing: str | None, *, preamble: str = ""
) -> Diagnosis:
    """Compare the file on disk (`existing`, `None` if absent) with the expectation."""
    if existing is None:
        return "missing"
    if existing.split("\n", 1)[0].endswith('version="1" -->'):
        return "version"
    if existing != expected_text(assessment.fragments, assessment.valid, preamble=preamble):
        return "out-of-date"
    if assessment.check_needed:
        return "unchecked"
    return "current"


__all__ = [
    "Assessment",
    "Diagnosis",
    "assess",
    "diagnose",
    "expected_text",
    "fragments_fingerprint",
]
