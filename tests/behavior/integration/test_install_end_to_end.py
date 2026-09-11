"""End-to-end `spaex install` with two molecules shipping one fragment each (T030).

Fixture project:
- Two published molecules, each with one `atoms.behavior` fragment.
- Consumer adds both and runs `spaex install`.
- Composer is stubbed via monkeypatch to return a canned Shape A that echoes
  the spaex-computed hashes.

Verifies:
- `<repo-root>/.spaex.md` is written with both directives.
- Provenance suffix names both molecule/fragment scoped keys.
- `.spaex/constitution.d/<molecule-id>/<fragment-id>.md` is materialized for
  each molecule (SC-001 acceptance scenario).
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
    ComposedShape,
    ComposerInput,
    InvokeOptions,
    InvokeOutcome,
    QuestionsShape,
    RuntimeDescriptor,
)
from spaex.cli import add as add_cli
from spaex.cli import install as install_cli
from spaex.migrate.transform import clone_dir

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


_PUBLISHER = "com.example.publisher"
_CANONICAL = "https://example.invalid/example/publisher"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_two_molecules_with_fragments(tmp_path: Path) -> tuple[str, str, Path]:
    working = tmp_path / "publisher-working"
    working.mkdir()
    _git(working, "init", "-q", "-b", "main")
    _git(working, "config", "user.email", "author@example.com")
    _git(working, "config", "user.name", "author")
    _git(working, "config", "commit.gpgsign", "false")

    mol_a = "com.example.publisher.strict-testing"
    mol_b = "com.example.publisher.commit-hygiene"

    (working / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "publisher": _PUBLISHER,
                "molecules": {
                    mol_a: {"path": "strict-testing", "version": "1.0.0"},
                    mol_b: {"path": "commit-hygiene", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )

    dir_a = working / "strict-testing"
    dir_a.mkdir()
    (dir_a / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": mol_a,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"behavior": ["fragments/tests-first.md"]},
            },
            indent=2,
        )
    )
    (dir_a / "fragments").mkdir()
    (dir_a / "fragments" / "tests-first.md").write_text(
        "---\n"
        "id: tests-first\n"
        "kind: constitution_fragment\n"
        "atom_source: hooks.test-runner\n"
        "modality: MUST\n"
        "---\n"
        "**MUST** run the project's tests before every commit.\n"
    )

    dir_b = working / "commit-hygiene"
    dir_b.mkdir()
    (dir_b / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": mol_b,
                "version": "1.0.0",
                "priority": 30,
                "atoms": {"behavior": ["fragments/small-commits.md"]},
            },
            indent=2,
        )
    )
    (dir_b / "fragments").mkdir()
    (dir_b / "fragments" / "small-commits.md").write_text(
        "---\n"
        "id: small-commits\n"
        "kind: constitution_fragment\n"
        "atom_source: policy.commit-hygiene\n"
        "modality: SHOULD\n"
        "---\n"
        "**SHOULD** keep every commit focused on a single logical change.\n"
    )

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "seed two behavior molecules")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head, state_root


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


def _run_add(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_url: str,
    molecule_ids: str,
    revision: str,
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(
        repo_root=str(consumer),
        source_url=source_url,
        molecule_ids=molecule_ids,
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


def _shape_a_from_payload(payload: str) -> str:
    data = json.loads(payload)
    src = data["expected_source_hash"]
    bih = data["expected_build_input_hash"]
    header = (
        f'<!-- spaex-composed:source_hash="{src}" '
        f'build_input_hash="{bih}" version="1" -->\n'
        "# spaex Behavior Harness\n"
        "\n"
        "_This file is generated by `spaex install`. Do not edit by hand._\n"
        "_Change fragments in `.spaex/constitution.d/` and re-run install._\n"
        "\n"
    )
    modality_sections: dict[str, list[str]] = {"MUST": [], "SHOULD": [], "MAY": []}
    for fragment in data["fragments"]:
        scoped = f"{fragment['molecule_id']}/{fragment['fragment_id']}"
        text = fragment["body"].strip().replace("**", "")
        if text.endswith("."):
            text = text[:-1]
        modality = fragment["modality"] or "MUST"
        bucket = modality if modality in modality_sections else "MUST"
        modality_sections[bucket].append(
            f"- {text}. _[from `{scoped}`]_"
        )
    body_parts = [header]
    for modality in ("MUST", "SHOULD", "MAY"):
        bullets = modality_sections[modality]
        if not bullets:
            continue
        body_parts.append(f"## {modality}\n\n")
        body_parts.append("\n".join(bullets) + "\n\n")
    body = "".join(body_parts).rstrip() + "\n"
    return (
        "<<<SPAEX-COMPOSER-BEGIN>>>\n"
        '{"type": "composed", "questions": []}\n'
        "<<<SPAEX-COMPOSER-END>>>\n"
        "\n" + body
    )


def _stub_invoke_composer(
    composer_input: ComposerInput,
    *,
    repo_root: Path,
    options: InvokeOptions | None = None,
) -> InvokeOutcome:
    payload = composer_input.to_json()
    raw = _shape_a_from_payload(payload)
    body = raw.split("<<<SPAEX-COMPOSER-END>>>", 1)[1].lstrip("\n\r ")
    return InvokeOutcome(
        result=ComposedShape(body=body),
        runtime=RuntimeDescriptor(kind="stub", identifier="test"),
        raw_output=raw,
    )


def test_install_composes_both_fragments_into_spaex_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical, head, state_root = _publish_two_molecules_with_fragments(tmp_path)
    consumer = _make_consumer(tmp_path)
    monkeypatch.setattr(
        behavior_orchestrate, "invoke_composer", _stub_invoke_composer
    )

    assert (
        _run_add(
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=(
                "com.example.publisher.strict-testing,"
                "com.example.publisher.commit-hygiene"
            ),
            revision=head,
        )
        == 0
    )

    spaex_md = consumer / ".spaex.md"
    assert spaex_md.exists()
    content = spaex_md.read_text(encoding="utf-8")

    assert "<!-- spaex-composed:" in content
    assert 'version="1"' in content
    assert "## MUST" in content
    assert "## SHOULD" in content
    assert "com.example.publisher.strict-testing/tests-first" in content
    assert "com.example.publisher.commit-hygiene/small-commits" in content

    frag_a = (
        consumer
        / ".spaex"
        / "constitution.d"
        / "com.example.publisher.strict-testing"
        / "tests-first.md"
    )
    frag_b = (
        consumer
        / ".spaex"
        / "constitution.d"
        / "com.example.publisher.commit-hygiene"
        / "small-commits.md"
    )
    assert frag_a.exists()
    assert frag_b.exists()
    assert "**MUST** run the project's tests" in frag_a.read_text(encoding="utf-8")


def _add_and_prepare_for_reinstall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    """Add both molecules with a working Shape A stub, then delete `.spaex.md`
    so the next install cannot short-circuit via the reproducibility skip.
    """
    canonical, head, state_root = _publish_two_molecules_with_fragments(tmp_path)
    consumer = _make_consumer(tmp_path)
    monkeypatch.setattr(
        behavior_orchestrate, "invoke_composer", _stub_invoke_composer
    )
    assert (
        _run_add(
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=(
                "com.example.publisher.strict-testing,"
                "com.example.publisher.commit-hygiene"
            ),
            revision=head,
        )
        == 0
    )
    (consumer / ".spaex.md").unlink()
    return consumer, state_root


def test_install_composer_failure_leaves_spec_023_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Composer failure on re-install must not (re-)create `.spaex.md`."""
    consumer, state_root = _add_and_prepare_for_reinstall(tmp_path, monkeypatch)

    class InjectedComposerError(RuntimeError):
        pass

    def failing_invoke_composer(*_, **__):
        raise InjectedComposerError("simulated composer failure")

    monkeypatch.setattr(
        behavior_orchestrate, "invoke_composer", failing_invoke_composer
    )

    with pytest.raises(InjectedComposerError):
        _run_install(consumer, state_root, monkeypatch)
    assert not (consumer / ".spaex.md").exists()


def test_install_shape_b_response_refuses_with_exit_21(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 3 has no operator round-trip: Shape B surfaces as semantic refuse."""
    consumer, state_root = _add_and_prepare_for_reinstall(tmp_path, monkeypatch)

    def shape_b_invoke_composer(
        composer_input: ComposerInput,
        *,
        repo_root: Path,
        options: InvokeOptions | None = None,
    ) -> InvokeOutcome:
        question = ClarificationQuestion(
            kind="overlap",
            cited_fragments=(
                {
                    "molecule_id": "com.example.publisher.strict-testing",
                    "fragment_id": "tests-first",
                },
            ),
            question="Do these overlap semantically?",
        )
        return InvokeOutcome(
            result=QuestionsShape(questions=(question,)),
            runtime=RuntimeDescriptor(kind="stub", identifier="test"),
            raw_output="raw",
        )

    monkeypatch.setattr(
        behavior_orchestrate, "invoke_composer", shape_b_invoke_composer
    )

    from spaex.util.errors import HaexError

    with pytest.raises(HaexError) as exc:
        _run_install(consumer, state_root, monkeypatch)
    assert exc.value.exit_code == 21
    assert not (consumer / ".spaex.md").exists()
