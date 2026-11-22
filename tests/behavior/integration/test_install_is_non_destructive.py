"""Every behavior-harness abort leaves tracked files byte-unchanged (T041, FR-006, FR-019).

Each of the documented failure exit codes MUST leave `.spaex/constitution.md`,
`.spaex/constitution.d/`, `.spaex/decisions.json` and the legacy
`.spaex/clarifications.json` byte-identical to their pre-install snapshot:

- 20: intra-molecule Case A (mechanical pre-check refuse)
- 21: a finding nobody can answer (no operator on a non-interactive terminal)
- 22: project-local additive-only refuse
- 30: check timeout
- 31: check runtime error
- 32: check invalid output
- 33: check quota
- 34: check no-runtime

Each test seeds a successful first install (fragment set materialized,
`.spaex/constitution.md` composed, `.spaex/decisions.json` written, a legacy
`.spaex/clarifications.json` planted), snapshots the tracked files, triggers the
specific failure on a second install, and asserts byte-for-byte equality. Exit
22 is exercised through `spaex.behavior.orchestrate.run` directly; the
non-destructive contract lives on `orchestrate.run`, and the same
`_commit_behavior_artifacts` rollback protects tracked files whether the caller
is `spaex install` or a direct orchestrator invocation. A successful install, in
contrast, removes the legacy files of format version 1.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior.composer.failure import (
    ComposerInvalidOutputError,
    ComposerNoRuntimeError,
    ComposerQuotaError,
    ComposerRuntimeError,
    ComposerTimeoutError,
)
from spaex.behavior.fragment import PROJECT_SCOPE, BehaviorFragment, Modality
from spaex.cli import install as install_cli
from spaex.constitution.resolve import resolve_install_inputs
from spaex.git.cache import clone_dir
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.util import exit_codes
from spaex.util.errors import HaexError

from ..conftest import StubCheck, make_finding

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


_MOL = "com.example.publisher.seeded"
_CANONICAL = "https://example.invalid/example/publisher-t041"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_seed_molecule(tmp_path: Path) -> tuple[str, str, str, Path, Path]:
    """Publish a molecule with two committed revisions.

    HEAD_GOOD carries one valid fragment; HEAD_CASE_A adds a second fragment
    that collides with HEAD_GOOD's under a contradictory modality. Tests that
    need the collision switch the consumer pin to HEAD_CASE_A after seeding.
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
                "molecules": {_MOL: {"path": "seeded", "version": "1.0.0"}},
            },
            indent=2,
        )
    )
    mol_dir = working / "seeded"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"behavior": ["fragments/rule.md"]},
            },
            indent=2,
        )
    )
    (mol_dir / "fragments").mkdir()
    (mol_dir / "fragments" / "rule.md").write_text(
        "---\n"
        "id: bar\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.strict\n"
        "modality: MUST\n"
        "---\n"
        "**MUST** always run the linter before committing.\n"
    )
    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "seed molecule with one behavior fragment")
    head_good = _git(working, "rev-parse", "HEAD")

    (mol_dir / "fragments" / "rule-lenient.md").write_text(
        "---\n"
        "id: bar\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.lenient\n"
        "modality: SHOULD\n"
        "---\n"
        "**SHOULD** usually run the linter before committing.\n"
    )
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {
                    "behavior": [
                        "fragments/rule.md",
                        "fragments/rule-lenient.md",
                    ],
                },
            },
            indent=2,
        )
    )
    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "introduce Case A collision on same molecule")
    head_case_a = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head_good, head_case_a, state_root, target


def _write_consumer(
    consumer: Path,
    *,
    source: str,
    revision: str,
    local_fragments: list[dict] | None = None,
) -> None:
    consumer.mkdir(exist_ok=True)
    (consumer / ".spaex").mkdir(exist_ok=True)
    manifest: dict = {
        "spaex_version": "4",
        "identity": "com.example.project-consumer",
        "compounds": [
            {
                "source": source,
                "revision": revision,
                "molecules": [_MOL],
            }
        ],
    }
    if local_fragments is not None:
        manifest["constitution"] = {"local_fragments": local_fragments}
    (consumer / ".spaex/manifest.json").write_text(json.dumps(manifest))


def _run_install(
    consumer: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0)
    return install_cli.run(ns)


