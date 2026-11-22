"""Reproducibility of `.spaex/constitution.md` (T031, spec 030 T012, SC-002, SC-003, SC-006).

The composed constitution is a pure function of the fragments and the valid
decisions. Installing again, deleting the file, or changing the check prompt
never changes the bytes; the check (the one model call) runs only when no
completed check covers exactly these fragments and the effective check prompt.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior.decisions import DECISIONS_FILENAME
from spaex.behavior.render import parse
from spaex.cli import add as add_cli
from spaex.cli import install as install_cli
from spaex.constitution.resolve import ResolvedMolecule
from spaex.git.cache import clone_dir
from spaex.model.molecule_manifest import MoleculeManifest

from ..conftest import StubCheck

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


_MOL = "com.example.publisher.repro"
_CANONICAL = "https://example.invalid/example/publisher"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_repro_molecule(tmp_path: Path) -> tuple[str, str, Path]:
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
                "molecules": {_MOL: {"path": "repro", "version": "1.0.0"}},
            },
            indent=2,
        )
    )
    mol_dir = working / "repro"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"behavior": ["fragments/a.md", "fragments/b.md"]},
            },
            indent=2,
        )
    )
    (mol_dir / "fragments").mkdir()
    (mol_dir / "fragments" / "a.md").write_text(
        "---\nid: rule-a\nkind: constitution_fragment\n"
        "atom_source: pkg.a\nmodality: MUST\n---\n"
        "**MUST** always do A.\n"
    )
    (mol_dir / "fragments" / "b.md").write_text(
        "---\nid: rule-b\nkind: constitution_fragment\n"
        "atom_source: pkg.b\nmodality: SHOULD\n---\n"
        "**SHOULD** usually do B.\n"
    )

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "reproducibility fixture")
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


def _constitution(consumer: Path) -> bytes:
    return (consumer / ".spaex/constitution.md").read_bytes()


def _add(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    canonical: str,
    head: str,
) -> None:
    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )


def test_two_installs_yield_byte_identical_spaex_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    canonical, head, state_root = _publish_repro_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    _add(consumer, state_root, monkeypatch, canonical, head)
    first = _constitution(consumer)
    assert stub_check.calls == 1

    assert _run_install(consumer, state_root, monkeypatch) == 0
    second = _constitution(consumer)

    assert first == second, ".spaex/constitution.md must be byte-identical across two installs"
    assert stub_check.calls == 1, (
        "no completed-check state change: the second install must not call the model"
    )


def test_three_installs_are_identical_and_only_the_first_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """SC-002: runs after the first make 0 model calls and change no byte."""
    canonical, head, state_root = _publish_repro_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    _add(consumer, state_root, monkeypatch, canonical, head)
    outputs = [_constitution(consumer)]
    decisions = (consumer / ".spaex" / DECISIONS_FILENAME).read_bytes()
    for _ in range(2):
        assert _run_install(consumer, state_root, monkeypatch) == 0
        outputs.append(_constitution(consumer))

    assert len(set(outputs)) == 1
    assert stub_check.calls == 1
    assert (consumer / ".spaex" / DECISIONS_FILENAME).read_bytes() == decisions


def test_deleted_constitution_regenerates_identically_without_a_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """SC-006: `decisions.json` keeps the checked state, so no model call is needed."""
    canonical, head, state_root = _publish_repro_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    _add(consumer, state_root, monkeypatch, canonical, head)
    first = _constitution(consumer)
    assert stub_check.calls == 1

    (consumer / ".spaex/constitution.md").unlink()
    assert _run_install(consumer, state_root, monkeypatch) == 0

    assert _constitution(consumer) == first
    assert stub_check.calls == 1


def test_check_prompt_override_reruns_the_check_but_not_the_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """A changed check prompt re-runs the check; the header carries no prompt data (FR-003)."""
    canonical, head, state_root = _publish_repro_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    _add(consumer, state_root, monkeypatch, canonical, head)
    first = _constitution(consumer)
    assert stub_check.calls == 1

    (consumer / ".spaex" / "check-prompt.md").write_text(
        "custom check prompt for this project\n", encoding="utf-8"
    )
    assert _run_install(consumer, state_root, monkeypatch) == 0

    assert stub_check.calls == 2
    assert _constitution(consumer) == first
    assert (consumer / ".spaex" / "check-prompt.md").exists()


# --- SC-003: a changed fragment limits the diff to its block and the header ---


def _edit_fragment_in_publisher(tmp_path: Path, state_root: Path, canonical: str) -> str:
    """Commit a new text for fragment `rule-b` in the publisher and return the new HEAD."""
    working = tmp_path / "publisher-working"
    fragment = working / "repro" / "fragments" / "b.md"
    fragment.write_text(
        "---\nid: rule-b\nkind: constitution_fragment\n"
        "atom_source: pkg.b\nmodality: SHOULD\n---\n"
        "**SHOULD** usually do B, and then do C.\n"
    )
    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "edit rule-b")
    head = _git(working, "rev-parse", "HEAD")
    target = clone_dir(state_root, canonical)
    subprocess.run(["git", "-C", str(target), "fetch", "-q", str(working), "main"], check=True)
    return head


def test_changed_fragment_changes_only_its_block_and_the_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    canonical, head, state_root = _publish_repro_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _add(consumer, state_root, monkeypatch, canonical, head)
    before = _constitution(consumer).decode().split("\n")
    assert stub_check.calls == 1

    new_head = _edit_fragment_in_publisher(tmp_path, state_root, canonical)
    # Re-pin the molecule to the new revision through `add` (same molecule, new revision).
    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=new_head)
        == 0
    )
    after = _constitution(consumer).decode().split("\n")
    assert stub_check.calls == 2, "a changed fragment triggers exactly one new check"

    changed = [
        (old, new) for old, new in zip(before, after, strict=False) if old != new
    ]
    assert len(before) == len(after)
    assert changed, "the edited fragment must show up in the output"
    # Header line (fingerprint metadata) and the one changed body line, nothing else.
    assert changed[0][0].startswith("<!-- spaex-composed:")
    assert [new for _, new in changed[1:]] == ["**SHOULD** usually do B, and then do C."]

    blocks = {b.scoped_id: b.body for b in parse("\n".join(after)).blocks}
    assert blocks[f"{_MOL}/rule-a"] == "**MUST** always do A.\n"


# --- Reproducibility for a large fragment set, driving `orchestrate.run` directly ---
#
# `ResolvedMolecule` carries `cache_dir`/`molecule_manifest` as a test seam, so no
# git clone is needed: the property under test does not depend on the resolver.


def _resolved_molecules(cache_root: Path, count: int) -> list[ResolvedMolecule]:
    """Create deterministic resolved molecules without invoking the resolver."""
    resolved = []
    for index in range(count):
        mol_id = f"mol-{index:03d}"
        cache_dir = cache_root / mol_id
        (cache_dir / "fragments").mkdir(parents=True)
        (cache_dir / "fragments" / "rule.md").write_text(
            "---\nid: rule\nkind: constitution_fragment\n"
            f"atom_source: pkg.{mol_id}\nmodality: MUST\n---\n"
            f"do thing {index}.\n",
            encoding="utf-8",
        )
        manifest = MoleculeManifest(
            spaex_version="4",
            id=mol_id,
            version="1.0.0",
            priority=20,
            atoms={"behavior": ("fragments/rule.md",)},
        )
        resolved.append(
            ResolvedMolecule(
                molecule_id=mol_id,
                source_url="https://example.invalid/fixture",
                revision="0" * 40,
                repo_dir=cache_root,
                molecule_path=mol_id,
                install_hook=None,
                effective_priority=20,
                molecule_manifest=manifest,
                cache_dir=cache_dir,
            )
        )
    return resolved


def test_large_set_second_run_skips_the_check(
    tmp_path: Path, stub_check: StubCheck
) -> None:
    repo = tmp_path / "repo"
    (repo / ".spaex").mkdir(parents=True)
    resolved = _resolved_molecules(tmp_path / "cache", 150)

    first = behavior_orchestrate.run(
        repo_root=repo, state_root=tmp_path / "state", resolved=resolved
    )
    assert first.published
    assert not first.skipped_check
    first_body = (repo / ".spaex" / "constitution.md").read_bytes()
    assert stub_check.calls == 1
    assert len(parse(first_body.decode()).blocks) == 150

    second = behavior_orchestrate.run(
        repo_root=repo, state_root=tmp_path / "state", resolved=resolved
    )
    assert second.published
    assert second.skipped_check
    assert stub_check.calls == 1
    assert (repo / ".spaex" / "constitution.md").read_bytes() == first_body


def test_forced_check_is_byte_identical(tmp_path: Path, stub_check: StubCheck) -> None:
    repo = tmp_path / "repo"
    (repo / ".spaex").mkdir(parents=True)
    resolved = _resolved_molecules(tmp_path / "cache", 150)

    behavior_orchestrate.run(repo_root=repo, state_root=tmp_path / "state", resolved=resolved)
    first_body = (repo / ".spaex" / "constitution.md").read_bytes()

    second = behavior_orchestrate.run(
        repo_root=repo,
        state_root=tmp_path / "state",
        resolved=resolved,
        force_check=True,
    )
    assert second.published
    assert not second.skipped_check
    assert stub_check.calls == 2
    assert (repo / ".spaex" / "constitution.md").read_bytes() == first_body, (
        "a forced check on unchanged fragments must not change a byte (SC-002)"
    )


def test_decisions_file_records_the_check_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    canonical, head, state_root = _publish_repro_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _add(consumer, state_root, monkeypatch, canonical, head)

    data = json.loads((consumer / ".spaex" / DECISIONS_FILENAME).read_text())
    assert data["schema_version"] == 1
    assert set(data["checked"]) == {"source_hash", "prompt_hash"}
    assert data["decisions"] == {}
