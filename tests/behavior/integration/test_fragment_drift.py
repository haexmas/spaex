"""Fragment drift detection: on-disk edits without an install (T050,
User Story 6 acceptance scenario 3, spec 030).

Project-local fragments configured via `.spaex/manifest.json`'s
`constitution.local_fragments[].file` are read straight from their
referenced file on every `spaex install` invocation
(`materialize.project_local_from_config`, FR-018's file-reference storage
option) rather than being reconstituted from any spaex-managed cache. That
makes them the one class of fragment whose content can drift on disk
between installs -- exactly Acceptance Scenario 3: the fragment set and the
committed `.spaex/constitution.md` fall out of sync (the file no longer
equals a fresh render, `render.verify` and `state.diagnose` say so), and the
next `spaex install` must detect the drift, run the check again and
regenerate `.spaex/constitution.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.render import RenderError, parse, verify
from spaex.behavior.state import assess, diagnose
from spaex.cli import install as install_cli

from ..conftest import StubCheck

_FRAGMENT_HEADER = (
    "---\n"
    "id: data-retention\n"
    "kind: constitution_fragment\n"
    "atom_source: project\n"
    "modality: MUST_NOT\n"
    "---\n"
)


def _fragment_text(*, retention_days: int) -> str:
    return (
        f"{_FRAGMENT_HEADER}"
        f"**MUST NOT** retain customer PII past {retention_days} days.\n"
    )


def _make_consumer(tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex").mkdir()
    fragments_dir = consumer / ".spaex" / "local-fragments"
    fragments_dir.mkdir(parents=True)
    (fragments_dir / "data-retention.md").write_text(_fragment_text(retention_days=30))
    (consumer / ".spaex/manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [],
                "constitution": {
                    "local_fragments": [
                        {"file": ".spaex/local-fragments/data-retention.md"}
                    ]
                },
            }
        )
    )
    return consumer


def _run_install(
    consumer: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0)
    return install_cli.run(ns)


def _local_fragments(consumer: Path) -> list[BehaviorFragment]:
    """The materialized fragments the install left behind."""
    path = consumer / ".spaex" / "constitution.d" / "_project" / "data-retention.md"
    return [BehaviorFragment.from_file(path, molecule_id="_project")]


def test_fragment_edited_on_disk_without_install_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    consumer = _make_consumer(tmp_path)
    state_root = tmp_path / "state"

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 1
    first = (consumer / ".spaex/constitution.md").read_bytes()
    first_document = parse(first.decode())
    assert b"past 30 days" in first

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 1, "an unchanged local fragment must skip the check"

    # Drift: the fragment's source file is edited directly on disk. No spaex
    # command touches `.spaex/constitution.md` or the check in between.
    fragment_path = consumer / ".spaex" / "local-fragments" / "data-retention.md"
    fragment_path.write_text(_fragment_text(retention_days=7))

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 2, (
        "fragment drift on disk must change the fragment fingerprint and force a "
        "new check (FR-005, User Story 6 acceptance scenario 3)"
    )
    second = (consumer / ".spaex/constitution.md").read_bytes()
    second_document = parse(second.decode())
    assert second_document.source_hash != first_document.source_hash, (
        "editing a local fragment must change source_hash"
    )
    assert second_document.build_input_hash == first_document.build_input_hash, (
        "editing a local fragment must preserve build_input_hash (no decisions changed)"
    )
    assert second != first
    assert b"past 7 days" in second
    assert b"past 30 days" not in second


def test_stale_composed_file_is_detected_by_verify_and_diagnose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """A composed file that no longer matches its fragments fails `verify` and `diagnose`."""
    consumer = _make_consumer(tmp_path)
    assert _run_install(consumer, tmp_path / "state", monkeypatch) == 0

    spaex_md = consumer / ".spaex/constitution.md"
    current = spaex_md.read_text(encoding="utf-8")
    fragments = _local_fragments(consumer)
    assessment = assess(fragments, repo_root=consumer, spaex_dir=consumer / ".spaex")

    verify(fragments, [], current)
    assert diagnose(assessment, current) == "current"

    # The fragment drifts on disk, and the copy materialized earlier is replaced.
    drifted = _fragment_text(retention_days=7)
    (consumer / ".spaex" / "constitution.d" / "_project" / "data-retention.md").write_text(
        drifted
    )
    new_fragments = _local_fragments(consumer)
    new_assessment = assess(new_fragments, repo_root=consumer, spaex_dir=consumer / ".spaex")

    with pytest.raises(RenderError, match="body differs"):
        verify(new_fragments, [], current)
    assert diagnose(new_assessment, current) == "out-of-date"
    assert new_assessment.check_needed, "the new text must also need a new check"
