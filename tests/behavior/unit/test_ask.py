"""The operator prompt for findings (Spec 030 T013, research R7)."""

from __future__ import annotations

import io

import pytest

from spaex.behavior.ask import default_operator_decision
from spaex.behavior.composer.check import Finding
from spaex.behavior.decisions import Choice
from spaex.util import exit_codes
from spaex.util.errors import HaexError

from ..conftest import make_finding
from ._fragments import make_fragment

FRAGMENTS = (
    make_fragment("m", "a", "intro\nalways use tabs\nmore text\n"),
    make_fragment("m", "b", "never use tabs\nother\n"),
    make_fragment("n", "c", "use tabs too\n"),
)


class _Stdin(io.StringIO):
    def __init__(self, text: str, *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _stdin(monkeypatch: pytest.MonkeyPatch, text: str, *, tty: bool = True) -> None:
    monkeypatch.setattr("sys.stdin", _Stdin(text, tty=tty))


def _two() -> Finding:
    return make_finding(FRAGMENTS, "contradiction", ("m/a", 2, 2), ("m/b", 1, 1))


def _three() -> Finding:
    return make_finding(
        FRAGMENTS, "duplicate", ("m/a", 2, 2), ("m/b", 1, 1), ("n/c", 1, 1), summary="same rule"
    )


def test_non_interactive_terminal_refuses_with_exit_21(monkeypatch: pytest.MonkeyPatch) -> None:
    _stdin(monkeypatch, "1\n", tty=False)

    with pytest.raises(HaexError) as caught:
        default_operator_decision(_two())

    assert caught.value.exit_code == exit_codes.BEHAVIOR_SEMANTIC_REFUSE == 21
    assert caught.value.diagnostic_key == "behavior-clarification-required"
    assert "m/a" in caught.value.message and "m/b" in caught.value.message
    assert "interactive terminal" in caught.value.hint


@pytest.mark.parametrize("answer", ["\n", "   \n", ""])
def test_blank_answer_or_end_of_input_declines_with_exit_21(
    monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    _stdin(monkeypatch, answer)

    with pytest.raises(HaexError) as caught:
        default_operator_decision(_two())

    assert caught.value.exit_code == 21
    assert "declined" in caught.value.message


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("1\n", Choice(kind="keep", kept=0)),
        ("2\n", Choice(kind="keep", kept=1)),
        ("a\n", Choice(kind="keep_all")),
        ("A\n", Choice(kind="keep_all")),
        ("  2  \n", Choice(kind="keep", kept=1)),
    ],
)
def test_valid_answers_become_choices(
    monkeypatch: pytest.MonkeyPatch, answer: str, expected: Choice
) -> None:
    _stdin(monkeypatch, answer)

    assert default_operator_decision(_two()) == expected


def test_three_passages_offer_three_keep_options(monkeypatch: pytest.MonkeyPatch) -> None:
    _stdin(monkeypatch, "3\n")

    assert default_operator_decision(_three()) == Choice(kind="keep", kept=2)


def test_invalid_answers_reprompt_until_a_valid_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stdin(monkeypatch, "x\n0\n3\n7\n2\n")

    assert default_operator_decision(_two()) == Choice(kind="keep", kept=1)

    out = capsys.readouterr().out
    assert out.count("Please answer with a number from the list, or 'a'.") == 4
    assert out.count("Choice (blank to decline and abort install):") == 5


def test_prompt_shows_kind_summary_and_both_passages_with_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stdin(monkeypatch, "a\n")

    default_operator_decision(_two())

    out = capsys.readouterr().out
    assert "Finding (contradiction): they disagree" in out
    assert "[1] m/a, lines 2-2:" in out
    assert "always use tabs" in out
    assert "[2] m/b, lines 1-1:" in out
    assert "never use tabs" in out
    assert "1: keep [1], comment out the other" in out
    assert "2: keep [2], comment out the other" in out
    assert "a: keep all" in out


def test_three_passage_prompt_says_the_others(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stdin(monkeypatch, "a\n")

    default_operator_decision(_three())

    out = capsys.readouterr().out
    assert "3: keep [3], comment out the others" in out
    assert "Finding (duplicate): same rule" in out


def test_multi_line_passage_text_is_shown_line_by_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stdin(monkeypatch, "1\n")
    finding = make_finding(FRAGMENTS, "duplicate", ("m/a", 2, 3), ("m/b", 1, 2))

    default_operator_decision(finding)

    out = capsys.readouterr().out
    assert "      always use tabs\n      more text\n" in out
