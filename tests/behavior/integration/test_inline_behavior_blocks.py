"""Inline `constitution_fragments:` blocks vs. standalone fragment atoms (T037).

A typed atom (e.g. a speckit-workflow atom) MAY declare an inline
`constitution_fragments:` block in its manifest instead of shipping a
standalone `atoms.behavior` fragment file (contracts/fragment-format.md
§"Inline behavior blocks in typed atoms"). FR-003 and User Story 2's
acceptance scenario 2 require the two authoring paths to be treated
identically during composition.

Fixture: one publisher ships two molecules whose only difference is the
fragment *authoring path* -- one uses a standalone `atoms.behavior` file,
the other an inline `constitution_fragments` block on a typed atom id --
but whose `id` / `atom_source` / `modality` / `tags` / `body` are otherwise
identical. Verifies:

- Both molecules materialize a fragment file under
  `.spaex/constitution.d/<molecule-id>/<fragment-id>.md`.
- The two materialized files are byte-identical (the only difference
  between the two molecules is *how* the fragment was authored).
- `spaex install` renders both into `.spaex/constitution.md` as verbatim fragment
  blocks, exactly as any other fragment (SC-001-style body + scoped-id check), and the
  check receives both with identical id, atom source, modality, tags and body.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior.composer.check import Finding
from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.render import parse
from spaex.cli import add as add_cli
from spaex.git.cache import clone_dir

from ..conftest import StubCheck

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_PUBLISHER = "com.example.publisher"
_CANONICAL = "https://example.invalid/example/publisher-inline-blocks"

_MOL_STANDALONE = "com.example.publisher.standalone-frag"
_MOL_INLINE = "com.example.publisher.inline-frag"

_FRAGMENT_BODY = (
    "**MUST** run /speckit-specify before any implementation work on a "
    "non-trivial feature."
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_standalone_and_inline_molecules(tmp_path: Path) -> tuple[str, str, Path]:
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
                    _MOL_STANDALONE: {"path": "standalone-frag", "version": "1.0.0"},
                    _MOL_INLINE: {"path": "inline-frag", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )

    dir_standalone = working / "standalone-frag"
    dir_standalone.mkdir()
    (dir_standalone / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL_STANDALONE,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"behavior": ["fragments/spec-first.md"]},
            },
            indent=2,
        )
    )
    (dir_standalone / "fragments").mkdir()
    (dir_standalone / "fragments" / "spec-first.md").write_text(
        "---\n"
        "id: spec-first\n"
        "kind: constitution_fragment\n"
        "atom_source: speckit-strict\n"
        "modality: MUST\n"
        "tags: [speckit]\n"
        "---\n"
        f"{_FRAGMENT_BODY}\n"
    )

    dir_inline = working / "inline-frag"
    dir_inline.mkdir()
    (dir_inline / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL_INLINE,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"speckit_workflow": ["workflow.md"]},
                "constitution_fragments": {
                    "speckit-strict": [
                        {
                            "id": "spec-first",
                            "modality": "MUST",
                            "tags": ["speckit"],
                            "body": _FRAGMENT_BODY,
                        }
                    ]
                },
            },
            indent=2,
        )
    )
    (dir_inline / "workflow.md").write_text(
        "speckit-workflow typed atom (test fixture).\n"
    )

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "seed standalone + inline fragment molecules")
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
    (consumer / ".spaex").mkdir()
    (consumer / ".spaex/manifest.json").write_text(
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


def test_inline_block_materializes_identically_to_standalone_atom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    canonical, head, state_root = _publish_standalone_and_inline_molecules(tmp_path)
    consumer = _make_consumer(tmp_path)

    received: list[list[BehaviorFragment]] = []

    def capture(fragments: Sequence[BehaviorFragment]) -> list[Finding]:
        received.append(list(fragments))
        return []

    stub_check.factory = capture

    assert (
        _run_add(
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=f"{_MOL_STANDALONE},{_MOL_INLINE}",
            revision=head,
        )
        == 0
    )

    standalone_path = (
        consumer / ".spaex" / "constitution.d" / _MOL_STANDALONE / "spec-first.md"
    )
    inline_path = (
        consumer / ".spaex" / "constitution.d" / _MOL_INLINE / "spec-first.md"
    )
    assert standalone_path.exists()
    assert inline_path.exists()

    # Same id/atom_source/modality/tags/body, authored two different ways:
    # the rendered fragment files must be byte-identical (FR-003).
    assert standalone_path.read_bytes() == inline_path.read_bytes()

    assert len(received) == 1
    records = {fragment.molecule_id: fragment for fragment in received[0]}
    assert set(records) == {_MOL_STANDALONE, _MOL_INLINE}
    for field in ("id", "atom_source", "modality", "tags", "body", "body_hash"):
        assert getattr(records[_MOL_STANDALONE], field) == getattr(
            records[_MOL_INLINE], field
        )

    content = (consumer / ".spaex/constitution.md").read_text(encoding="utf-8")
    blocks = {block.scoped_id: block for block in parse(content).blocks}
    assert set(blocks) == {
        f"{_MOL_STANDALONE}/spec-first",
        f"{_MOL_INLINE}/spec-first",
    }
    assert (
        blocks[f"{_MOL_STANDALONE}/spec-first"].body
        == blocks[f"{_MOL_INLINE}/spec-first"].body
        == _FRAGMENT_BODY + "\n"
    )
