"""Reproducibility skip mechanism: source/build-input fingerprint comparison
(T049, User Story 6 acceptance scenario 1).

`orchestrate.run` computes `source_hash` (per-fragment identity, metadata,
and body) and `build_input_hash` (effective prompt, prompt version, valid
clarifications) outside the LLM and compares them against the committed
`.spaex.md` header before deciding whether to invoke the Composer at all
(FR-009, contracts/composer-interface.md Build fingerprints; the skip
decision itself lives in `orchestrate.run`, wired in Phase 3 T029/T031).

This file verifies:

1. Two installs against identical committed state must not re-invoke the
   Composer on the second run.
2. Changing a fragment's metadata (modality, with the body left byte-
   identical) still changes `source_hash` and forces a re-invocation.
3. Changing the effective Composer prompt (`.spaex/composer-prompt.md`)
   changes `build_input_hash` and forces a re-invocation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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
from spaex.behavior.emit import read_header_hashes
from spaex.cli import add as add_cli
from spaex.cli import install as install_cli
from spaex.migrate.transform import clone_dir

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_MOL = "com.example.publisher.hash-skip"
_CANONICAL = "https://example.invalid/example/publisher-hash-skip"
_BODY = "**MUST** always route billing calls through the ledger service.\n"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _fragment_text(*, modality: str) -> str:
    return (
        "---\nid: ledger-routing\nkind: constitution_fragment\n"
        f"atom_source: pkg.ledger\nmodality: {modality}\n---\n{_BODY}"
    )


def _publish_molecule(
    tmp_path: Path, *, modality: str = "MUST"
) -> tuple[Path, str, str, Path]:
    """Publisher repo with one molecule/one fragment. Returns
    (working_dir, canonical_url, head, state_root)."""
    working = tmp_path / "publisher-working"
    working.mkdir()
    _git(working, "init", "-q", "-b", "main")
    _git(working, "config", "user.email", "author@example.com")
    _git(working, "config", "user.name", "author")
    _git(working, "config", "commit.gpgsign", "false")

    (working / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "publisher": "com.example.publisher",
                "molecules": {_MOL: {"path": "hash-skip", "version": "1.0.0"}},
            },
            indent=2,
        )
    )
    mol_dir = working / "hash-skip"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"behavior": ["fragments/ledger-routing.md"]},
            },
            indent=2,
        )
    )
    (mol_dir / "fragments").mkdir()
    (mol_dir / "fragments" / "ledger-routing.md").write_text(
        _fragment_text(modality=modality)
    )

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "hash-skip fixture v1")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return working, _CANONICAL, head, state_root


def _commit_modality_change(
    working: Path, state_root: Path, *, new_modality: str
) -> str:
    """Body-unchanged, metadata-only edit: only `modality` changes.

    Resyncs the bare clone via fetch rather than re-cloning: git marks
    pack/object files read-only, and `rmtree` on a bare repo fails with
    `PermissionError` on Windows CI (memory
    feedback_verify_tool_behavior_empirically; same pattern as
    test_clarification_persistence.py's `_update_focus_a_body`).
    """
    (working / "hash-skip" / "fragments" / "ledger-routing.md").write_text(
        _fragment_text(modality=new_modality)
    )
    _git(working, "add", ".")
    _git(
        working,
        "commit",
        "-q",
        "-m",
        f"hash-skip fixture v2: modality={new_modality}",
    )
    head = _git(working, "rev-parse", "HEAD")

    target = clone_dir(state_root, _CANONICAL)
    _git(target, "fetch", "-q", str(working), "+main:main")
    return head


def _make_consumer(tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [],
            }
        )
    )
    return consumer


def _bump_consumer_revision(consumer: Path, revision: str) -> None:
    manifest_path = consumer / ".spaex.json"
    data = json.loads(manifest_path.read_text())
    data["compounds"][0]["revision"] = revision
    manifest_path.write_text(json.dumps(data, indent=2))


def _run_add(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_url: str,
    revision: str,
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(
        repo_root=str(consumer),
        source_url=source_url,
        molecule_ids=_MOL,
        revision=revision,
        all=False,
        lock_timeout=5.0,
    )
    return add_cli.run(ns)


def _run_install(
    consumer: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0)
    return install_cli.run(ns)


class _CountingStub:
    """Counts every Composer invocation; echoes the expected header hashes
    back verbatim (contracts §Shape A) so `emit_composed`'s hash
    verification passes."""

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
        sections: dict[str, list[str]] = {}
        for fragment in data["fragments"]:
            scoped = f"{fragment['molecule_id']}/{fragment['fragment_id']}"
            text = fragment["body"].strip().replace("**", "").rstrip(".")
            bullet = f"- {text}. _[from `{scoped}`]_"
            sections.setdefault(fragment["modality"] or "MUST", []).append(bullet)
        parts = [header]
        for modality in ("MUST", "MUST_NOT", "SHOULD", "SHOULD_NOT", "MAY", "MAY_NOT"):
            bullets = sections.get(modality)
            if not bullets:
                continue
            parts.append(f"## {modality}\n\n" + "\n".join(bullets) + "\n\n")
        body = "".join(parts).rstrip() + "\n"
        return InvokeOutcome(
            result=ComposedShape(body=body),
            runtime=RuntimeDescriptor(kind="stub", identifier="test"),
            raw_output=body,
        )


def test_second_install_skips_composer_when_state_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    stub = _CountingStub()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub.calls == 1
    first = (consumer / ".spaex.md").read_bytes()

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub.calls == 1, (
        "unchanged fragment set + prompt must skip the Composer entirely (FR-009)"
    )
    assert (consumer / ".spaex.md").read_bytes() == first


def test_fragment_metadata_change_invalidates_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Modality-only edit (body byte-identical) must still bust `source_hash`."""
    working, canonical, head, state_root = _publish_molecule(tmp_path, modality="MUST")
    consumer = _make_consumer(tmp_path)
    stub = _CountingStub()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub.calls == 1
    first = (consumer / ".spaex.md").read_bytes()
    first_hashes = read_header_hashes(consumer)
    assert first_hashes is not None
    assert b"## MUST" in first

    new_head = _commit_modality_change(working, state_root, new_modality="SHOULD")
    _bump_consumer_revision(consumer, new_head)

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub.calls == 2, (
        "a metadata-only fragment change must invalidate the fingerprint skip"
    )
    second = (consumer / ".spaex.md").read_bytes()
    second_hashes = read_header_hashes(consumer)
    assert second_hashes is not None
    assert second_hashes[0] != first_hashes[0], (
        "a metadata-only fragment change must change source_hash"
    )
    assert second_hashes[1] == first_hashes[1], (
        "a metadata-only fragment change must preserve build_input_hash"
    )
    assert second != first
    assert b"## SHOULD" in second


def test_effective_prompt_change_invalidates_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    stub = _CountingStub()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub.calls == 1
    first = (consumer / ".spaex.md").read_bytes()
    first_hashes = read_header_hashes(consumer)
    assert first_hashes is not None

    (consumer / ".spaex" / "composer-prompt.md").write_text(
        "custom project composer prompt override\n", encoding="utf-8"
    )

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub.calls == 2, (
        "an effective-prompt change must invalidate build_input_hash"
    )
    second = (consumer / ".spaex.md").read_bytes()
    second_hashes = read_header_hashes(consumer)
    assert second_hashes is not None
    assert second_hashes[0] == first_hashes[0], (
        "a prompt-only change must preserve source_hash"
    )
    assert second_hashes[1] != first_hashes[1], (
        "a prompt-only change must change build_input_hash"
    )
    assert second != first