def _seed_successful_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, str, str, str, Path]:
    """One successful install with the check stubbed; returns (consumer, state_root, ...)."""
    canonical, head_good, head_case_a, state_root, bare_target = (
        _publish_seed_molecule(tmp_path)
    )
    consumer = tmp_path / "consumer"
    _write_consumer(consumer, source=canonical, revision=head_good)

    assert _run_install(consumer, state_root, monkeypatch) == 0

    assert (consumer / ".spaex/constitution.md").exists()
    assert (consumer / ".spaex/decisions.json").exists()
    assert (consumer / ".spaex" / "constitution.d" / _MOL / "bar.md").exists()

    return consumer, state_root, canonical, head_good, head_case_a, bare_target


def _seed_legacy_files(consumer: Path) -> None:
    """Plant the files of format version 1 next to the seed."""
    path = consumer / ".spaex" / "clarifications.json"
    path.write_text(
        json.dumps({"schema_version": 1, "clarifications": {}}, indent=2) + "\n",
        encoding="utf-8",
    )
    (consumer / ".spaex" / ".stale").write_text("left over from an old add\n", encoding="utf-8")


def _invalidate_check_state(consumer: Path) -> None:
    """Change the effective check prompt so the next install must run the check."""
    override = consumer / ".spaex" / "check-prompt.md"
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text(
        "custom check prompt override for this project\n", encoding="utf-8"
    )


def _snapshot_tracked(consumer: Path) -> dict[str, bytes | None]:
    """Read every tracked path FR-006 protects. `None` records absence."""
    snapshot: dict[str, bytes | None] = {}
    for name in ("constitution.md", "decisions.json", "clarifications.json", ".stale"):
        path = consumer / ".spaex" / name
        snapshot[f".spaex/{name}"] = path.read_bytes() if path.exists() else None
    constitution_d = consumer / ".spaex" / "constitution.d"
    if constitution_d.exists():
        for path in sorted(constitution_d.rglob("*")):
            if path.is_file():
                rel = str(path.relative_to(consumer))
                snapshot[rel] = path.read_bytes()
    return snapshot


def _assert_tracked_unchanged(
    consumer: Path, baseline: dict[str, bytes | None]
) -> None:
    """Compare current tracked-file bytes against the pre-failure snapshot."""
    current = _snapshot_tracked(consumer)
    assert current == baseline, (
        "tracked files diverged after failure:\n"
        f"  baseline keys: {sorted(baseline)}\n"
        f"  current  keys: {sorted(current)}\n"
        f"  diff       : {set(baseline).symmetric_difference(current)}"
    )


def test_exit_20_case_a_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    consumer, state_root, canonical, _head_good, head_case_a, _bare = (
        _seed_successful_install(tmp_path, monkeypatch)
    )
    _seed_legacy_files(consumer)
    baseline = _snapshot_tracked(consumer)
    calls_before = stub_check.calls

    _write_consumer(consumer, source=canonical, revision=head_case_a)

    with pytest.raises(HaexError) as excinfo:
        _run_install(consumer, state_root, monkeypatch)
    assert excinfo.value.exit_code == exit_codes.BEHAVIOR_PRECHECK_REFUSE == 20
    assert stub_check.calls == calls_before, "the check must not run when the pre-check rejects"

    _assert_tracked_unchanged(consumer, baseline)


def test_exit_21_unanswerable_finding_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """A finding with no operator (no TTY under pytest) aborts before anything is written."""
    consumer, state_root, canonical, head_good, *_ = _seed_successful_install(
        tmp_path, monkeypatch
    )
    _seed_legacy_files(consumer)
    baseline = _snapshot_tracked(consumer)

    _write_consumer(
        consumer,
        source=canonical,
        revision=head_good,
        local_fragments=[
            {"id": "extra", "modality": "SHOULD", "body": "**SHOULD** skip the linter."}
        ],
    )
    stub_check.factory = lambda fragments: [
        make_finding(
            fragments,
            "contradiction",
            (f"{_MOL}/bar", 1, 1),
            (f"{PROJECT_SCOPE}/extra", 1, 1),
        )
    ]

    with pytest.raises(HaexError) as excinfo:
        _run_install(consumer, state_root, monkeypatch)
    assert excinfo.value.exit_code == exit_codes.BEHAVIOR_SEMANTIC_REFUSE == 21

    _assert_tracked_unchanged(consumer, baseline)


