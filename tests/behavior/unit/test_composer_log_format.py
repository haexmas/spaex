"""JSON-lines composer log format (Spec 026 T002, T006).

`$SPAEX_COMPOSER_LOG` becomes one JSON-lines record per completed
invocation, truncated exactly once at the start of a fresh attempt and
appended (flushed) thereafter, so a later step's failure can't erase
evidence of earlier ones (research.md §5, data-model.md `ComposerLogEntry`).
Applies uniformly whether a build has one step or many.
"""

from __future__ import annotations

import json
from pathlib import Path

from spaex.behavior.composer.invoke import (
    ComposedShape,
    ComposerInput,
    ComposerLogEntry,
    InvokeOptions,
    QuestionsShape,
    append_composer_log_entry,
    invoke_composer,
    truncate_composer_log,
)


def _read_entries(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def test_truncate_then_append_yields_one_entry_per_line(tmp_path: Path) -> None:
    log_path = tmp_path / "composer.log"
    truncate_composer_log(log_path)
    append_composer_log_entry(
        log_path,
        ComposerLogEntry(
            step="batch-1", invocation=1, phase="initial", raw_output="one", outcome="composed"
        ),
    )
    append_composer_log_entry(
        log_path,
        ComposerLogEntry(
            step="batch-2", invocation=1, phase="initial", raw_output="two", outcome="composed"
        ),
    )

    entries = _read_entries(log_path)
    assert [e["step"] for e in entries] == ["batch-1", "batch-2"]
    assert [e["raw_output"] for e in entries] == ["one", "two"]


def test_truncate_clears_a_prior_attempts_entries(tmp_path: Path) -> None:
    log_path = tmp_path / "composer.log"
    append_composer_log_entry(
        log_path,
        ComposerLogEntry(
            step="batch-1", invocation=1, phase="initial", raw_output="stale", outcome="composed"
        ),
    )

    truncate_composer_log(log_path)

    assert log_path.read_text(encoding="utf-8") == ""


def _shape_a_body() -> str:
    return (
        "<<<SPAEX-COMPOSER-BEGIN>>>\n"
        '{"type": "composed", "questions": []}\n'
        "<<<SPAEX-COMPOSER-END>>>\n"
        "\n"
        "body\n"
    )


def _shape_b_body() -> str:
    return (
        "<<<SPAEX-COMPOSER-BEGIN>>>\n"
        '{"type": "questions", "questions": ['
        '{"kind": "overlap", "cited_fragments": '
        '[{"molecule_id": "mol", "fragment_id": "rule"}], "question": "which?"}'
        "]}\n"
        "<<<SPAEX-COMPOSER-END>>>\n"
    )


def test_invoke_composer_appends_one_independently_parseable_entry_per_step(
    tmp_path: Path,
) -> None:
    (tmp_path / ".spaex").mkdir()
    log_path = tmp_path / ".spaex" / "composer.log"
    truncate_composer_log(log_path)

    def stub(runtime: str, prompt: str, payload: str, timeout: float) -> str:
        return _shape_a_body()

    options = InvokeOptions(stub_caller=stub, composer_log_path=log_path)
    outcome1 = invoke_composer(
        ComposerInput(fragments=()), repo_root=tmp_path, options=options, step="batch-1"
    )
    outcome2 = invoke_composer(
        ComposerInput(fragments=()), repo_root=tmp_path, options=options, step="batch-2"
    )

    assert isinstance(outcome1.result, ComposedShape)
    assert isinstance(outcome2.result, ComposedShape)

    entries = _read_entries(log_path)
    assert [e["step"] for e in entries] == ["batch-1", "batch-2"]
    assert all(e["outcome"] == "composed" for e in entries)


def test_clarification_round_trip_retains_both_ordered_records(tmp_path: Path) -> None:
    (tmp_path / ".spaex").mkdir()
    log_path = tmp_path / ".spaex" / "composer.log"
    truncate_composer_log(log_path)

    responses = iter([_shape_b_body(), _shape_a_body()])

    def stub(runtime: str, prompt: str, payload: str, timeout: float) -> str:
        return next(responses)

    options = InvokeOptions(stub_caller=stub, composer_log_path=log_path)
    first = invoke_composer(
        ComposerInput(fragments=()),
        repo_root=tmp_path,
        options=options,
        step="single",
        invocation=1,
        phase="initial",
    )
    assert isinstance(first.result, QuestionsShape)
    second = invoke_composer(
        ComposerInput(fragments=()),
        repo_root=tmp_path,
        options=options,
        step="single",
        invocation=2,
        phase="clarification-resolved",
    )
    assert isinstance(second.result, ComposedShape)

    entries = _read_entries(log_path)
    assert len(entries) == 2
    assert entries[0]["invocation"] == 1
    assert entries[0]["phase"] == "initial"
    assert entries[0]["outcome"] == "questions"
    assert entries[1]["invocation"] == 2
    assert entries[1]["phase"] == "clarification-resolved"
    assert entries[1]["outcome"] == "composed"
