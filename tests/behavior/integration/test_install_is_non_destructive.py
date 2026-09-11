"""Every behavior-harness abort leaves tracked files byte-unchanged (T041, FR-006).

Each of the eight documented failure exit codes MUST leave `.spaex.md`,
`.spaex/constitution.d/`, and `.spaex/clarifications.json` byte-identical to
their pre-install snapshot:

- 20: intra-molecule Case A (mechanical pre-check refuse)
- 21: cross-molecule Case B (Composer semantic refuse)
- 22: project-local additive-only refuse
- 30: Composer timeout
- 31: Composer runtime error
- 32: Composer invalid output
- 33: Composer quota
- 34: Composer no-runtime

Each test seeds a successful first install (fragment set materialized,
`.spaex.md` composed, `.spaex/clarifications.json` planted), snapshots the
tracked files, triggers the specific failure on a second install, and asserts
byte-for-byte equality. Exit 22 is exercised through
`spaex.behavior.orchestrate.run` directly because the project-local CLI wiring
lands in Phase 7 (T044-T046); the non-destructive contract still lives on
`orchestrate.run`, and the same `_commit_behavior_artifacts` rollback protects
tracked files whether the caller is `spaex install` or a direct orchestrator
invocation.
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
from spaex.behavior.composer.invoke import (
    ClarificationQuestion,
    ComposedShape,
    ComposerInput,
    InvokeOptions,
    InvokeOutcome,
    QuestionsShape,
    RuntimeDescriptor,
)
from spaex.behavior.fragment import PROJECT_SCOPE, BehaviorFragment, Modality
from spaex.cli import install as install_cli
from spaex.constitution.resolve import resolve_install_inputs
from spaex.migrate.transform import clone_dir
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.util import exit_codes
from spaex.util.errors import HaexError

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


def _write_consumer(consumer: Path, *, source: str, revision: str) -> None:
    consumer.mkdir(exist_ok=True)
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
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
        )
    )


def _run_install(
    consumer: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0)
    return install_cli.run(ns)


def _shape_a_stub(
    composer_input: ComposerInput,
    *,
    repo_root: Path,
    options: InvokeOptions | None = None,
) -> InvokeOutcome:
    data = json.loads(composer_input.to_json())
    header = (
        f'<!-- spaex-composed:source_hash="{data["expected_source_hash"]}" '
        f'build_input_hash="{data["expected_build_input_hash"]}" '
        'version="1" -->\n'
        "# spaex Behavior Harness\n"
        "\n"
        "_This file is generated by `spaex install`. Do not edit by hand._\n"
        "_Change fragments in `.spaex/constitution.d/` and re-run install._\n"
        "\n"
        "## MUST\n"
        "\n"
        "- Always run the linter before committing. "
        f'_[from `{_MOL}/bar`]_\n'
    )
    return InvokeOutcome(
        result=ComposedShape(body=header),
        runtime=RuntimeDescriptor(kind="stub", identifier="test"),
        raw_output=header,
    )


def _seed_successful_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, str, str, str, Path]:
    """One successful Shape A install; returns (consumer, state_root, ...)."""
    canonical, head_good, head_case_a, state_root, bare_target = (
        _publish_seed_molecule(tmp_path)
    )
    consumer = tmp_path / "consumer"
    _write_consumer(consumer, source=canonical, revision=head_good)

    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", _shape_a_stub)
    assert _run_install(consumer, state_root, monkeypatch) == 0
    monkeypatch.undo()
    monkeypatch.setenv("SPAEX_STATE", str(state_root))

    assert (consumer / ".spaex.md").exists()
    assert (consumer / ".spaex" / "constitution.d" / _MOL / "bar.md").exists()

    return consumer, state_root, canonical, head_good, head_case_a, bare_target


def _seed_clarifications_json(consumer: Path) -> None:
    """Plant a schema-valid empty clarifications store next to the seed."""
    path = consumer / ".spaex" / "clarifications.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "clarifications": {}}, indent=2) + "\n",
        encoding="utf-8",
    )


def _invalidate_reproducibility_skip(consumer: Path) -> None:
    """Bump `build_input_hash` so the next install must invoke the Composer."""
    override = consumer / ".spaex" / "composer-prompt.md"
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text(
        "custom prompt override for this project\n", encoding="utf-8"
    )


def _snapshot_tracked(consumer: Path) -> dict[str, bytes | None]:
    """Read every tracked path FR-006 protects. `None` records absence."""
    spaex_md = consumer / ".spaex.md"
    constitution_d = consumer / ".spaex" / "constitution.d"
    clarifications = consumer / ".spaex" / "clarifications.json"

    snapshot: dict[str, bytes | None] = {}
    snapshot[".spaex.md"] = spaex_md.read_bytes() if spaex_md.exists() else None
    snapshot[".spaex/clarifications.json"] = (
        clarifications.read_bytes() if clarifications.exists() else None
    )
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer, state_root, canonical, _head_good, head_case_a, _bare = (
        _seed_successful_install(tmp_path, monkeypatch)
    )
    _seed_clarifications_json(consumer)
    baseline = _snapshot_tracked(consumer)

    _write_consumer(consumer, source=canonical, revision=head_case_a)

    def sentinel_composer(*args, **kwargs):
        raise AssertionError(
            "Composer must not run when the mechanical pre-check rejects"
        )

    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", sentinel_composer)

    with pytest.raises(HaexError) as excinfo:
        _run_install(consumer, state_root, monkeypatch)
    assert excinfo.value.exit_code == exit_codes.BEHAVIOR_PRECHECK_REFUSE == 20

    _assert_tracked_unchanged(consumer, baseline)


def test_exit_21_case_b_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer, state_root, *_ = _seed_successful_install(tmp_path, monkeypatch)
    _seed_clarifications_json(consumer)
    _invalidate_reproducibility_skip(consumer)
    baseline = _snapshot_tracked(consumer)

    def shape_b_composer(
        composer_input: ComposerInput,
        *,
        repo_root: Path,
        options: InvokeOptions | None = None,
    ) -> InvokeOutcome:
        return InvokeOutcome(
            result=QuestionsShape(
                questions=(
                    ClarificationQuestion(
                        kind="contradiction",
                        cited_fragments=(
                            {"molecule_id": _MOL, "fragment_id": "bar"},
                        ),
                        question="operator, resolve this contradiction?",
                    ),
                )
            ),
            runtime=RuntimeDescriptor(kind="stub", identifier="test"),
            raw_output="shape-b",
        )

    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", shape_b_composer)

    with pytest.raises(HaexError) as excinfo:
        _run_install(consumer, state_root, monkeypatch)
    assert excinfo.value.exit_code == exit_codes.BEHAVIOR_SEMANTIC_REFUSE == 21

    _assert_tracked_unchanged(consumer, baseline)


def test_exit_22_project_local_override_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Trigger exit 22 through `orchestrate.run` directly.

    Project-local CLI wiring (`.spaex.json` -> `constitution.local_fragments`)
    lands in Phase 7 T044-T046; the additive-only enforcement itself is Phase
    2's `precheck` and Spec 023's non-destructive contract is Phase 5's
    concern.
    """
    consumer, state_root, *_ = _seed_successful_install(tmp_path, monkeypatch)
    _seed_clarifications_json(consumer)
    baseline = _snapshot_tracked(consumer)

    manifest = ConsumerManifest.from_json((consumer / ".spaex.json").read_bytes())
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

    _assert_tracked_unchanged(consumer, baseline)


