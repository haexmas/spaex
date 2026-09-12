"""A molecule shipping zero behavior fragments must not alter the composed
constitution (T038, User Story 2 acceptance scenario 3).

Fixture: one publisher ships two molecules --

- `with-fragment`: declares one `atoms.behavior` fragment.
- `no-fragment`: declares only a non-behavior atom category and no inline
  `constitution_fragments` block.

Two consumers pin the same molecule set except one also adds `no-fragment`.
Both run `spaex install` against the same Composer stub. Verifies:

- Both consumers produce byte-identical `.spaex.md` (the fragment-less
  molecule's presence changes nothing about the composed output).
- `.spaex/constitution.d/` never gets a directory for the fragment-less
  molecule (it is skipped before materialization, per
  `orchestrate._record_declares_behavior`).
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
from spaex.cli import add as add_cli
from spaex.migrate.transform import clone_dir

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_PUBLISHER = "com.example.publisher"
_CANONICAL = "https://example.invalid/example/publisher-no-fragment"

_MOL_WITH_FRAGMENT = "com.example.publisher.with-fragment"
_MOL_NO_FRAGMENT = "com.example.publisher.no-fragment"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_molecules(tmp_path: Path) -> tuple[str, str, Path]:
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
                "publisher": _PUBLISHER,
                "molecules": {
                    _MOL_WITH_FRAGMENT: {"path": "with-fragment", "version": "1.0.0"},
                    _MOL_NO_FRAGMENT: {"path": "no-fragment", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )

    dir_with = working / "with-fragment"
    dir_with.mkdir()
    (dir_with / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL_WITH_FRAGMENT,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"behavior": ["fragments/no-secrets.md"]},
            },
            indent=2,
        )
    )
    (dir_with / "fragments").mkdir()
    (dir_with / "fragments" / "no-secrets.md").write_text(
        "---\n"
        "id: no-secrets\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.security\n"
        "modality: MUST_NOT\n"
        "---\n"
        "**MUST NOT** commit secrets to git.\n"
    )

    dir_without = working / "no-fragment"
    dir_without.mkdir()
    (dir_without / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL_NO_FRAGMENT,
                "version": "1.0.0",
                "priority": 30,
                "atoms": {"other": ["README.md"]},
            },
            indent=2,
        )
    )
    (dir_without / "README.md").write_text("no behavior fragments here.\n")

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "seed with-fragment + no-fragment molecules")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head, state_root


def _make_consumer(tmp_path: Path, name: str) -> Path:
    consumer = tmp_path / name
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


def _shape_a_from_payload(payload: str) -> str:
    data = json.loads(payload)
    src = data["expected_source_hash"]
    bih = data["expected_build_input_hash"]
    header = (
        f'<!-- spaex-composed:source_hash="{src}" '
        f'build_input_hash="{bih}" version="1" -->\n'
        "# spaex Behavior Harness\n\n"
    )
    modality_sections: dict[str, list[str]] = {"MUST": [], "SHOULD": [], "MAY": []}
    for fragment in data["fragments"]:
        scoped = f"{fragment['molecule_id']}/{fragment['fragment_id']}"
        text = fragment["body"].strip().replace("**", "").rstrip(".")
        modality = fragment["modality"] or "MUST"
        bucket = modality if modality in modality_sections else "MUST"
        modality_sections[bucket].append(f"- {text}. _[from `{scoped}`]_")
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
        "<<<SPAEX-COMPOSER-END>>>\n\n" + body
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


def test_fragment_less_molecule_does_not_alter_composed_constitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical, head, state_root = _publish_molecules(tmp_path)
    monkeypatch.setattr(
        behavior_orchestrate, "invoke_composer", _stub_invoke_composer
    )

    baseline = _make_consumer(tmp_path, "baseline")
    assert (
        _run_add(
            baseline,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=_MOL_WITH_FRAGMENT,
            revision=head,
        )
        == 0
    )

    with_extra = _make_consumer(tmp_path, "with-extra")
    assert (
        _run_add(
            with_extra,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=f"{_MOL_WITH_FRAGMENT},{_MOL_NO_FRAGMENT}",
            revision=head,
        )
        == 0
    )

    baseline_md = (baseline / ".spaex.md").read_text(encoding="utf-8")
    with_extra_md = (with_extra / ".spaex.md").read_text(encoding="utf-8")
    assert baseline_md == with_extra_md

    # The fragment-less molecule never gets a constitution.d directory.
    assert not (
        with_extra / ".spaex" / "constitution.d" / _MOL_NO_FRAGMENT
    ).exists()
    assert (
        with_extra / ".spaex" / "constitution.d" / _MOL_WITH_FRAGMENT / "no-secrets.md"
    ).exists()
