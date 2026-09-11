"""Clarification round-trip persistence (T043, SC-008).

Three-phase scenario against a fixture with a semantically-overlapping
fragment pair across two molecules:

1. First install: the Composer stub returns Shape B once; the scripted
   operator answers once; the answer persists to `.spaex/clarifications.json`
   and the Composer is re-invoked with it staged, producing `.spaex.md`.
2. Second install, fragment set unchanged: the reproducibility skip (FR-009)
   must reuse the persisted clarification without invoking the Composer or
   the operator at all.
3. After editing the involved fragment's body (via a new publisher revision)
   and bumping the consumer's pin: the stale clarification is invalidated,
   so the Composer asks again, the operator is re-asked exactly once, and
   the new answer replaces the old one under a new key.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior.composer.clarifications import CitedFragment, derive_key
from spaex.behavior.composer.invoke import (
    ClarificationQuestion,
    ComposedShape,
    ComposerInput,
    InvokeOptions,
    InvokeOutcome,
    QuestionsShape,
    RuntimeDescriptor,
)
from spaex.cli import install as install_cli
from spaex.migrate.transform import clone_dir

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


_MOL_A = "com.example.publisher.overlap-a"
_MOL_B = "com.example.publisher.overlap-b"
_CANONICAL = "https://example.invalid/example/publisher-overlap"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _focus_a_text(body: str) -> str:
    return (
        "---\nid: focus-a\nkind: constitution_fragment\n"
        "atom_source: pkg.review-timeliness\nmodality: MUST\n---\n"
        f"{body}"
    )


def _publish_overlap_molecules(tmp_path: Path) -> tuple[Path, str, str, Path]:
    """Publisher repo with two molecules whose fragments a Composer stub
    treats as overlapping. Returns (working_dir, canonical_url, head, state_root)."""
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
                "molecules": {
                    _MOL_A: {"path": "overlap-a", "version": "1.0.0"},
                    _MOL_B: {"path": "overlap-b", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )

    mol_a_dir = working / "overlap-a"
    mol_a_dir.mkdir()
    (mol_a_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL_A,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"behavior": ["fragments/focus-a.md"]},
            },
            indent=2,
        )
    )
    (mol_a_dir / "fragments").mkdir()
    (mol_a_dir / "fragments" / "focus-a.md").write_text(
        _focus_a_text(
            "**MUST** ensure every pull request has a reviewer assigned "
            "within one business day.\n"
        )
    )

    mol_b_dir = working / "overlap-b"
    mol_b_dir.mkdir()
    (mol_b_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL_B,
                "version": "1.0.0",
                "priority": 30,
                "atoms": {"behavior": ["fragments/focus-b.md"]},
            },
            indent=2,
        )
    )
    (mol_b_dir / "fragments").mkdir()
    (mol_b_dir / "fragments" / "focus-b.md").write_text(
        "---\nid: focus-b\nkind: constitution_fragment\n"
        "atom_source: pkg.review-timeliness\nmodality: MUST\n---\n"
        "**MUST** ensure every pull request is reviewed within one business "
        "day of being opened.\n"
    )

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "overlap fixture v1")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return working, _CANONICAL, head, state_root


def _update_focus_a_body(working: Path, state_root: Path, *, new_body: str) -> str:
    """Commit a body-only edit to focus-a and resync the bare clone spaex reads."""
    (working / "overlap-a" / "fragments" / "focus-a.md").write_text(
        _focus_a_text(new_body)
    )
    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "overlap fixture v2: tighten focus-a")
    head = _git(working, "rev-parse", "HEAD")

    target = clone_dir(state_root, _CANONICAL)
    shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return head


def _make_consumer_pinning_both(
    tmp_path: Path, *, source_url: str, revision: str
) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [
                    {
                        "source": source_url,
                        "revision": revision,
                        "molecules": [_MOL_A, _MOL_B],
                    }
                ],
            }
        )
    )
    return consumer


def _bump_consumer_revision(consumer: Path, revision: str) -> None:
    manifest_path = consumer / ".spaex.json"
    data = json.loads(manifest_path.read_text())
    data["compounds"][0]["revision"] = revision
    manifest_path.write_text(json.dumps(data, indent=2))


def _run_install(
    consumer: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0)
    return install_cli.run(ns)


def _build_composed_body(data: dict[str, object]) -> str:
    """Build a Shape A body that echoes the expected hashes (contracts §Shape A)."""
    header = (
        f'<!-- spaex-composed:source_hash="{data["expected_source_hash"]}" '
        f'build_input_hash="{data["expected_build_input_hash"]}" version="1" -->\n'
        "# spaex Behavior Harness\n"
        "\n"
        "_This file is generated by `spaex install`. Do not edit by hand._\n"
        "_Change fragments in `.spaex/constitution.d/` and re-run install._\n"
        "\n"
    )
    bullets: list[str] = []
    for fragment in data["fragments"]:
        scoped = f"{fragment['molecule_id']}/{fragment['fragment_id']}"
        text = fragment["body"].strip().replace("**", "")
        if text.endswith("."):
            text = text[:-1]
        bullets.append(f"- {text}. _[from `{scoped}`]_")
    body = header + "## MUST\n\n" + "\n".join(bullets) + "\n"
    return body


class _ClarificationAwareComposer:
    """Stub Composer: Shape B until a matching clarification key is staged.

    Mirrors a real Composer's behavior of not re-asking a question whose
    answer is already present in its own input (contracts §Shape B): it
    derives the same key spaex would from the fragments it was given and
    checks whether that key is already among the staged `clarifications`.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        composer_input: ComposerInput,
        *,
        repo_root: Path,
        options: InvokeOptions | None = None,
    ) -> InvokeOutcome:
        data = json.loads(composer_input.to_json())
        self.calls.append({"clarification_count": len(data["clarifications"])})
        fragments = data["fragments"]
        cited = tuple(
            CitedFragment(
                molecule_id=f["molecule_id"],
                fragment_id=f["fragment_id"],
                body_sha256=f["body_sha256"],
            )
            for f in fragments
        )
        key = derive_key(cited)
        existing_keys = {c["key"] for c in data["clarifications"]}
        if key not in existing_keys:
            question = ClarificationQuestion(
                kind="overlap",
                cited_fragments=tuple(
                    {"molecule_id": f["molecule_id"], "fragment_id": f["fragment_id"]}
                    for f in fragments
                ),
                question=(
                    "overlap-a and overlap-b both require reviewer assignment "
                    "within one business day. Merge into a single clause?"
                ),
            )
            return InvokeOutcome(
                result=QuestionsShape(questions=(question,)),
                runtime=RuntimeDescriptor(kind="stub", identifier="test"),
                raw_output="shape-b-stub",
            )
        body = _build_composed_body(data)
        return InvokeOutcome(
            result=ComposedShape(body=body),
            runtime=RuntimeDescriptor(kind="stub", identifier="test"),
            raw_output=body,
        )


