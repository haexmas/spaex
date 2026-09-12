"""`spaex constitution build` / `--force` / `--check` (T058, SC-003).

Verifies contracts/cli-surface.md §"spaex constitution build"'s exit-code
and Composer-invocation contract:

- Plain `constitution build` reuses `orchestrate.run()`'s reproducibility
  skip: no Composer call when fingerprints already match, a genuine
  invocation when they don't.
- `--force` reruns the Composer even when fingerprints match.
- `--check` (without `--force`) NEVER invokes the Composer, exiting 0 when
  current and non-zero when stale.
- `--force --check` performs an explicit fresh Composer comparison: it does
  invoke the Composer, and reports via exit code whether the freshly
  composed output matches what was already committed (SC-003
  reproducibility verification).

Fixture setup mirrors test_source_hash_skip.py: a bare-git publisher
repo with one molecule/one fragment, adopted by a consumer via `spaex add`
with a counting Composer stub.
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
from spaex.cli.main import main
from spaex.migrate.transform import clone_dir

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_MOL = "com.example.publisher.build-check"
_CANONICAL = "https://example.invalid/example/publisher-build-check"
_BODY = "**MUST** always route billing calls through the ledger service.\n"


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
                "atoms": {"behavior": ["fragments/ledger-routing.md"]},
            },
            indent=2,
        )
    )
    (mol_dir / "fragments").mkdir()
    (mol_dir / "fragments" / "ledger-routing.md").write_text(_fragment_text())

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "build-check fixture v1")
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
    """Body-unchanged, metadata-only edit so `source_hash` changes without
    a full re-clone (bare-repo pack files are read-only on some
    platforms; refetch instead, matching test_source_hash_skip.py)."""
    (working / "build-check" / "fragments" / "ledger-routing.md").write_text(
        _fragment_text(modality=new_modality)
    )
    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", f"build-check fixture v2: {new_modality}")
    head = _git(working, "rev-parse", "HEAD")

    target = clone_dir(state_root, _CANONICAL)
    _git(target, "fetch", "-q", str(working), "+main:main")
    return head


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


def _bump_consumer_revision(consumer: Path, revision: str) -> None:
    manifest_path = consumer / ".spaex.json"
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


def _run_constitution_build(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *args: str,
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    return main(["--repo-root", str(consumer), "constitution", "build", *args])


class _CountingStub:
    """Counts every Composer invocation; echoes the expected header hashes
    back verbatim (contracts §Shape A) so `emit_composed`'s hash
    verification passes. An optional `variant` seam lets a test simulate a
    non-reproducible rebuild (different bullet phrasing) while still
    satisfying the hash contract, which only depends on fragment identity
    and metadata, never the Composer's exact prose."""

    def __init__(self, *, variant: str = "") -> None:
        self.calls: int = 0
        self._variant = variant

    def __call__(
        self,
        composer_input: ComposerInput,
        *,
        repo_root: Path,
        options: InvokeOptions | None = None,
    ) -> InvokeOutcome:
        self.calls += 1
        data = json.loads(composer_input.to_json())
        header = (
            f'<!-- spaex-composed:source_hash="{data["expected_source_hash"]}" '
            f'build_input_hash="{data["expected_build_input_hash"]}" version="1" -->\n'
            "# spaex Behavior Harness\n\n"
        )
        sections: dict[str, list[str]] = {}
        for fragment in data["fragments"]:
            scoped = f"{fragment['molecule_id']}/{fragment['fragment_id']}"
            text = fragment["body"].strip().replace("**", "").rstrip(".")
            suffix = f" ({self._variant})" if self._variant and self.calls > 1 else ""
            bullet = f"- {text}{suffix}. _[from `{scoped}`]_"
            sections.setdefault(fragment["modality"] or "MUST", []).append(bullet)
        parts = [header]
        for modality in ("MUST", "MUST_NOT", "SHOULD", "SHOULD_NOT", "MAY", "MAY_NOT"):
            bullets = sections.get(modality)
            if not bullets:
                continue
            parts.append(f"## {modality}\n\n" + "\n".join(bullets) + "\n\n")
        body = "".join(parts).rstrip() + "\n"
        return InvokeOutcome(
            result=ComposedShape(body=body),
            runtime=RuntimeDescriptor(kind="stub", identifier="test"),
            raw_output=body,
        )


def test_check_reports_current_and_never_invokes_composer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    stub = _CountingStub()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub.calls == 1

    rc = _run_constitution_build(consumer, state_root, monkeypatch, "--check")
    assert rc == 0
    assert stub.calls == 1, "--check must never invoke the Composer"


def test_check_reports_stale_without_invoking_composer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    stub = _CountingStub()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub.calls == 1
    before = (consumer / ".spaex.md").read_bytes()

    new_head = _commit_modality_change(working, state_root, new_modality="SHOULD")
    _bump_consumer_revision(consumer, new_head)

    rc = _run_constitution_build(consumer, state_root, monkeypatch, "--check")
    assert rc == 1, "a changed fragment set must report stale under --check"
    assert stub.calls == 1, "--check must never invoke the Composer, even when stale"
    assert (consumer / ".spaex.md").read_bytes() == before, (
        "--check must not write .spaex.md"
    )


def test_plain_build_skips_composer_when_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    stub = _CountingStub()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub.calls == 1

    rc = _run_constitution_build(consumer, state_root, monkeypatch)
    assert rc == 0
    assert stub.calls == 1, "a plain rebuild must reuse the reproducibility skip"


def test_plain_build_recomposes_when_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    stub = _CountingStub()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub.calls == 1

    new_head = _commit_modality_change(working, state_root, new_modality="SHOULD")
    _bump_consumer_revision(consumer, new_head)

    rc = _run_constitution_build(consumer, state_root, monkeypatch)
    assert rc == 0
    assert stub.calls == 2
    assert b"## SHOULD" in (consumer / ".spaex.md").read_bytes()

    rc = _run_constitution_build(consumer, state_root, monkeypatch, "--check")
    assert rc == 0
    assert stub.calls == 2


def test_force_rebuilds_even_when_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    stub = _CountingStub()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub.calls == 1

    rc = _run_constitution_build(consumer, state_root, monkeypatch, "--force")
    assert rc == 0
    assert stub.calls == 2, "--force must invoke the Composer even when fingerprints match"


def test_force_check_matches_when_rebuild_is_reproducible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    stub = _CountingStub()
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub.calls == 1
    before = (consumer / ".spaex.md").read_bytes()

    rc = _run_constitution_build(
        consumer, state_root, monkeypatch, "--force", "--check"
    )
    assert rc == 0, "a reproducible rebuild must report a match"
    assert stub.calls == 2, "--force --check must invoke the Composer for real"
    assert (consumer / ".spaex.md").read_bytes() == before


def test_force_check_reports_drift_when_rebuild_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-003 verification: `--force --check` catches a Composer that does
    not reproduce byte-identical output on rebuild, even though the
    fingerprints (fragment identity/metadata) are unchanged."""
    _, canonical, head, state_root = _publish_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)
    stub = _CountingStub(variant="nondeterministic")
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )
    assert stub.calls == 1
    before = (consumer / ".spaex.md").read_bytes()

    rc = _run_constitution_build(
        consumer, state_root, monkeypatch, "--force", "--check"
    )
    assert rc == 1, "drift between the fresh rebuild and the committed file is reported"
    assert stub.calls == 2
    after = (consumer / ".spaex.md").read_bytes()
    assert after != before
    assert b"nondeterministic" in after
