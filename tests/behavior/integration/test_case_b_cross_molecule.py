"""Case B: cross-molecule semantic contradiction aborts install with exit 21 (T040).

Two independently authored molecules ship fragments the Composer flags as
semantically contradictory. The mechanical pre-check accepts the pin set
(disjoint scoped ids), so the contradiction only surfaces once the Composer
returns a Shape B response. In the Phase 3 install path, Shape B (declined
reconciliation) surfaces immediately as exit 21 with a typed diagnostic; the
full clarification loop that would let the operator answer the question is
wired in Phase 6 (T042).

The task text notes that Phase 3 currently maps every Shape B response to
exit 21 regardless of the clarification content, so a stub Composer returning
Shape B is sufficient here (FR-005a, FR-010a, SC-002 Case B).
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
    ClarificationQuestion,
    ComposerInput,
    InvokeOptions,
    InvokeOutcome,
    QuestionsShape,
    RuntimeDescriptor,
)
from spaex.cli import install as install_cli
from spaex.git.cache import clone_dir
from spaex.util import exit_codes
from spaex.util.errors import HaexError

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


_MOL_STRICT = "com.example.publisher.strict-force-push"
_MOL_LENIENT = "com.example.publisher.lenient-force-push"
_CANONICAL = "https://example.invalid/example/publisher-case-b"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_semantically_overlapping_molecules(
    tmp_path: Path,
) -> tuple[str, str, Path]:
    """Two molecules whose fragments would be reconciled by the Composer.

    The scoped ids differ (so the mechanical pre-check accepts them), but the
    bodies contradict each other so the Composer would emit a Shape B
    question in production.
    """
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
                    _MOL_STRICT: {"path": "strict", "version": "1.0.0"},
                    _MOL_LENIENT: {"path": "lenient", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )

    strict_dir = working / "strict"
    strict_dir.mkdir()
    (strict_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL_STRICT,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"behavior": ["fragments/no-force-push.md"]},
            },
            indent=2,
        )
    )
    (strict_dir / "fragments").mkdir()
    (strict_dir / "fragments" / "no-force-push.md").write_text(
        "---\n"
        "id: no-force-push\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.strict-git\n"
        "modality: MUST\n"
        "---\n"
        "**MUST NOT** force-push to any branch. Ever.\n"
    )

    lenient_dir = working / "lenient"
    lenient_dir.mkdir()
    (lenient_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL_LENIENT,
                "version": "1.0.0",
                "priority": 30,
                "atoms": {"behavior": ["fragments/rebase-flow.md"]},
            },
            indent=2,
        )
    )
    (lenient_dir / "fragments").mkdir()
    (lenient_dir / "fragments" / "rebase-flow.md").write_text(
        "---\n"
        "id: rebase-flow\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.rebase-workflow\n"
        "modality: SHOULD\n"
        "---\n"
        "**SHOULD** force-push feature branches after every interactive rebase.\n"
    )

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "case B semantically contradictory fixture")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head, state_root


def _make_consumer_pinning_both(
    tmp_path: Path, *, source_url: str, revision: str
) -> Path:
    """Hand-seed a consumer that already pins both molecules.

    Skipping `spaex add` avoids `InstallTransactionFailedError` wrapping the
    behavior refuse in exit 2 (same reason as T039 Case A).
    """
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex").mkdir()
    (consumer / ".spaex/manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [
                    {
                        "source": source_url,
                        "revision": revision,
                        "molecules": [_MOL_STRICT, _MOL_LENIENT],
                    }
                ],
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


def _shape_b_stub_factory() -> tuple[
    callable[..., InvokeOutcome], list[dict[str, object]]
]:
    """Composer stub that always returns Shape B, recording each invocation."""
    calls: list[dict[str, object]] = []

    def shape_b_invoke_composer(
        composer_input: ComposerInput,
        *,
        repo_root: Path,
        options: InvokeOptions | None = None,
    ) -> InvokeOutcome:
        calls.append(
            {
                "fragment_count": len(composer_input.fragments),
                "expected_source_hash": composer_input.expected_source_hash,
            }
        )
        question = ClarificationQuestion(
            kind="contradiction",
            cited_fragments=(
                {"molecule_id": _MOL_STRICT, "fragment_id": "no-force-push"},
                {"molecule_id": _MOL_LENIENT, "fragment_id": "rebase-flow"},
            ),
            question=(
                "strict-force-push forbids all force-push, rebase-flow requires "
                "it after interactive rebase. Which policy takes precedence?"
            ),
        )
        return InvokeOutcome(
            result=QuestionsShape(questions=(question,)),
            runtime=RuntimeDescriptor(kind="stub", identifier="test"),
            raw_output="shape-b-stub",
        )

    return shape_b_invoke_composer, calls


def test_case_b_shape_b_response_aborts_with_exit_21(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical, head, state_root = _publish_semantically_overlapping_molecules(
        tmp_path
    )
    consumer = _make_consumer_pinning_both(
        tmp_path, source_url=canonical, revision=head
    )

    stub, calls = _shape_b_stub_factory()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    with pytest.raises(HaexError) as excinfo:
        _run_install(consumer, state_root, monkeypatch)

    err = excinfo.value
    assert err.exit_code == exit_codes.BEHAVIOR_SEMANTIC_REFUSE == 21
    assert err.diagnostic_key == "behavior-clarification-required"

    assert len(calls) == 1
    assert calls[0]["fragment_count"] == 2

    assert not (consumer / ".spaex/constitution.md").exists()
