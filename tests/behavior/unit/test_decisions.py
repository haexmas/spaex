"""Persisted decisions (Spec 030 T004, research R5 and R8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spaex.behavior.decisions import (
    Checked,
    Choice,
    Decision,
    DecisionsStoreError,
    DecisionStore,
    PassageRef,
    build_input_hash,
    load,
    save,
    valid_decisions,
)
from spaex.behavior.passages import finding_key, text_hash

from ._fragments import make_fragment


def _decision(first: str, second: str, kept: int = 0) -> Decision:
    refs = (
        PassageRef("m/a", text_hash(first), first),
        PassageRef("m/b", text_hash(second), second),
    )
    return Decision(
        key=finding_key([(r.scoped_id, r.text_hash) for r in refs]),
        kind="duplicate",
        summary="same rule",
        passages=refs,
        choice=Choice(kind="keep", kept=kept),
        asked_at="2026-11-22T10:00:00Z",
        answered_at="2026-11-22T10:00:05Z",
    )


def test_roundtrip_is_stable(tmp_path: Path) -> None:
    store = DecisionStore(
        checked=Checked(source_hash="a" * 64, prompt_hash="b" * 64),
        decisions={d.key: d for d in (_decision("x", "y"), _decision("p", "q", kept=1))},
    )
    path = tmp_path / "decisions.json"
    save(path, store)
    first = path.read_text()
    assert load(path) == store
    save(path, load(path))
    assert path.read_text() == first


def test_load_absent_is_empty_and_broken_is_an_error(tmp_path: Path) -> None:
    assert load(tmp_path / "none.json") == DecisionStore()
    (tmp_path / "bad.json").write_text("{nope")
    with pytest.raises(DecisionsStoreError):
        load(tmp_path / "bad.json")
    (tmp_path / "old.json").write_text('{"schema_version": 9}')
    with pytest.raises(DecisionsStoreError):
        load(tmp_path / "old.json")


@pytest.mark.parametrize(
    ("passages", "choice"),
    [(None, {"kind": "keep_all"}), ([None], {"kind": "keep_all"}), ([], [])],
)
def test_load_rejects_malformed_nested_json_containers(
    tmp_path: Path, passages: object, choice: object
) -> None:
    path = tmp_path / "malformed.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "decisions": {
                    "key": {
                        "kind": "duplicate",
                        "summary": "s",
                        "passages": passages,
                        "choice": choice,
                        "asked_at": "t",
                        "answered_at": "t",
                    }
                },
            }
        )
    )
    with pytest.raises(DecisionsStoreError):
        load(path)


def test_unrelated_edit_keeps_a_decision_but_a_changed_passage_drops_it() -> None:
    decision = _decision("rule one", "rule two")
    store = DecisionStore(decisions={decision.key: decision})
    base = (
        make_fragment("m", "a", "intro\nrule one\n"),
        make_fragment("m", "b", "rule two\nmore\n"),
    )
    assert valid_decisions(store, base) == (decision,)
    unrelated = (
        make_fragment("m", "a", "a new intro\nsecond line\nrule one\n"),
        make_fragment("m", "b", "rule two\nmore\nand more\n"),
    )
    assert valid_decisions(store, unrelated) == (decision,)
    edited = (
        make_fragment("m", "a", "intro\nrule one changed\n"),
        make_fragment("m", "b", "rule two\nmore\n"),
    )
    assert valid_decisions(store, edited) == ()
    assert valid_decisions(store, base[:1]) == ()
    fenced = (
        base[0],
        make_fragment("m", "b", "```\nrule two\n```\n"),
    )
    assert valid_decisions(store, fenced) == ()


def test_build_input_hash_depends_on_decisions_only() -> None:
    one = _decision("x", "y")
    other = _decision("x", "y", kept=1)
    assert build_input_hash([]) != build_input_hash([one])
    assert build_input_hash([one]) != build_input_hash([other])
    assert build_input_hash([one]) == build_input_hash([one])
