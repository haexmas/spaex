"""Fragment drift detection: on-disk edits without a Composer run (T050,
User Story 6 acceptance scenario 3).

Project-local fragments configured via `.spaex.json`'s
`constitution.local_fragments[].file` are read straight from their
referenced file on every `spaex install` invocation
(`materialize.project_local_from_config`, FR-018's file-reference storage
option) rather than being reconstituted from any spaex-managed cache. That
makes them the one class of fragment whose content can drift on disk
between installs with no Composer invocation in between -- exactly
Acceptance Scenario 3: the fragment set and the committed `.spaex.md` fall
out of sync, and the next `spaex install` must detect the drift (via a
`source_hash` mismatch, FR-009) and invoke the Composer to regenerate
`.spaex.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior.composer.invoke import (
    ComposedShape,
    ComposerInput,
    InvokeOptions,
    InvokeOutcome,
    RuntimeDescriptor,
)
from spaex.cli import install as install_cli

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
    fragments_dir = consumer / ".spaex" / "local-fragments"
    fragments_dir.mkdir(parents=True)
    (fragments_dir / "data-retention.md").write_text(_fragment_text(retention_days=30))
    (consumer / ".spaex.json").write_text(
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


class _CountingStub:
    """Counts Composer invocations; echoes the expected header hashes back
    verbatim (contracts §Shape A) so `emit_composed`'s hash verification
    passes."""

    def __init__(self) -> None:
        self.calls: int = 0

    def __call__(
        self,
        composer_input: ComposerInput,
        *,
        repo_root: Path,
        options: InvokeOptions | None = None,
    ) -> InvokeOutcome:
        self.calls += 1
        data = json.loads(composer_input.to_json())
        header = (
            f'<!-- spaex-composed:source_hash="{data["expected_source_hash"]}" '
            f'build_input_hash="{data["expected_build_input_hash"]}" version="1" -->\n'
            "# spaex Behavior Harness\n\n"
        )
        bullets = []
        for fragment in data["fragments"]:
            scoped = f"{fragment['molecule_id']}/{fragment['fragment_id']}"
            text = fragment["body"].strip().replace("**", "").rstrip(".")
            bullets.append(f"- {text}. _[from `{scoped}`]_")
        body = header + "## MUST_NOT\n\n" + "\n".join(bullets) + "\n"
        return InvokeOutcome(
            result=ComposedShape(body=body),
            runtime=RuntimeDescriptor(kind="stub", identifier="test"),
            raw_output=body,
        )


def test_fragment_edited_on_disk_without_composer_run_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer = _make_consumer(tmp_path)
    state_root = tmp_path / "state"
    stub = _CountingStub()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub.calls == 1
    first = (consumer / ".spaex.md").read_bytes()
    assert b"past 30 days" in first

    # Drift: the fragment's source file is edited directly on disk. No
    # spaex command touches `.spaex.md` or the Composer in between.
    fragment_path = consumer / ".spaex" / "local-fragments" / "data-retention.md"
    fragment_path.write_text(_fragment_text(retention_days=7))

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub.calls == 2, (
        "fragment drift on disk must invalidate source_hash and force a "
        "Composer re-invocation (FR-009, User Story 6 acceptance scenario 3)"
    )
    second = (consumer / ".spaex.md").read_bytes()
    assert second != first
    assert b"past 7 days" in second
