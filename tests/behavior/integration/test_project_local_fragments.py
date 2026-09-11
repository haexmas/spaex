"""Project-local additive fragments via the full `spaex install` CLI (T047).

Unlike Phase 5's T041 (which exercised `_project`-scope routing by calling
`orchestrate.run()` directly, before the CLI wiring existed), these tests
drive `.spaex.json`'s `constitution.local_fragments[]` end-to-end through
`spaex install`:

- A project with zero pinned molecules and one inline local fragment gets
  a `.spaex.md` carrying the `_project/<id>` directive (SC-005).
- A project with zero pinned molecules and one file-reference local
  fragment materializes identically (FR-018's second storage option).
- A project-local fragment whose bare id matches an atom-provided fragment
  aborts install with exit 22 before the Composer runs (SC-010).
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
from spaex.cli import install as install_cli
from spaex.migrate.transform import clone_dir
from spaex.util import exit_codes
from spaex.util.errors import HaexError

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_MOL = "com.example.publisher.shared-id-source"
_CANONICAL = "https://example.invalid/example/publisher-project-local"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _shape_a_from_payload(payload: str) -> str:
    """Build a canned Shape A response that echoes every fragment as a bullet."""
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


def _make_consumer(tmp_path: Path, *, local_fragments: list[dict]) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [],
                "constitution": {"local_fragments": local_fragments},
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


def test_inline_local_only_fragment_appears_with_project_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer = _make_consumer(
        tmp_path,
        local_fragments=[
            {
                "id": "shared-client",
                "modality": "MUST",
                "body": "**MUST** route HTTP through the shared client.",
            }
        ],
    )
    state_root = tmp_path / "state"
    monkeypatch.setattr(
        behavior_orchestrate, "invoke_composer", _stub_invoke_composer
    )

    assert _run_install(consumer, state_root, monkeypatch) == 0

    spaex_md = consumer / ".spaex.md"
    assert spaex_md.exists()
    content = spaex_md.read_text(encoding="utf-8")
    assert "_project/shared-client" in content

    frag = consumer / ".spaex" / "constitution.d" / "_project" / "shared-client.md"
    assert frag.exists()


def test_file_reference_local_fragment_materializes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    fragments_dir = consumer / ".spaex" / "local-fragments"
    fragments_dir.mkdir(parents=True)
    (fragments_dir / "no-secrets.md").write_text(
        "---\n"
        "id: no-secrets\n"
        "kind: constitution_fragment\n"
        "atom_source: project\n"
        "modality: MUST_NOT\n"
        "---\n"
        "**MUST NOT** commit secrets to git.\n"
    )
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [],
                "constitution": {
                    "local_fragments": [
                        {"file": ".spaex/local-fragments/no-secrets.md"}
                    ]
                },
            }
        )
    )
    state_root = tmp_path / "state"
    monkeypatch.setattr(
        behavior_orchestrate, "invoke_composer", _stub_invoke_composer
    )

    assert _run_install(consumer, state_root, monkeypatch) == 0

    content = (consumer / ".spaex.md").read_text(encoding="utf-8")
    assert "_project/no-secrets" in content

    frag = consumer / ".spaex" / "constitution.d" / "_project" / "no-secrets.md"
    assert frag.exists()


def _publish_shared_id_molecule(tmp_path: Path) -> tuple[str, str, Path]:
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
                "molecules": {_MOL: {"path": "shared-id", "version": "1.0.0"}},
            },
            indent=2,
        )
    )
    mol_dir = working / "shared-id"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"behavior": ["fragments/shared.md"]},
            },
            indent=2,
        )
    )
    fragments_dir = mol_dir / "fragments"
    fragments_dir.mkdir()
    (fragments_dir / "shared.md").write_text(
        "---\n"
        "id: shared-client\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.http\n"
        "modality: MUST\n"
        "---\n"
        "**MUST** route HTTP through the shared client.\n"
    )

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "project-local override fixture")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head, state_root


def test_project_local_override_aborts_with_exit_22(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical, head, state_root = _publish_shared_id_molecule(tmp_path)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [
                    {"source": canonical, "revision": head, "molecules": [_MOL]}
                ],
                "constitution": {
                    "local_fragments": [
                        {
                            "id": "shared-client",
                            "modality": "SHOULD",
                            "body": "**SHOULD** also route HTTP through the shared client.",
                        }
                    ]
                },
            }
        )
    )

    composer_calls: list[int] = []

    def sentinel_composer(*args, **kwargs):
        composer_calls.append(1)
        raise AssertionError(
            "Composer must not be invoked when the additive-only pre-check "
            "rejects a project-local override (FR-020)"
        )

    monkeypatch.setattr(
        behavior_orchestrate, "invoke_composer", sentinel_composer
    )

    with pytest.raises(HaexError) as excinfo:
        _run_install(consumer, state_root, monkeypatch)

    err = excinfo.value
    assert err.exit_code == exit_codes.BEHAVIOR_PROJECT_LOCAL_REFUSE == 22
    assert "shared-client" in str(err)
    assert composer_calls == []
    assert not (consumer / ".spaex.md").exists()