def test_exit_22_project_local_override_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """Trigger exit 22 through `orchestrate.run` directly (additive-only pre-check)."""
    consumer, state_root, *_ = _seed_successful_install(tmp_path, monkeypatch)
    _seed_legacy_files(consumer)
    baseline = _snapshot_tracked(consumer)
    calls_before = stub_check.calls

    manifest = ConsumerManifest.from_json((consumer / ".spaex/manifest.json").read_bytes())
    _contributions, resolved = resolve_install_inputs(manifest, state_root)

    shadow = BehaviorFragment(
        id="bar",
        kind="constitution_fragment",
        atom_source="project.local",
        modality=Modality.MUST,
        tags=(),
        body="**MUST** override the atom-provided rule.\n",
        molecule_id=PROJECT_SCOPE,
    )

    with pytest.raises(HaexError) as excinfo:
        behavior_orchestrate.run(
            repo_root=consumer,
            state_root=state_root,
            resolved=resolved,
            project_local=(shadow,),
        )
    assert (
        excinfo.value.exit_code
        == exit_codes.BEHAVIOR_PROJECT_LOCAL_REFUSE
        == 22
    )
    assert stub_check.calls == calls_before

    _assert_tracked_unchanged(consumer, baseline)


def _run_seeded_second_install_and_expect_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_check,
    expected_exit_code: int,
) -> None:
    consumer, state_root, *_ = _seed_successful_install(tmp_path, monkeypatch)
    _seed_legacy_files(consumer)
    _invalidate_check_state(consumer)
    baseline = _snapshot_tracked(consumer)

    monkeypatch.setattr(behavior_orchestrate, "check_fragments", failing_check)

    with pytest.raises(HaexError) as excinfo:
        _run_install(consumer, state_root, monkeypatch)
    assert excinfo.value.exit_code == expected_exit_code

    _assert_tracked_unchanged(consumer, baseline)


def test_exit_30_check_timeout_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    def timeout_stub(*args, **kwargs):
        raise ComposerTimeoutError(message="stubbed timeout")

    _run_seeded_second_install_and_expect_exit(
        tmp_path,
        monkeypatch,
        timeout_stub,
        exit_codes.BEHAVIOR_COMPOSER_TIMEOUT,
    )


def test_exit_31_check_runtime_error_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    def runtime_error_stub(*args, **kwargs):
        raise ComposerRuntimeError(message="stubbed runtime error")

    _run_seeded_second_install_and_expect_exit(
        tmp_path,
        monkeypatch,
        runtime_error_stub,
        exit_codes.BEHAVIOR_COMPOSER_RUNTIME_ERROR,
    )


def test_exit_32_check_invalid_output_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    def invalid_output_stub(*args, **kwargs):
        raise ComposerInvalidOutputError(message="stubbed invalid output")

    _run_seeded_second_install_and_expect_exit(
        tmp_path,
        monkeypatch,
        invalid_output_stub,
        exit_codes.BEHAVIOR_COMPOSER_INVALID_OUTPUT,
    )


def test_exit_33_check_quota_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    def quota_stub(*args, **kwargs):
        raise ComposerQuotaError(message="stubbed quota")

    _run_seeded_second_install_and_expect_exit(
        tmp_path,
        monkeypatch,
        quota_stub,
        exit_codes.BEHAVIOR_COMPOSER_QUOTA,
    )


def test_exit_34_check_no_runtime_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    def no_runtime_stub(*args, **kwargs):
        raise ComposerNoRuntimeError(message="stubbed no-runtime")

    _run_seeded_second_install_and_expect_exit(
        tmp_path,
        monkeypatch,
        no_runtime_stub,
        exit_codes.BEHAVIOR_COMPOSER_NO_RUNTIME,
    )


def test_successful_install_removes_the_legacy_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_check: StubCheck
) -> None:
    """Contrast to the failures above: a successful install drops format-1 leftovers."""
    consumer, state_root, *_ = _seed_successful_install(tmp_path, monkeypatch)
    _seed_legacy_files(consumer)
    assert (consumer / ".spaex" / "clarifications.json").exists()

    assert _run_install(consumer, state_root, monkeypatch) == 0

    assert not (consumer / ".spaex" / "clarifications.json").exists()
    assert not (consumer / ".spaex" / ".stale").exists()
    assert (consumer / ".spaex" / "decisions.json").exists()
