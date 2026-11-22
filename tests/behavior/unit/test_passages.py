"""Passages of fragment bodies (Spec 030 T003, research R3)."""

from __future__ import annotations

import pytest

from spaex.behavior.passages import (
    PassageError,
    canonical_body,
    canonical_lines,
    finding_key,
    locate,
    text_hash,
    validate_range,
)

from ._fragments import make_fragment

BODY = "# Title\n\n- one\n- two\n\n```sh\nrun\nrun2\n```\n- three\n"


def test_canonical_body_only_changes_line_endings_and_adds_a_missing_final_newline() -> None:
    assert canonical_body("a\r\nb\rc") == "a\nb\nc\n"
    assert canonical_body("a  \n\n\n") == "a  \n\n\n"
    assert canonical_lines("a\n\n") == ["a", ""]


def test_validate_range_returns_the_lines() -> None:
    fragment = make_fragment("m", "f", BODY)
    passage = validate_range(fragment, 3, 4)
    assert passage.text == "- one\n- two"
    assert passage.scoped_id == "m/f"
    assert passage.text_hash == text_hash("- one\n- two")


@pytest.mark.parametrize(
    ("start", "end"),
    [(0, 1), (3, 2), (1, 99), (2, 2)],
)
def test_validate_range_rejects_outside_and_blank(start: int, end: int) -> None:
    fragment = make_fragment("m", "f", BODY)
    with pytest.raises(PassageError):
        validate_range(fragment, start, end)


def test_validate_range_rejects_cutting_a_fenced_block() -> None:
    fragment = make_fragment("m", "f", BODY)
    with pytest.raises(PassageError):
        validate_range(fragment, 6, 7)  # opens the fence, does not close it
    with pytest.raises(PassageError):
        validate_range(fragment, 7, 8)  # starts inside the fence
    assert validate_range(fragment, 6, 9).text.startswith("```sh")


def test_locate_requires_exactly_one_line_aligned_occurrence() -> None:
    fragment = make_fragment("m", "f", "a\nb\na\nb\nc\n")
    assert locate(fragment, "b\nc") == (4, 5)
    assert locate(fragment, "a\nb") is None  # twice
    assert locate(fragment, "x") is None
    assert locate(fragment, "") is None  # no blank line in the body


def test_finding_key_ignores_order() -> None:
    first = ("m/a", text_hash("x"))
    second = ("m/b", text_hash("y"))
    assert finding_key([first, second]) == finding_key([second, first])
    assert finding_key([first, second]) != finding_key([first])
