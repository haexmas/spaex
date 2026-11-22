"""Assessment and diagnosis of the composed constitution (Spec 030 T011, research R5)."""

from __future__ import annotations

from pathlib import Path

from spaex.behavior.composer.prompt import effective_prompt_sha256, load_effective_check_prompt
from spaex.behavior.decisions import (
    DECISIONS_FILENAME,
    Checked,
    Choice,
    Decision,
    DecisionStore,
    PassageRef,
    save,
)
from spaex.behavior.passages import finding_key, text_hash
from spaex.behavior.state import (
    assess,
    diagnose,
    expected_text,
    fragments_fingerprint,
)

from ._fragments import make_fragment

A = make_fragment("m", "a", "first line\nuse tabs\n")
B = make_fragment("m", "b", "use spaces\n")


def _prompt_hash(repo: Path) -> str:
    return effective_prompt_sha256(load_effective_check_prompt(repo))


def _decision() -> Decision:
    refs = (
        PassageRef("m/a", text_hash("use tabs"), "use tabs"),
        PassageRef("m/b", text_hash("use spaces"), "use spaces"),
    )
    return Decision(
        key=finding_key([(r.scoped_id, r.text_hash) for r in refs]),
        kind="contradiction",
        summary="s",
        passages=refs,
        choice=Choice(kind="keep", kept=0),
        asked_at="t",
        answered_at="t",
    )


def _write_store(spaex_dir: Path, store: DecisionStore) -> None:
    save(spaex_dir / DECISIONS_FILENAME, store)


def test_fingerprint_changes_on_a_whitespace_only_edit() -> None:
    plain = make_fragment("m", "a", "rule\n")
    padded = make_fragment("m", "a", "rule  \n")
    extra_blank = make_fragment("m", "a", "rule\n\n")
    crlf = make_fragment("m", "a", "rule\r\n")

    assert fragments_fingerprint([plain]) != fragments_fingerprint([padded])
    assert fragments_fingerprint([plain]) != fragments_fingerprint([extra_blank])
    # CRLF is canonicalized to LF, so it is the same text.
    assert fragments_fingerprint([plain]) == fragments_fingerprint([crlf])


def test_fingerprint_is_order_independent_and_covers_every_fragment() -> None:
    assert fragments_fingerprint([A, B]) == fragments_fingerprint([B, A])
    assert fragments_fingerprint([A, B]) != fragments_fingerprint([A])


def test_assess_without_a_decisions_file_needs_a_check(tmp_path: Path) -> None:
    assessment = assess([A, B], repo_root=tmp_path, spaex_dir=tmp_path / ".spaex")

    assert assessment.check_needed is True
    assert assessment.valid == ()
    assert assessment.fingerprint == fragments_fingerprint([A, B])
    assert assessment.prompt_hash == _prompt_hash(tmp_path)


def test_assess_after_a_completed_check_needs_none(tmp_path: Path) -> None:
    spaex_dir = tmp_path / ".spaex"
    _write_store(
        spaex_dir,
        DecisionStore(checked=Checked(fragments_fingerprint([A, B]), _prompt_hash(tmp_path))),
    )

    assert assess([A, B], repo_root=tmp_path, spaex_dir=spaex_dir).check_needed is False


def test_check_is_needed_again_after_a_fragment_or_prompt_change(tmp_path: Path) -> None:
    spaex_dir = tmp_path / ".spaex"
    _write_store(
        spaex_dir,
        DecisionStore(checked=Checked(fragments_fingerprint([A, B]), _prompt_hash(tmp_path))),
    )

    edited = make_fragment("m", "b", "use spaces  \n")
    assert assess([A, edited], repo_root=tmp_path, spaex_dir=spaex_dir).check_needed is True
    assert assess([A], repo_root=tmp_path, spaex_dir=spaex_dir).check_needed is True

    override = tmp_path / ".spaex" / "check-prompt.md"
    override.write_text("another prompt\n", encoding="utf-8")
    assert assess([A, B], repo_root=tmp_path, spaex_dir=spaex_dir).check_needed is True


def test_assess_keeps_only_decisions_whose_passages_still_exist(tmp_path: Path) -> None:
    spaex_dir = tmp_path / ".spaex"
    decision = _decision()
    _write_store(spaex_dir, DecisionStore(decisions={decision.key: decision}))

    assert assess([A, B], repo_root=tmp_path, spaex_dir=spaex_dir).valid == (decision,)
    changed = make_fragment("m", "b", "use two spaces\n")
    assert assess([A, changed], repo_root=tmp_path, spaex_dir=spaex_dir).valid == ()


def test_expected_text_is_pure_and_applies_valid_decisions() -> None:
    decision = _decision()

    first = expected_text([A, B], [decision])
    second = expected_text([B, A], [decision])
    undecided = expected_text([A, B], [])

    assert first == second
    assert first != undecided
    assert "<!-- spaex-excluded" in first
    assert "<!-- spaex-excluded" not in undecided
    assert first.startswith("<!-- spaex-composed:")


def test_expected_text_puts_the_preamble_between_the_notices_and_the_fragments() -> None:
    lines = expected_text([A], [], preamble="<!-- local -->\n").split("\n")

    assert lines.index("# spaex Behavior Harness") < lines.index("<!-- local -->")
    assert lines.index("<!-- local -->") < lines.index('<!-- spaex-fragment id="m/a" -->')


def _current(tmp_path: Path):
    spaex_dir = tmp_path / ".spaex"
    _write_store(
        spaex_dir,
        DecisionStore(checked=Checked(fragments_fingerprint([A, B]), _prompt_hash(tmp_path))),
    )
    return assess([A, B], repo_root=tmp_path, spaex_dir=spaex_dir)


def test_diagnose_current(tmp_path: Path) -> None:
    assessment = _current(tmp_path)

    assert diagnose(assessment, expected_text([A, B], [])) == "current"


def test_diagnose_missing(tmp_path: Path) -> None:
    assert diagnose(_current(tmp_path), None) == "missing"


def test_diagnose_version_1(tmp_path: Path) -> None:
    v1 = (
        f'<!-- spaex-composed:source_hash="{"a" * 64}" '
        f'build_input_hash="{"b" * 64}" version="1" -->\n# x\n'
    )

    assert diagnose(_current(tmp_path), v1) == "version"


def test_diagnose_out_of_date(tmp_path: Path) -> None:
    stale = expected_text([A, B], []) + "hand edit\n"

    assert diagnose(_current(tmp_path), stale) == "out-of-date"


def test_diagnose_unchecked_when_the_text_is_right_but_no_check_covers_it(
    tmp_path: Path,
) -> None:
    assessment = assess([A, B], repo_root=tmp_path, spaex_dir=tmp_path / ".spaex")

    assert diagnose(assessment, expected_text([A, B], [])) == "unchecked"


def test_diagnose_compares_against_the_preamble_text(tmp_path: Path) -> None:
    assessment = _current(tmp_path)
    with_preamble = expected_text([A, B], [], preamble="<!-- local -->\n")

    assert diagnose(assessment, with_preamble, preamble="<!-- local -->\n") == "current"
    assert diagnose(assessment, with_preamble) == "out-of-date"
