"""End-to-end `spaex install` with two molecules shipping one fragment each (T030).

Fixture project:
- Two published molecules, each with one `atoms.behavior` fragment.
- Consumer adds both and runs `spaex install`.
- The check (the one model call) is stubbed via `stub_check`; the operator via `operator`.

Verifies:
- `<repo-root>/.spaex/constitution.md` (format version 2) carries both fragment
  bodies verbatim, each in a block naming its scoped id.
- `.spaex/constitution.d/<molecule-id>/<fragment-id>.md` is materialized for
  each molecule (SC-001 acceptance scenario).
- `.spaex/install.lock` records both behavior molecules and the shared
  composed constitution publication path.
- A failing check, or a finding nobody can answer, leaves the tree unchanged.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.render import parse, verify
from spaex.behavior.state import assess
from spaex.cli import add as add_cli
from spaex.cli import install as install_cli
from spaex.git.cache import clone_dir
from spaex.util.errors import HaexError

from ..conftest import StubCheck, make_finding

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


def _run_install(
    consumer: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0)
    return install_cli.run(ns)


_MOLECULES = (
    "com.example.publisher.strict-testing,"
    "com.example.publisher.commit-hygiene"
)
_ID_A = "com.example.publisher.strict-testing/tests-first"
_ID_B = "com.example.publisher.commit-hygiene/small-commits"


def _add_both(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    canonical: str,
    head: str,
) -> None:
    assert (
        _run_add(
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            molecule_ids=_MOLECULES,
            revision=head,
        )
        == 0
    )


def test_install_composes_both_fragments_into_spaex_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    canonical, head, state_root = _publish_two_molecules_with_fragments(tmp_path)
    consumer = _make_consumer(tmp_path)

    _add_both(consumer, state_root, monkeypatch, canonical, head)
    assert _run_install(consumer, state_root, monkeypatch) == 0

    spaex_md = consumer / ".spaex/constitution.md"
    assert spaex_md.exists()
    content = spaex_md.read_text(encoding="utf-8")

    assert "<!-- spaex-composed:" in content
    assert 'version="2"' in content
    document = parse(content)
    assert [block.scoped_id for block in document.blocks] == [_ID_B, _ID_A]
    bodies = {block.scoped_id: block.body for block in document.blocks}
    assert bodies[_ID_A] == "**MUST** run the project's tests before every commit.\n"
    assert bodies[_ID_B] == (
        "**SHOULD** keep every commit focused on a single logical change.\n"
    )
    assert {block.scoped_id: block.modality for block in document.blocks} == {
        _ID_A: "MUST",
        _ID_B: "SHOULD",
    }
    assert "## MUST" not in content, "version 2 has no modality sections"

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

    # The composed file proves itself against the materialized fragments.
    fragments = [
        BehaviorFragment.from_file(frag_a, molecule_id=_ID_A.split("/")[0]),
        BehaviorFragment.from_file(frag_b, molecule_id=_ID_B.split("/")[0]),
    ]
    verify(fragments, [], content)
    assessment = assess(fragments, repo_root=consumer, spaex_dir=consumer / ".spaex")
    assert assessment.check_needed is False

    install_lock = json.loads(
        (consumer / ".spaex" / "install.lock").read_text(encoding="utf-8")
    )
    assert [entry["id"] for entry in install_lock["molecules"]] == [
        "com.example.publisher.commit-hygiene",
        "com.example.publisher.strict-testing",
    ]
    assert all(
        entry["paths"] == [".spaex/constitution.md"]
        for entry in install_lock["molecules"]
    )
    assert all(
        entry["source"] == _CANONICAL and entry["revision"] == head
        for entry in install_lock["molecules"]
    )

    install_lock_bytes = (consumer / ".spaex" / "install.lock").read_bytes()
    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert (consumer / ".spaex" / "install.lock").read_bytes() == install_lock_bytes
    assert stub_check.calls == 1, "adding both molecules checks once; reinstalling does not"


def _add_and_prepare_for_recheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    """Add both molecules, install once, then drop the composed file and the check state.

    A deleted `constitution.md` alone regenerates without a check (decisions.json keeps
    the checked state), so the check state goes too; the next install must check again.
    """
    canonical, head, state_root = _publish_two_molecules_with_fragments(tmp_path)
    consumer = _make_consumer(tmp_path)
    _add_both(consumer, state_root, monkeypatch, canonical, head)
    assert _run_install(consumer, state_root, monkeypatch) == 0
    (consumer / ".spaex/constitution.md").unlink()
    (consumer / ".spaex/decisions.json").unlink()
    return consumer, state_root


def test_install_check_failure_leaves_the_tree_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """A failing check on re-install must not (re-)create `.spaex/constitution.md`."""
    consumer, state_root = _add_and_prepare_for_recheck(tmp_path, monkeypatch)

    class InjectedCheckError(RuntimeError):
        pass

    def failing_check(*_: object, **__: object) -> None:
        raise InjectedCheckError("simulated check failure")

    monkeypatch.setattr(behavior_orchestrate, "check_fragments", failing_check)

    with pytest.raises(InjectedCheckError):
        _run_install(consumer, state_root, monkeypatch)
    assert not (consumer / ".spaex/constitution.md").exists()
    assert not (consumer / ".spaex/decisions.json").exists()


def test_install_finding_without_an_operator_refuses_with_exit_21(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """A finding nobody can answer (no TTY) is a semantic refuse and writes nothing."""
    consumer, state_root = _add_and_prepare_for_recheck(tmp_path, monkeypatch)
    stub_check.factory = lambda fragments: [
        make_finding(fragments, "contradiction", (_ID_A, 1, 1), (_ID_B, 1, 1))
    ]

    with pytest.raises(HaexError) as exc:
        _run_install(consumer, state_root, monkeypatch)
    assert exc.value.exit_code == 21
    assert not (consumer / ".spaex/constitution.md").exists()
    assert not (consumer / ".spaex/decisions.json").exists()
