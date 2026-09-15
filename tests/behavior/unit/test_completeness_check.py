"""Composer output completeness verification (Spec 023 T073, FR-012b).

`_verify_completeness` closes the gap `emit_composed`'s hash checks cannot
see: both hashes are computed from the *input* fragments and merely echoed
back by the Composer, so a Shape A response can carry correct hashes while
its body silently omits one or more fragments. A fragment's absence is only
legitimate when it is accounted for by a currently-valid persisted
clarification (i.e. it went through the Shape B contradiction/overlap path
and the operator's resolution already explains why it is missing).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.behavior import orchestrate
from spaex.behavior.composer.clarifications import (
    CitedFragment,
    Clarification,
    ClarificationsStore,
)
from spaex.behavior.composer.failure import ComposerInvalidOutputError
from spaex.behavior.fragment import BehaviorFragment


def _fragment(molecule: str, fid: str, body: str = "**MUST** run tests.\n") -> BehaviorFragment:
    raw = (
        f"---\nid: {fid}\nkind: constitution_fragment\n"
        f"atom_source: pkg.a\nmodality: MUST\n---\n{body}"
    ).encode()
    return BehaviorFragment.from_bytes(raw, molecule_id=molecule, path=f"{molecule}/{fid}.md")


def _cited(mol: str, fid: str) -> CitedFragment:
    return CitedFragment(molecule_id=mol, fragment_id=fid, body_sha256="0" * 64)


def _clarification(*cited: CitedFragment, key: str = "aa" * 32) -> Clarification:
    return Clarification(
        key=key,
        question="Q?",
        cited_fragments=cited,
        answer="resolved",
        asked_at="2026-09-15T00:00:00Z",
        answered_at="2026-09-15T00:00:00Z",
    )


def test_uncited_fragment_with_no_clarification_aborts(tmp_path: Path) -> None:
    fragments = [_fragment("alpha", "rule-a"), _fragment("beta", "rule-b")]
    body = "## MUST\n\n- Run tests. _[from `alpha/rule-a`]_\n"

    with pytest.raises(ComposerInvalidOutputError, match="beta/rule-b"):
        orchestrate._verify_completeness(
            canonical_fragments=fragments,
            composed_body=body,
            clarifications=ClarificationsStore(),
            repo_root=tmp_path,
            invoke_options=None,
        )


def test_fragment_covered_by_valid_clarification_is_not_flagged(tmp_path: Path) -> None:
    fragments = [_fragment("alpha", "rule-a"), _fragment("beta", "rule-b")]
    body = "## MUST\n\n- Run tests. _[from `alpha/rule-a`]_\n"
    store = ClarificationsStore().with_entry(
        _clarification(_cited("alpha", "rule-a"), _cited("beta", "rule-b"))
    )

    orchestrate._verify_completeness(
        canonical_fragments=fragments,
        composed_body=body,
        clarifications=store,
        repo_root=tmp_path,
        invoke_options=None,
    )


def test_every_fragment_cited_passes_with_no_clarifications(tmp_path: Path) -> None:
    fragments = [_fragment("alpha", "rule-a"), _fragment("beta", "rule-b")]
    body = (
        "## MUST\n\n"
        "- Run tests. _[from `alpha/rule-a`]_\n"
        "- Ship signed. _[from `beta/rule-b`]_\n"
    )

    orchestrate._verify_completeness(
        canonical_fragments=fragments,
        composed_body=body,
        clarifications=ClarificationsStore(),
        repo_root=tmp_path,
        invoke_options=None,
    )


def test_merged_clause_citation_covers_both_contributing_fragments(tmp_path: Path) -> None:
    fragments = [_fragment("alpha", "rule-a"), _fragment("beta", "rule-b")]
    body = "## MUST\n\n- Ship signed. _[from `alpha/rule-a`, `beta/rule-b`]_\n"

    orchestrate._verify_completeness(
        canonical_fragments=fragments,
        composed_body=body,
        clarifications=ClarificationsStore(),
        repo_root=tmp_path,
        invoke_options=None,
    )


def test_inline_code_in_clause_text_is_not_mistaken_for_a_citation(tmp_path: Path) -> None:
    fragments = [_fragment("alpha", "rule-a")]
    body = (
        "## MUST\n\n"
        "- Use `pyproject.toml` for metadata. _[from `alpha/rule-a`]_\n"
    )

    orchestrate._verify_completeness(
        canonical_fragments=fragments,
        composed_body=body,
        clarifications=ClarificationsStore(),
        repo_root=tmp_path,
        invoke_options=None,
    )


def test_citation_like_text_outside_a_clause_does_not_count(tmp_path: Path) -> None:
    fragments = [_fragment("alpha", "rule-a")]
    body = "The omitted rule is documented here. _[from `alpha/rule-a`]_\n"

    with pytest.raises(ComposerInvalidOutputError, match="alpha/rule-a"):
        orchestrate._verify_completeness(
            canonical_fragments=fragments,
            composed_body=body,
            clarifications=ClarificationsStore(),
            repo_root=tmp_path,
            invoke_options=None,
        )


def test_reports_every_missing_fragment_sorted(tmp_path: Path) -> None:
    fragments = [
        _fragment("zeta", "rule-z"),
        _fragment("alpha", "rule-a"),
    ]
    body = "## MUST\n\n- Unrelated. _[from `other/rule`]_\n"

    with pytest.raises(ComposerInvalidOutputError) as exc_info:
        orchestrate._verify_completeness(
            canonical_fragments=fragments,
            composed_body=body,
            clarifications=ClarificationsStore(),
            repo_root=tmp_path,
            invoke_options=None,
        )
    message = str(exc_info.value)
    assert message.index("alpha/rule-a") < message.index("zeta/rule-z")


def test_missing_fragment_writes_composed_body_to_composer_log(tmp_path: Path) -> None:
    """Unlike a sentinel-parse failure, this response parses fine - it just
    silently dropped a fragment. The hint still says to inspect
    `$SPAEX_COMPOSER_LOG`, so the body must actually land there."""
    fragments = [_fragment("alpha", "rule-a"), _fragment("beta", "rule-b")]
    body = "## MUST\n\n- Run tests. _[from `alpha/rule-a`]_\n"

    with pytest.raises(ComposerInvalidOutputError, match="beta/rule-b"):
        orchestrate._verify_completeness(
            canonical_fragments=fragments,
            composed_body=body,
            clarifications=ClarificationsStore(),
            repo_root=tmp_path,
            invoke_options=None,
        )

    log_path = tmp_path / ".spaex" / "composer.log"
    assert log_path.read_text(encoding="utf-8") == body