def _run_seeded_second_install_and_expect_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_factory,
    expected_exit_code: int,
) -> None:
    consumer, state_root, *_ = _seed_successful_install(tmp_path, monkeypatch)
    _seed_clarifications_json(consumer)
    _invalidate_reproducibility_skip(consumer)
    baseline = _snapshot_tracked(consumer)

    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", stub_factory)

    with pytest.raises(HaexError) as excinfo:
        _run_install(consumer, state_root, monkeypatch)
    assert excinfo.value.exit_code == expected_exit_code

    _assert_tracked_unchanged(consumer, baseline)


def test_exit_30_composer_timeout_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout_stub(*args, **kwargs):
        raise ComposerTimeoutError(message="stubbed timeout")

    _run_seeded_second_install_and_expect_exit(
        tmp_path,
        monkeypatch,
        timeout_stub,
        exit_codes.BEHAVIOR_COMPOSER_TIMEOUT,
    )


def test_exit_31_composer_runtime_error_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def runtime_error_stub(*args, **kwargs):
        raise ComposerRuntimeError(message="stubbed runtime error")

    _run_seeded_second_install_and_expect_exit(
        tmp_path,
        monkeypatch,
        runtime_error_stub,
        exit_codes.BEHAVIOR_COMPOSER_RUNTIME_ERROR,
    )


def test_exit_32_composer_invalid_output_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid_output_stub(*args, **kwargs):
        raise ComposerInvalidOutputError(message="stubbed invalid output")

    _run_seeded_second_install_and_expect_exit(
        tmp_path,
        monkeypatch,
        invalid_output_stub,
        exit_codes.BEHAVIOR_COMPOSER_INVALID_OUTPUT,
    )


def test_exit_33_composer_quota_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def quota_stub(*args, **kwargs):
        raise ComposerQuotaError(message="stubbed quota")

    _run_seeded_second_install_and_expect_exit(
        tmp_path,
        monkeypatch,
        quota_stub,
        exit_codes.BEHAVIOR_COMPOSER_QUOTA,
    )


def test_exit_34_composer_no_runtime_leaves_tracked_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_runtime_stub(*args, **kwargs):
        raise ComposerNoRuntimeError(message="stubbed no-runtime")

    _run_seeded_second_install_and_expect_exit(
        tmp_path,
        monkeypatch,
        no_runtime_stub,
        exit_codes.BEHAVIOR_COMPOSER_NO_RUNTIME,
    )
