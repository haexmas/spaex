"""Rendering, parsing and verifying the version 2 constitution (Spec 030 T005)."""

from __future__ import annotations

import pytest

from spaex.behavior.decisions import Choice, Decision, PassageRef, build_input_hash
from spaex.behavior.fragment import BehaviorFragment, Modality
from spaex.behavior.passages import finding_key, text_hash
from spaex.behavior.render import RenderError, parse, render, verify

from ._fragments import make_fragment

HASH = "a" * 64
BIG = "\n".join(f"- rule {n}" for n in range(1, 33)) + "\n"
STRUCTURED = "# Heading\n\ntext  \n\n- item\n\n```sh\n$ run\n```\n\n> quote\n\n\n"


def _render(
    fragments: list[BehaviorFragment],
    decisions: list[Decision] | None = None,
    preamble: str = "",
) -> str:
    decisions = decisions or []
    return render(
        fragments,
        decisions,
        source_hash=HASH,
        build_input_hash=build_input_hash(decisions),
        preamble=preamble,
    )


def _decision(first: PassageRef, second: PassageRef, kept: int | None) -> Decision:
    return Decision(
        key=finding_key([(first.scoped_id, first.text_hash), (second.scoped_id, second.text_hash)]),
        kind="contradiction",
        summary="s",
        passages=(first, second),
        choice=Choice(kind="keep", kept=kept) if kept is not None else Choice(kind="keep_all"),
        asked_at="t",
        answered_at="t",
    )


def _ref(scoped_id: str, text: str) -> PassageRef:
    return PassageRef(scoped_id, text_hash(text), text)


def test_every_body_is_present_unchanged_and_blocks_are_sorted() -> None:
    fragments = [
        make_fragment("zeta", "z", "last\n"),
        make_fragment("alpha", "big", BIG, modality=Modality.MUST),
        make_fragment("alpha", "structured", STRUCTURED),
    ]
    text = _render(fragments)
    document = parse(text)
    assert [b.scoped_id for b in document.blocks] == ["alpha/big", "alpha/structured", "zeta/z"]
    assert document.blocks[0].modality == "MUST"
    assert document.blocks[0].body == BIG
    assert document.blocks[1].body == STRUCTURED  # trailing whitespace and blank lines kept
    verify(fragments, [], text)


def test_crlf_is_canonicalized_and_nothing_else() -> None:
    fragment = make_fragment("m", "f", "a  \r\nb\r\n\r\n")
    text = _render([fragment])
    assert parse(text).blocks[0].body == "a  \nb\n\n"
    verify([fragment], [], text)


def test_render_is_deterministic_and_independent_of_input_order() -> None:
    a = make_fragment("m", "a", "one\n")
    b = make_fragment("m", "b", "two\n")
    assert _render([a, b]) == _render([b, a])


def test_preamble_follows_the_notices() -> None:
    text = _render([make_fragment("m", "a", "one\n")], preamble="<!-- note -->\n")
    lines = text.split("\n")
    assert lines[1] == "# spaex Behavior Harness"
    assert lines[6] == "<!-- note -->"
    assert lines[7] == ""
    verify([make_fragment("m", "a", "one\n")], [], text)


def test_keep_one_comments_out_the_other_passage_unchanged() -> None:
    first = make_fragment("m", "a", "intro\nuse tabs\noutro\n")
    second = make_fragment("m", "b", "alpha\nuse spaces\nomega\n")
    decision = _decision(_ref("m/a", "use tabs"), _ref("m/b", "use spaces"), kept=0)
    text = _render([first, second], [decision])
    comment = f'<!-- spaex-excluded kept="m/a:2-2" decision="{decision.key[:12]}"\nuse spaces\n-->'
    assert comment in text
    block = parse(text).blocks[1]
    assert block.body == "alpha\nuse spaces\nomega\n"
    assert [e.text_lines for e in block.exclusions] == [("use spaces",)]
    assert block.exclusions[0].kept == ("m/a:2-2",)
    verify([first, second], [decision], text)


def test_keep_all_comments_out_nothing() -> None:
    first = make_fragment("m", "a", "one\n")
    second = make_fragment("m", "b", "two\n")
    decision = _decision(_ref("m/a", "one"), _ref("m/b", "two"), kept=None)
    text = _render([first, second], [decision])
    assert "<!-- spaex-excluded" not in text
    verify([first, second], [decision], text)


def test_a_line_that_would_close_the_comment_is_escaped_and_restored() -> None:
    first = make_fragment("m", "a", "keep me\n")
    source = "start --> inline\n-->\n--&gt;\n--&amp;gt;\nend\n"
    second = make_fragment("m", "b", source)
    decision = _decision(_ref("m/a", "keep me"), _ref("m/b", source.removesuffix("\n")), kept=0)
    text = _render([first, second], [decision])
    assert "--&gt;" in text
    assert parse(text).blocks[1].body == source
    verify([first, second], [decision], text)


def test_overlapping_exclusions_become_one_comment() -> None:
    kept = make_fragment("m", "a", "keep one\nkeep two\n")
    other = make_fragment("m", "b", "x\nline 1\nline 2\nline 3\ny\n")
    d1 = _decision(_ref("m/a", "keep one"), _ref("m/b", "line 1\nline 2"), kept=0)
    d2 = _decision(_ref("m/a", "keep two"), _ref("m/b", "line 2\nline 3"), kept=0)
    text = _render([kept, other], [d1, d2])
    exclusions = parse(text).blocks[1].exclusions
    assert len(exclusions) == 1
    assert exclusions[0].text_lines == ("line 1", "line 2", "line 3")
    assert len(exclusions[0].decisions) == 2
    verify([kept, other], [d1, d2], text)


def test_verify_catches_a_dropped_line_and_an_altered_line() -> None:
    fragment = make_fragment("m", "a", "one\ntwo\nthree\n")
    text = _render([fragment])
    with pytest.raises(RenderError, match="body differs"):
        verify([fragment], [], text.replace("two\n", ""))
    with pytest.raises(RenderError, match="body differs"):
        verify([fragment], [], text.replace("two", "2"))


def test_verify_catches_a_missing_block_and_a_missing_exclusion() -> None:
    a = make_fragment("m", "a", "one\n")
    b = make_fragment("m", "b", "two\n")
    text = _render([a, b])
    with pytest.raises(RenderError, match="fragment blocks differ"):
        verify([a], [], text)
    decision = _decision(_ref("m/a", "one"), _ref("m/b", "two"), kept=0)
    with pytest.raises(RenderError, match="exclusions differ"):
        verify([a, b], [decision], text)  # text was rendered without the decision


def test_parse_rejects_a_foreign_file() -> None:
    with pytest.raises(RenderError):
        parse("# just a title\n")
