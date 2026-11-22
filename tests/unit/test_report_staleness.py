"""Unit tests for `check_constitution_staleness` (Spec 028 T016, reworked for Spec 030).

Stale means: the composed constitution is missing, is format version 1, differs
from a fresh render of the fragments and valid decisions, or no completed check
covers these fragments (research R12).
"""

from __future__ import annotations

from pathlib import Path

from spaex.behavior.composer.prompt import effective_prompt_sha256, load_effective_check_prompt
from spaex.behavior.decisions import DECISIONS_FILENAME, Checked, DecisionStore, save
from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.state import expected_text, fragments_fingerprint
from spaex.report.staleness import check_constitution_staleness

_FRAGMENT_TEXT = (
    "---\nid: ledger-routing\nkind: constitution_fragment\n"
    "atom_source: pkg.ledger\nmodality: MUST\n---\n"
    "**MUST** always route billing calls through the ledger service.\n"
)
_MOLECULE_ID = "com.example.publisher.staleness"


def _fragment_path(repo_root: Path) -> Path:
    return repo_root / ".spaex" / "constitution.d" / _MOLECULE_ID / "ledger-routing.md"


def _write_fragment(repo_root: Path) -> BehaviorFragment:
    path = _fragment_path(repo_root)
    path.parent.mkdir(parents=True)
    path.write_text(_FRAGMENT_TEXT, encoding="utf-8")
    return BehaviorFragment.from_file(path, molecule_id=_MOLECULE_ID)


def _write_constitution(repo_root: Path, fragment: BehaviorFragment) -> None:
    (repo_root / ".spaex" / "constitution.md").write_text(
        expected_text([fragment], []), encoding="utf-8"
    )


def _write_checked(repo_root: Path, fragment: BehaviorFragment) -> None:
    prompt_hash = effective_prompt_sha256(load_effective_check_prompt(repo_root))
    store = DecisionStore(checked=Checked(fragments_fingerprint([fragment]), prompt_hash))
    save(repo_root / ".spaex" / DECISIONS_FILENAME, store)


def test_rendered_text_and_completed_check_is_not_stale(tmp_path: Path) -> None:
    """A file equal to a fresh render, covered by a completed check, is current."""
    fragment = _write_fragment(tmp_path)
    _write_constitution(tmp_path, fragment)
    _write_checked(tmp_path, fragment)

    assert check_constitution_staleness(tmp_path) is False


def test_fragment_edited_after_rendering_is_stale(tmp_path: Path) -> None:
    """A fragment that changed after the file was rendered makes it stale."""
    fragment = _write_fragment(tmp_path)
    _write_constitution(tmp_path, fragment)
    _write_checked(tmp_path, fragment)
    _fragment_path(tmp_path).write_text(
        _FRAGMENT_TEXT.replace("billing calls", "refund calls"), encoding="utf-8"
    )

    assert check_constitution_staleness(tmp_path) is True


def test_text_that_differs_from_a_fresh_render_is_stale(tmp_path: Path) -> None:
    """A hand edit of the composed file is out of date."""
    fragment = _write_fragment(tmp_path)
    _write_constitution(tmp_path, fragment)
    _write_checked(tmp_path, fragment)
    path = tmp_path / ".spaex" / "constitution.md"
    path.write_text(path.read_text(encoding="utf-8") + "extra line\n", encoding="utf-8")

    assert check_constitution_staleness(tmp_path) is True


def test_format_version_1_file_is_stale(tmp_path: Path) -> None:
    """A version 1 composed file is out of date even with a completed check."""
    fragment = _write_fragment(tmp_path)
    _write_checked(tmp_path, fragment)
    (tmp_path / ".spaex" / "constitution.md").write_text(
        f'<!-- spaex-composed:source_hash="{"a" * 64}" '
        f'build_input_hash="{"b" * 64}" version="1" -->\n# Constitution\n',
        encoding="utf-8",
    )

    assert check_constitution_staleness(tmp_path) is True


def test_correct_text_without_a_completed_check_is_stale(tmp_path: Path) -> None:
    """No decisions file means no completed check covers the fragments."""
    fragment = _write_fragment(tmp_path)
    _write_constitution(tmp_path, fragment)

    assert check_constitution_staleness(tmp_path) is True


def test_check_state_for_other_fragments_is_stale(tmp_path: Path) -> None:
    """A recorded check that covers different text does not cover these fragments."""
    fragment = _write_fragment(tmp_path)
    _write_constitution(tmp_path, fragment)
    save(
        tmp_path / ".spaex" / DECISIONS_FILENAME,
        DecisionStore(checked=Checked("0" * 64, "1" * 64)),
    )

    assert check_constitution_staleness(tmp_path) is True


def test_invalid_existing_fragment_is_stale(tmp_path: Path) -> None:
    """An invalid fragment must not be silently omitted from freshness checks."""
    fragment = _write_fragment(tmp_path)
    _write_constitution(tmp_path, fragment)
    _write_checked(tmp_path, fragment)
    invalid_path = _fragment_path(tmp_path).with_name("invalid.md")
    invalid_path.write_text("not a constitution fragment\n", encoding="utf-8")

    assert check_constitution_staleness(tmp_path) is True


def test_missing_constitution_with_fragments_present_is_stale(tmp_path: Path) -> None:
    """Fragments present but no composed constitution at all is stale."""
    _write_fragment(tmp_path)

    assert check_constitution_staleness(tmp_path) is True


def test_composed_file_without_fragments_is_stale(tmp_path: Path) -> None:
    """A composed constitution with no fragment behind it should not exist."""
    (tmp_path / ".spaex").mkdir()
    (tmp_path / ".spaex" / "constitution.md").write_text("leftover\n", encoding="utf-8")

    assert check_constitution_staleness(tmp_path) is True


def test_no_fragments_and_no_file_is_not_stale(tmp_path: Path) -> None:
    """Nothing to compose yet: not stale (the 'no behavior molecules' case)."""
    assert check_constitution_staleness(tmp_path) is False
