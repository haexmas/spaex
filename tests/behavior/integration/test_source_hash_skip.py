"""Check skip mechanism: no model call while fragments and check prompt are unchanged
(T049, User Story 6 acceptance scenario 1, spec 030 research R5).

`orchestrate.run` records in `.spaex/decisions.json` which fragments (exact text)
and which effective check prompt the last completed check covered. The check, the
one remaining model call, runs only when that state differs from the current one
(FR-005). The composed constitution itself never depends on the check prompt
(FR-003), so its header fingerprint is the only thing a metadata change touches.

This file verifies:

1. Two installs against identical state must not call the check on the second run.
2. Changing a fragment's modality (body byte-identical) changes the header
   `source_hash` and the block's modality, keeps `build_input_hash`, and re-runs the
   check (the modality is part of what the check reads).
3. Changing the effective check prompt (`.spaex/check-prompt.md`) re-runs the check
   and changes neither the text nor either header hash.
4. Editing a fragment body re-runs the check exactly once.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior.emit import compute_source_hash
from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.render import parse
from spaex.cli import add as add_cli
from spaex.cli import install as install_cli
from spaex.git.cache import clone_dir

from ..conftest import StubCheck

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


def _bump_consumer_revision(consumer: Path, revision: str) -> None:
    manifest_path = consumer / ".spaex/manifest.json"
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


def _headers(consumer: Path) -> tuple[str, str]:
    document = parse((consumer / ".spaex/constitution.md").read_text(encoding="utf-8"))
    return document.source_hash, document.build_input_hash


def test_second_install_skips_the_check_when_state_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub_check.calls == 1
    first = (consumer / ".spaex/constitution.md").read_bytes()

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 1, (
        "unchanged fragments and check prompt must skip the check entirely (FR-005)"
    )
    assert (consumer / ".spaex/constitution.md").read_bytes() == first


def test_fragment_metadata_change_changes_source_hash_and_modality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """Modality-only edit (body byte-identical) must still bust the header `source_hash`."""
    working, canonical, head, state_root = _publish_molecule(tmp_path, modality="MUST")
    consumer = _make_consumer(tmp_path)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    first = (consumer / ".spaex/constitution.md").read_bytes()
    first_hashes = _headers(consumer)
    assert b'modality="MUST"' in first
    assert stub_check.calls == 1

    new_head = _commit_modality_change(working, state_root, new_modality="SHOULD")
    _bump_consumer_revision(consumer, new_head)

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 2, "a modality change must re-run the check"
    second = (consumer / ".spaex/constitution.md").read_bytes()
    second_hashes = _headers(consumer)
    assert second_hashes[0] != first_hashes[0], (
        "a metadata-only fragment change must change source_hash"
    )
    assert second_hashes[1] == first_hashes[1], (
        "a metadata-only fragment change must preserve build_input_hash"
    )
    assert second != first
    assert b'modality="SHOULD"' in second
    assert b'modality="MUST"' not in second
    block = parse(second.decode()).blocks[0]
    assert block.body == _BODY


def test_check_prompt_change_reruns_the_check_but_not_the_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub_check.calls == 1
    first = (consumer / ".spaex/constitution.md").read_bytes()
    first_hashes = _headers(consumer)

    (consumer / ".spaex" / "check-prompt.md").write_text(
        "custom project check prompt override\n", encoding="utf-8"
    )

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 2, "an effective check prompt change must re-run the check"
    assert (consumer / ".spaex/constitution.md").read_bytes() == first, (
        "the check prompt must not influence the composed text (FR-003)"
    )
    assert _headers(consumer) == first_hashes

    # And the new check state is recorded, so the next install skips again.
    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 2


def test_body_change_reruns_the_check_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    working, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub_check.calls == 1

    new_body = _BODY + "**MUST** also record every ledger call.\n"
    (working / "hash-skip" / "fragments" / "ledger-routing.md").write_text(
        _fragment_text(modality="MUST").replace(_BODY, new_body)
    )
    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "hash-skip fixture v2: body")
    new_head = _git(working, "rev-parse", "HEAD")
    _git(clone_dir(state_root, _CANONICAL), "fetch", "-q", str(working), "+main:main")
    _bump_consumer_revision(consumer, new_head)

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 2
    block = parse((consumer / ".spaex/constitution.md").read_text(encoding="utf-8")).blocks[0]
    assert block.body == new_body

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 2


def test_header_source_hash_is_the_fragment_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """The header `source_hash` is computed by spaex from the materialized fragments."""
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    fragment = BehaviorFragment.from_file(
        consumer / ".spaex" / "constitution.d" / _MOL / "ledger-routing.md",
        molecule_id=_MOL,
    )
    assert _headers(consumer)[0] == compute_source_hash([fragment])
