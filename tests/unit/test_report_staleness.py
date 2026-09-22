"""Unit tests for `check_constitution_staleness` (Spec 028 T016, research.md R4)."""

from __future__ import annotations

from pathlib import Path

from spaex.behavior.composer.clarifications import ClarificationsStore
from spaex.behavior.composer.prompt import (
    COMPOSER_PROMPT_VERSION,
    effective_prompt_sha256,
    load_effective_prompt,
)
from spaex.behavior.emit import compute_build_input_hash, compute_source_hash
from spaex.behavior.fragment import BehaviorFragment
from spaex.report.staleness import check_constitution_staleness

_FRAGMENT_TEXT = (
    "---\nid: ledger-routing\nkind: constitution_fragment\n"
    "atom_source: pkg.ledger\nmodality: MUST\n---\n"
    "**MUST** always route billing calls through the ledger service.\n"
)
_MOLECULE_ID = "com.example.publisher.staleness"


def _write_fragment(repo_root: Path) -> BehaviorFragment:
    fragment_dir = repo_root / ".spaex" / "constitution.d" / _MOLECULE_ID
    fragment_dir.mkdir(parents=True)
    fragment_path = fragment_dir / "ledger-routing.md"
    fragment_path.write_text(_FRAGMENT_TEXT, encoding="utf-8")
    return BehaviorFragment.from_file(fragment_path, molecule_id=_MOLECULE_ID)


def _write_matching_header(repo_root: Path, fragment: BehaviorFragment) -> None:
    source_hash = compute_source_hash([fragment])
    prompt_hash = effective_prompt_sha256(load_effective_prompt(repo_root))
    build_input_hash = compute_build_input_hash(
        effective_prompt_sha256=prompt_hash,
        composer_prompt_version=COMPOSER_PROMPT_VERSION,
        valid_clarifications=ClarificationsStore().entries.values(),
    )
    constitution_path = repo_root / ".spaex" / "constitution.md"
    constitution_path.write_text(
        f'<!-- spaex-composed:source_hash="{source_hash}" '
        f'build_input_hash="{build_input_hash}" version="1" -->\n'
        "# Constitution\n",
        encoding="utf-8",
    )


def test_header_matches_recomputed_hashes_is_not_stale(tmp_path: Path) -> None:
    """A header consistent with the on-disk fragments is not stale."""
    fragment = _write_fragment(tmp_path)
    _write_matching_header(tmp_path, fragment)

    assert check_constitution_staleness(tmp_path) is False


def test_header_fragment_mismatch_is_stale(tmp_path: Path) -> None:
    """A header that no longer matches the on-disk fragments is stale."""
    fragment = _write_fragment(tmp_path)
    _write_matching_header(tmp_path, fragment)
    # Edit the fragment after the header was written, without updating it.
    fragment_path = (
        tmp_path / ".spaex" / "constitution.d" / _MOLECULE_ID / "ledger-routing.md"
    )
    fragment_path.write_text(
        _FRAGMENT_TEXT.replace("billing calls", "refund calls"), encoding="utf-8"
    )

    assert check_constitution_staleness(tmp_path) is True


def test_invalid_existing_fragment_is_stale(tmp_path: Path) -> None:
    """An invalid fragment must not be silently omitted from freshness checks."""
    fragment = _write_fragment(tmp_path)
    _write_matching_header(tmp_path, fragment)
    invalid_path = (
        tmp_path / ".spaex" / "constitution.d" / _MOLECULE_ID / "invalid.md"
    )
    invalid_path.write_text("not a constitution fragment\n", encoding="utf-8")

    assert check_constitution_staleness(tmp_path) is True


def test_missing_header_with_fragments_present_is_stale(tmp_path: Path) -> None:
    """Fragments present but no composed constitution header at all is stale."""
    _write_fragment(tmp_path)

    assert check_constitution_staleness(tmp_path) is True


def test_no_fragments_and_no_file_is_not_stale(tmp_path: Path) -> None:
    """Nothing to compose yet: not stale (the 'no behavior molecules' case)."""
    assert check_constitution_staleness(tmp_path) is False
