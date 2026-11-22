"""JSON-lines composer log format (Spec 026 T002, T006).

`$SPAEX_COMPOSER_LOG` becomes one JSON-lines record per completed
invocation, truncated exactly once at the start of a fresh attempt and
appended (flushed) thereafter, so a later step's failure can't erase
evidence of earlier ones (research.md §5, data-model.md `ComposerLogEntry`).
Applies uniformly whether a check has one step or many.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spaex.behavior.composer.check import CheckInput, run_check
from spaex.behavior.composer.invoke import (
    ComposerLogEntry,
    InvokeOptions,
    append_composer_log_entry,
    truncate_composer_log,
)
from spaex.util.errors import HaexError


def _read_entries(path: Path) -> list[dict]:
    """Read every non-empty JSON-lines entry from a composer log."""
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def test_truncate_then_append_yields_one_entry_per_line(tmp_path: Path) -> None:
    """Append each completed invocation as an independent JSON line."""
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
    """Clear records from the prior composition attempt."""
    log_path = tmp_path / "composer.log"
    append_composer_log_entry(
        log_path,
        ComposerLogEntry(
            step="batch-1", invocation=1, phase="initial", raw_output="stale", outcome="composed"
        ),
    )

    truncate_composer_log(log_path)

    assert log_path.read_text(encoding="utf-8") == ""


def _no_findings() -> str:
    """Return a minimal check answer without findings."""
    return (
        "<<<SPAEX-COMPOSER-BEGIN>>>\n"
        '{"type": "no_findings"}\n'
        "<<<SPAEX-COMPOSER-END>>>\n"
    )


def _findings_for_missing_fragment() -> str:
    """Return a check answer that names a fragment that does not exist."""
    return (
        "<<<SPAEX-COMPOSER-BEGIN>>>\n"
        '{"type": "findings", "findings": [{"kind": "duplicate", "summary": "same", '
        '"passages": [{"fragment": "a/b", "start": 1, "end": 1}, '
        '{"fragment": "c/d", "start": 1, "end": 1}]}]}\n'
        "<<<SPAEX-COMPOSER-END>>>\n"
    )


def test_run_check_appends_one_independently_parseable_entry_per_step(
    tmp_path: Path,
) -> None:
    """Log independently parseable entries for successive check steps."""
    (tmp_path / ".spaex").mkdir()
    log_path = tmp_path / ".spaex" / "composer.log"
    truncate_composer_log(log_path)

    def stub(runtime: str, prompt: str, payload: str, timeout: float) -> str:
        """Return a successful answer for every invocation."""
        return _no_findings()

    options = InvokeOptions(stub_caller=stub, composer_log_path=log_path)
    assert run_check(
        CheckInput(fragments=()), repo_root=tmp_path, options=options, step="check-g1"
    ) == ()
    assert run_check(
        CheckInput(fragments=()), repo_root=tmp_path, options=options, step="check-g2"
    ) == ()

    entries = _read_entries(log_path)
    assert [e["step"] for e in entries] == ["check-g1", "check-g2"]
    assert all(e["outcome"] == "no_findings" for e in entries)


def test_a_failed_step_does_not_erase_the_entries_before_it(tmp_path: Path) -> None:
    """Retain the earlier step's record when a later step's answer is unusable."""
    (tmp_path / ".spaex").mkdir()
    log_path = tmp_path / ".spaex" / "composer.log"
    truncate_composer_log(log_path)

    responses = iter([_no_findings(), _findings_for_missing_fragment()])

    def stub(runtime: str, prompt: str, payload: str, timeout: float) -> str:
        """Return a usable answer first and an unverifiable one second."""
        return next(responses)

    options = InvokeOptions(stub_caller=stub, composer_log_path=log_path)
    run_check(CheckInput(fragments=()), repo_root=tmp_path, options=options, step="check-g1")
    with pytest.raises(HaexError) as caught:
        run_check(
            CheckInput(fragments=()),
            repo_root=tmp_path,
            options=options,
            step="check-g2",
            invocation=2,
            phase="retry",
        )
    assert caught.value.exit_code == 32

    entries = _read_entries(log_path)
    assert [(e["step"], e["invocation"], e["outcome"]) for e in entries] == [
        ("check-g1", 1, "no_findings"),
        ("check-g2", 2, "invalid-output"),
    ]
    assert entries[1]["phase"] == "retry"
