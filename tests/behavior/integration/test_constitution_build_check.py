"""`spaex constitution build` / `--force` / `--check` (T058, SC-003; reworked by Spec 030).

- Plain `constitution build` renders the file and runs the check only when no
  completed check covers the current fragments (state in `decisions.json`).
- `--force` reruns the check even when the state matches.
- `--check` (without `--force`) NEVER calls the model: it compares the file
  with a fresh render and the check state, exiting 0 when current and
  non-zero (naming the reason) otherwise.
- `--force --check` performs a fresh check and render and reports by exit code
  whether they match what is committed; it never persists anything.

Fixture setup: a bare-git publisher repo with one molecule and two fragments,
adopted by a consumer via `spaex add`, with the check stubbed (`stub_check`).
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior.decisions import Choice
from spaex.cli import add as add_cli
from spaex.cli.main import main
from spaex.git.cache import clone_dir

from ..conftest import Operator, StubCheck, make_finding

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")

_MOL = "com.example.publisher.build-check"
_CANONICAL = "https://example.invalid/example/publisher-build-check"
_BODY = "**MUST** always route billing calls through the ledger service.\n"
_AUDIT_BODY = "**SHOULD** never route billing calls around the ledger service.\n"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _fragment_text(*, modality: str = "MUST") -> str:
    return (
        "---\nid: ledger-routing\nkind: constitution_fragment\n"
        f"atom_source: pkg.ledger\nmodality: {modality}\n---\n{_BODY}"
    )


def _audit_text() -> str:
    return (
        "---\nid: ledger-audit\nkind: constitution_fragment\n"
        f"atom_source: pkg.audit\nmodality: SHOULD\n---\n{_AUDIT_BODY}"
    )


def _publish_molecule(tmp_path: Path) -> tuple[Path, str, str, Path]:
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
                "molecules": {_MOL: {"path": "build-check", "version": "1.0.0"}},
            },
            indent=2,
        )
    )
    mol_dir = working / "build-check"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"behavior": ["fragments/ledger-routing.md", "fragments/ledger-audit.md"]},
            },
            indent=2,
        )
    )
    (mol_dir / "fragments").mkdir()
    (mol_dir / "fragments" / "ledger-routing.md").write_text(_fragment_text())
    (mol_dir / "fragments" / "ledger-audit.md").write_text(_audit_text())

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "build-check fixture v1")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--bare", "-q", str(working), str(target)], check=True)
    return working, _CANONICAL, head, state_root


def _commit_fragment_change(
    working: Path,
    state_root: Path,
    *,
    modality: str = "MUST",
    body: str = _BODY,
    atom_source: str = "pkg.ledger",
) -> str:
    """Edit the first fragment and refetch (bare-repo pack files are read-only on
    some platforms; refetch instead of re-cloning)."""
    (working / "build-check" / "fragments" / "ledger-routing.md").write_text(
        "---\nid: ledger-routing\nkind: constitution_fragment\n"
        f"atom_source: {atom_source}\nmodality: {modality}\n---\n{body}"
    )
    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", f"build-check fixture v2: {modality}")
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


def _seed_check_artifacts(consumer: Path) -> None:
    """Plant every mutable behavior artifact with sentinel content."""
    spaex_dir = consumer / ".spaex"
    (spaex_dir / "constitution.d").mkdir(parents=True, exist_ok=True)
    (spaex_dir / "constitution.d" / "legacy.md").write_text(
        "legacy constitution fragment\n", encoding="utf-8"
    )
    (spaex_dir / ".constitution.d.staging").mkdir(parents=True, exist_ok=True)
    (spaex_dir / ".constitution.d.staging" / "sentinel").write_text(
        "staging sentinel\n", encoding="utf-8"
    )
    (spaex_dir / ".constitution.d.prev").mkdir(parents=True, exist_ok=True)
    (spaex_dir / ".constitution.d.prev" / "sentinel").write_text(
        "previous sentinel\n", encoding="utf-8"
    )
    (spaex_dir / "clarifications.json").write_text(
        '{"schema_version": 1, "clarifications": {}}\n', encoding="utf-8"
    )
    (spaex_dir / ".stale").write_text("stale sentinel\n", encoding="utf-8")
    (spaex_dir / "composer.log").write_text("composer sentinel\n", encoding="utf-8")


def _snapshot_check_artifacts(consumer: Path) -> dict[str, object]:
    """Read check-managed files and directory contents for byte comparison."""
    roots = (
        ".spaex/constitution.md",
        ".spaex/constitution.d",
        ".spaex/decisions.json",
        ".spaex/clarifications.json",
        ".spaex/.stale",
        ".spaex/.constitution.d.staging",
        ".spaex/.constitution.d.prev",
        ".spaex/composer.log",
    )
    snapshot: dict[str, object] = {}
    for relative in roots:
        path = consumer / relative
        if not path.exists():
            snapshot[relative] = None
        elif path.is_dir():
            snapshot[relative] = {
                str(child.relative_to(path)): child.read_bytes()
                for child in sorted(path.rglob("*"))
                if child.is_file()
            }
        else:
            snapshot[relative] = path.read_bytes()
    return snapshot


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


def _run_constitution_build(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *args: str,
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    return main(["--repo-root", str(consumer), "constitution", "build", *args])


def _install(consumer, state_root, monkeypatch, canonical, head) -> None:
    assert _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head) == 0


def _contradiction(stub: StubCheck) -> None:
    """Make the stubbed check report the two ledger fragments as contradicting."""
    stub.factory = lambda fragments: [
        make_finding(
            fragments,
            "contradiction",
            (f"{_MOL}/ledger-routing", 1, 1),
            (f"{_MOL}/ledger-audit", 1, 1),
        )
    ]


def test_check_reports_current_and_never_calls_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck, capsys
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)
    assert stub_check.calls == 1

    scratch = consumer / ".spaex" / ".constitution.d.staging" / "sentinel"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text("persistent scratch\n", encoding="utf-8")
    capsys.readouterr()

    rc = _run_constitution_build(consumer, state_root, monkeypatch, "--check")
    assert rc == 0
    assert "is current" in capsys.readouterr().out
    assert stub_check.calls == 1, "--check must never call the model"
    assert scratch.read_text(encoding="utf-8") == "persistent scratch\n"


def test_check_reports_out_of_date_without_calling_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck, capsys
) -> None:
    working, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)
    before = (consumer / ".spaex/constitution.md").read_bytes()

    new_head = _commit_fragment_change(working, state_root, modality="SHOULD")
    _bump_consumer_revision(consumer, new_head)
    capsys.readouterr()

    rc = _run_constitution_build(consumer, state_root, monkeypatch, "--check")
    assert rc == 1, "a changed fragment set must report out of date under --check"
    assert "differs from a fresh render" in capsys.readouterr().out
    assert stub_check.calls == 1, "--check must never call the model, even when out of date"
    assert (consumer / ".spaex/constitution.md").read_bytes() == before


def test_check_reports_an_unchecked_fragment_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck, capsys
) -> None:
    """A file that equals the fresh render but whose fragments were never checked."""
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)
    (consumer / ".spaex/decisions.json").unlink()
    capsys.readouterr()

    rc = _run_constitution_build(consumer, state_root, monkeypatch, "--check")
    assert rc == 1
    assert "no completed contradiction check covers these fragments" in capsys.readouterr().out
    assert stub_check.calls == 1


def test_check_reports_a_missing_file_and_a_version_1_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck, capsys
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)
    path = consumer / ".spaex/constitution.md"

    path.write_text(
        '<!-- spaex-composed:source_hash="'
        + "a" * 64
        + '" build_input_hash="'
        + "b" * 64
        + '" version="1" -->\n## MUST\n- x. _[from `m/f`]_\n',
        encoding="utf-8",
    )
    capsys.readouterr()
    assert _run_constitution_build(consumer, state_root, monkeypatch, "--check") == 1
    assert "format version 1" in capsys.readouterr().out

    path.unlink()
    assert _run_constitution_build(consumer, state_root, monkeypatch, "--check") == 1
    assert "is missing" in capsys.readouterr().out
    assert stub_check.calls == 1


def test_plain_build_skips_the_check_when_one_covers_the_fragments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)
    before = (consumer / ".spaex/constitution.md").read_bytes()

    assert _run_constitution_build(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 1, "a plain rebuild must not repeat a completed check"
    assert (consumer / ".spaex/constitution.md").read_bytes() == before


def test_plain_build_rerenders_a_provenance_change_without_a_new_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """The atom source is not part of what the model compares, but it is part of the
    fragment fingerprint in the header: the file changes, the check is not repeated."""
    working, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)
    before = (consumer / ".spaex/constitution.md").read_text()

    new_head = _commit_fragment_change(working, state_root, atom_source="pkg.ledger-renamed")
    _bump_consumer_revision(consumer, new_head)
    assert _run_constitution_build(consumer, state_root, monkeypatch, "--check") == 1

    assert _run_constitution_build(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 1
    after = (consumer / ".spaex/constitution.md").read_text()
    assert after != before
    assert after.split("\n", 1)[1] == before.split("\n", 1)[1], "only the header hash changes"
    assert _run_constitution_build(consumer, state_root, monkeypatch, "--check") == 0


def test_plain_build_checks_again_when_the_modality_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """The declared modality is part of what the model compares, so it is checked again."""
    working, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)

    new_head = _commit_fragment_change(working, state_root, modality="SHOULD")
    _bump_consumer_revision(consumer, new_head)

    assert _run_constitution_build(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 2
    text = (consumer / ".spaex/constitution.md").read_text()
    assert f'<!-- spaex-fragment id="{_MOL}/ledger-routing" modality="SHOULD" -->' in text
    assert _run_constitution_build(consumer, state_root, monkeypatch, "--check") == 0


def test_plain_build_checks_again_when_a_body_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    working, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)

    new_head = _commit_fragment_change(
        working, state_root, body="**MUST** route billing through the ledger and log it.\n"
    )
    _bump_consumer_revision(consumer, new_head)

    assert _run_constitution_build(consumer, state_root, monkeypatch) == 0
    assert stub_check.calls == 2
    assert "log it" in (consumer / ".spaex/constitution.md").read_text()
    assert _run_constitution_build(consumer, state_root, monkeypatch, "--check") == 0
    assert stub_check.calls == 2


def test_force_checks_again_even_when_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)
    assert stub_check.calls == 1

    assert _run_constitution_build(consumer, state_root, monkeypatch, "--force") == 0
    assert stub_check.calls == 2, "--force must run the check even when the state matches"


def test_force_check_matches_when_nothing_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)
    before = (consumer / ".spaex/constitution.md").read_bytes()
    _seed_check_artifacts(consumer)
    artifacts_before = _snapshot_check_artifacts(consumer)

    rc = _run_constitution_build(consumer, state_root, monkeypatch, "--force", "--check")
    assert rc == 0, "a fresh check that finds nothing reproduces the committed file"
    assert stub_check.calls == 2, "--force --check must run the check for real"
    assert (consumer / ".spaex/constitution.md").read_bytes() == before
    assert _snapshot_check_artifacts(consumer) == artifacts_before


def test_force_check_reports_drift_when_a_fresh_check_finds_something(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_check: StubCheck,
    operator: Operator,
) -> None:
    """The committed file has no exclusion; a fresh check reports a contradiction and the
    operator keeps one passage, so the fresh render differs. Nothing is persisted."""
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)
    before = (consumer / ".spaex/constitution.md").read_bytes()
    _seed_check_artifacts(consumer)
    artifacts_before = _snapshot_check_artifacts(consumer)

    _contradiction(stub_check)
    operator.default = Choice(kind="keep", kept=0)
    rc = _run_constitution_build(consumer, state_root, monkeypatch, "--force", "--check")
    assert rc == 1, "drift between the fresh result and the committed file is reported"
    assert len(operator.asked) == 1
    assert (consumer / ".spaex/constitution.md").read_bytes() == before, (
        "--check must never persist a rebuild, even combined with --force"
    )
    assert _snapshot_check_artifacts(consumer) == artifacts_before


def test_force_check_refuses_to_decide_without_an_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """Without the `operator` stand-in the real prompt runs and refuses on a non-TTY."""
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    _install(consumer, state_root, monkeypatch, canonical, head)
    _seed_check_artifacts(consumer)
    artifacts_before = _snapshot_check_artifacts(consumer)

    _contradiction(stub_check)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    rc = _run_constitution_build(consumer, state_root, monkeypatch, "--force", "--check")
    assert rc == 21
    assert _snapshot_check_artifacts(consumer) == artifacts_before