def _scripted_operator_answer_factory(
    answer: str,
) -> tuple[callable, list[ClarificationQuestion]]:
    calls: list[ClarificationQuestion] = []

    def answer_fn(question: ClarificationQuestion) -> str:
        calls.append(question)
        return answer

    return answer_fn, calls


def test_clarification_answered_once_reused_then_reasked_on_body_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working, canonical, head, state_root = _publish_overlap_molecules(tmp_path)
    consumer = _make_consumer_pinning_both(
        tmp_path, source_url=canonical, revision=head
    )

    composer = _ClarificationAwareComposer()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", composer)
    answer_fn, answer_calls = _scripted_operator_answer_factory(
        "Merge into one clause citing both molecules; keep the MUST modality."
    )
    monkeypatch.setattr(behavior_orchestrate, "_default_operator_answer", answer_fn)

    # Phase 1: first install asks once (Shape B), persists the answer, and
    # re-invokes the Composer once more (Shape A) with it staged.
    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert len(composer.calls) == 2
    assert len(answer_calls) == 1
    first_bytes = (consumer / ".spaex.md").read_bytes()

    stored = json.loads((consumer / ".spaex" / "clarifications.json").read_text())
    assert len(stored["clarifications"]) == 1
    first_entry = next(iter(stored["clarifications"].values()))
    assert first_entry["answer"] == (
        "Merge into one clause citing both molecules; keep the MUST modality."
    )
    assert len(first_entry["cited_fragments"]) == 2
    first_key = next(iter(stored["clarifications"]))

    # Phase 2: second install, fragment set unchanged. The reproducibility
    # skip must reuse the persisted answer without asking again or invoking
    # the Composer at all (SC-008 "not re-asked").
    composer.calls.clear()
    answer_calls.clear()
    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert composer.calls == []
    assert answer_calls == []
    assert (consumer / ".spaex.md").read_bytes() == first_bytes

    # Phase 3: edit focus-a's body via a new publisher revision and bump the
    # consumer's pin. The stale clarification is invalidated, so the
    # Composer asks again and the operator is re-asked exactly once
    # (SC-008 "re-asked exactly once").
    new_head = _update_focus_a_body(
        working,
        state_root,
        new_body=(
            "**MUST** ensure every pull request is assigned a reviewer "
            "within four business hours.\n"
        ),
    )
    _bump_consumer_revision(consumer, new_head)

    composer.calls.clear()
    answer_calls.clear()
    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert len(composer.calls) == 2
    assert len(answer_calls) == 1

    second_bytes = (consumer / ".spaex.md").read_bytes()
    assert second_bytes != first_bytes

    stored_after = json.loads(
        (consumer / ".spaex" / "clarifications.json").read_text()
    )
    assert len(stored_after["clarifications"]) == 1
    second_key = next(iter(stored_after["clarifications"]))
    assert second_key != first_key
