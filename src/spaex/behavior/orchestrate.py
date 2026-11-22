"""Behavior-harness transaction (Spec 023 T029, reworked by Spec 030).

Runs the whole per-project behavior pipeline inside a single transaction:

1. Build MoleculeInputs from resolved molecules (Spec 016 resolver output).
2. Materialize fragments to a staging tree under `.spaex/.constitution.d.staging/`
   and run the mechanical pre-check (exit 20 / 22 on collision).
3. Load the persisted decisions (`.spaex/decisions.json`) and relate them to the
   fragments (`state.assess`).
4. Run the check (the only model call) when no completed check covers exactly
   these fragments and the effective check prompt, or when forced. Ask the
   operator about every finding that has no valid decision; a refusal or a
   non-interactive terminal aborts with exit 21 before anything is written.
5. Render the constitution with spaex's own code, verify it against the
   fragments, and COMMIT `.spaex/constitution.d/`, `.spaex/constitution.md` and
   `.spaex/decisions.json` in a rollback-safe sequence. Any failure leaves
   tracked files byte-unchanged (FR-019).

The empty fragment set path (FR-017d) removes the composed constitution and the
decisions and clears the staging tree without invoking the model.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from spaex.behavior.ask import OperatorDecision, default_operator_decision
from spaex.behavior.composer.check import check_fragments
from spaex.behavior.composer.failure import ComposerFailureCategory, raise_for
from spaex.behavior.composer.invoke import (
    InvokeOptions,
    resolve_composer_log_path,
    truncate_composer_log,
)
from spaex.behavior.decisions import (
    DECISIONS_FILENAME,
    Checked,
    Decision,
    DecisionStore,
    PassageRef,
    save,
    utc_timestamp,
    valid_decisions,
)
from spaex.behavior.emit import emit_rendered, remove_if_exists
from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.materialize import MoleculeInput, materialize
from spaex.behavior.precheck import PrecheckOutcome
from spaex.behavior.render import RenderError, verify
from spaex.behavior.state import Assessment, assess, expected_text
from spaex.constitution.resolve import ResolvedMolecule
from spaex.git import molecule_store
from spaex.io.transaction import CONSTITUTION_NAME
from spaex.model.molecule_manifest import MoleculeManifest
from spaex.util import exit_codes
from spaex.util.errors import HaexError

SPAEX_DIR = ".spaex"
CONSTITUTION_D_DIRNAME = "constitution.d"
STAGING_DIRNAME = ".constitution.d.staging"
PREV_DIRNAME = ".constitution.d.prev"

#: Files of format version 1 that a version 2 install removes (research R10).
LEGACY_FILENAMES = ("clarifications.json", ".stale")


@dataclass(frozen=True)
class BehaviorOutcome:
    """Result of one orchestration run."""

    fragment_count: int
    published: bool = False
    skipped_check: bool = False
    removed_constitution: bool = False
    decision_count: int = 0
    excluded_count: int = 0
    dedup_provenance: dict[str, tuple[BehaviorFragment, ...]] = field(
        default_factory=dict
    )


def run(
    *,
    repo_root: Path,
    state_root: Path,
    resolved: Sequence[ResolvedMolecule],
    project_local: Sequence[BehaviorFragment] = (),
    invoke_options: InvokeOptions | None = None,
    operator_decision: OperatorDecision | None = None,
    force_check: bool = False,
    spaex_dir: Path | None = None,
    preamble: str = "",
) -> BehaviorOutcome:
    """Execute the behavior-harness transaction for one install.

    Spec 029: ``spaex_dir`` (default `.spaex/`) relocates every behavior
    output for the local pass (`.spaex/local/`), and ``preamble`` is written
    after the composed document's header line.

    Fast-path: no orchestration when no resolved molecule declares
    `atoms.behavior` / inline `constitution_fragments` AND the caller
    supplies no `project_local` fragments. In that case tracked files
    are untouched and no `.spaex/` scratch directories are created,
    keeping the behavior pass invisible to consumers whose molecules
    ship no behavior fragments (FR-017d).

    `operator_decision` answers each finding in place of prompting stdin (test
    seam). `force_check` reruns the check even when a completed one covers the
    current fragments (`spaex constitution build --force`).
    """
    spaex_dir = spaex_dir if spaex_dir is not None else repo_root / SPAEX_DIR
    if not project_local and not _any_declares_behavior(resolved):
        # The install transaction owns `.spaex/constitution.md` for
        # atoms.constitution molecules as well as behavior composition. With
        # the canonical all-in-one `.spaex/` layout, the behavior pass must
        # never remove an artifact it did not produce.
        return BehaviorOutcome(fragment_count=0)

    target = spaex_dir / CONSTITUTION_D_DIRNAME
    staging = spaex_dir / STAGING_DIRNAME
    prev = spaex_dir / PREV_DIRNAME

    _reset_scratch(staging)
    _reset_scratch(prev)

    molecule_inputs = _build_molecule_inputs(resolved, state_root=state_root)

    materialized = materialize(
        molecule_inputs,
        staging_root=staging,
        project_local=tuple(project_local),
    )
    fragments = tuple(m.fragment for m in materialized)

    if not fragments:
        removed = _publish_empty_artifacts(
            repo_root=repo_root,
            spaex_dir=spaex_dir,
            staging=staging,
            target=target,
            prev=prev,
        )
        return BehaviorOutcome(fragment_count=0, removed_constitution=removed)

    dedup_provenance = {
        m.fragment.scoped_id: m.dedup_provenance
        for m in materialized
        if m.dedup_provenance
    }

    try:
        assessment = assess(fragments, repo_root=repo_root, spaex_dir=spaex_dir)
        store = assessment.store
        checked_now = assessment.check_needed or force_check
        if checked_now:
            store = _check_and_decide(
                assessment,
                repo_root=repo_root,
                invoke_options=invoke_options,
                operator_decision=operator_decision or default_operator_decision,
            )
        valid = valid_decisions(store, fragments)
        # Decisions about passages that no longer exist are dropped, not kept around.
        store = replace(store, decisions={d.key: d for d in valid})

        try:
            text = expected_text(fragments, valid, preamble=preamble)
            verify(fragments, valid, text)
        except RenderError as exc:
            if "both keep and exclude" in str(exc):
                raise HaexError(
                    message=f"saved operator decisions conflict: {exc}",
                    diagnostic_key="behavior-clarification-required",
                    exit_code=exit_codes.BEHAVIOR_SEMANTIC_REFUSE,
                    hint="Edit `.spaex/decisions.json` to resolve the conflict, then rerun `spaex install`.",
                ) from exc
            raise_for(
                ComposerFailureCategory.INVALID_OUTPUT,
                f"the rendered constitution does not carry every fragment verbatim: {exc}",
            )
            raise AssertionError("unreachable") from exc
    except BaseException:
        _reset_scratch(staging)
        raise

    _commit_behavior_artifacts(
        repo_root=repo_root,
        spaex_dir=spaex_dir,
        staging=staging,
        target=target,
        prev=prev,
        rendered=text,
        decisions_store=store,
    )
    return BehaviorOutcome(
        fragment_count=len(fragments),
        published=True,
        skipped_check=not checked_now,
        decision_count=len(valid),
        excluded_count=text.count("<!-- spaex-excluded "),
        dedup_provenance=dedup_provenance,
    )


def current_assessment(
    *,
    repo_root: Path,
    state_root: Path,
    resolved: Sequence[ResolvedMolecule],
    project_local: Sequence[BehaviorFragment] = (),
    spaex_dir: Path | None = None,
) -> Assessment | None:
    """Relate the current fragments to the persisted decisions without writing anything.

    Used by `spaex constitution build --check`. Returns `None` when no
    fragment is active (the composed constitution should not exist then).
    """
    spaex_dir = spaex_dir if spaex_dir is not None else repo_root / SPAEX_DIR
    if not project_local and not _any_declares_behavior(resolved):
        return None
    with tempfile.TemporaryDirectory(prefix=".spaex-check-", dir=repo_root) as temp_dir:
        materialized = materialize(
            _build_molecule_inputs(resolved, state_root=state_root),
            staging_root=Path(temp_dir),
            project_local=tuple(project_local),
        )
    fragments = tuple(m.fragment for m in materialized)
    if not fragments:
        return None
    return assess(fragments, repo_root=repo_root, spaex_dir=spaex_dir)


def _check_and_decide(
    assessment: Assessment,
    *,
    repo_root: Path,
    invoke_options: InvokeOptions | None,
    operator_decision: OperatorDecision,
) -> DecisionStore:
    """Run the check, ask about every undecided finding, return the updated store."""
    truncate_composer_log(
        resolve_composer_log_path(invoke_options or InvokeOptions(), repo_root)
    )
    findings = check_fragments(
        assessment.fragments,
        repo_root=repo_root,
        options=invoke_options,
        prompt_text=assessment.prompt_text,
    )
    decided = {decision.key for decision in assessment.valid}
    store = assessment.store
    for finding in sorted(
        findings,
        key=lambda f: (f.passages[0].scoped_id, f.passages[0].start, f.key),
    ):
        if finding.key in decided:
            continue
        asked_at = utc_timestamp()
        choice = operator_decision(finding)
        store = store.with_decision(
            Decision(
                key=finding.key,
                kind=finding.kind,
                summary=finding.summary,
                passages=tuple(
                    PassageRef(p.scoped_id, p.text_hash, p.text) for p in finding.passages
                ),
                choice=choice,
                asked_at=asked_at,
                answered_at=utc_timestamp(),
            )
        )
        decided.add(finding.key)
    return store.with_checked(Checked(assessment.fingerprint, assessment.prompt_hash))


def _publish_empty_artifacts(
    *, repo_root: Path, spaex_dir: Path, staging: Path, target: Path, prev: Path
) -> bool:
    """Commit an empty behavior generation with rollback protection."""
    removed = (spaex_dir / CONSTITUTION_NAME).exists()
    _commit_behavior_artifacts(
        repo_root=repo_root,
        spaex_dir=spaex_dir,
        staging=staging,
        target=target,
        prev=prev,
        remove_spaex_md=True,
    )
    return removed


def _commit_behavior_artifacts(
    *,
    repo_root: Path,
    spaex_dir: Path | None = None,
    staging: Path,
    target: Path,
    prev: Path,
    rendered: str | None = None,
    decisions_store: DecisionStore | None = None,
    remove_spaex_md: bool = False,
) -> None:
    """Publish behavior outputs as one rollback boundary."""
    spaex_dir = spaex_dir if spaex_dir is not None else repo_root / SPAEX_DIR
    spaex_dir.mkdir(parents=True, exist_ok=True)
    spaex_md = spaex_dir / CONSTITUTION_NAME
    decisions_path = spaex_dir / DECISIONS_FILENAME
    legacy_paths = [spaex_dir / name for name in LEGACY_FILENAMES]
    backup_dir = Path(tempfile.mkdtemp(prefix=".behavior-backup-", dir=spaex_dir))
    backups: dict[Path, Path | None] = {}
    for path in (spaex_md, decisions_path, *legacy_paths):
        backup_path = backup_dir / path.name
        if path.exists():
            shutil.copy2(path, backup_path)
            backups[path] = backup_path
        else:
            backups[path] = None

    constitution_published = False
    try:
        _publish_constitution_d(staging=staging, target=target, prev=prev)
        constitution_published = True
        if remove_spaex_md:
            remove_if_exists(repo_root, spaex_md)
            remove_if_exists(repo_root, decisions_path)
            _clear_target(target)
        elif rendered is not None:
            emit_rendered(rendered, target=spaex_md)
            if decisions_store is not None:
                save(decisions_path, decisions_store)
        for legacy in legacy_paths:
            remove_if_exists(repo_root, legacy)
    except BaseException:
        if constitution_published:
            _rollback_constitution_d(target=target, prev=prev)
        for path, backup in backups.items():
            _restore_file(path, backup)
        raise
    else:
        _reset_scratch(prev)
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)


def _restore_file(path: Path, backup: Path | None) -> None:
    """Restore one root-level artifact from its pre-publication snapshot."""
    if os.path.lexists(path):
        path.unlink()
    if backup is not None:
        shutil.copy2(backup, path)


def _build_molecule_inputs(
    resolved: Sequence[ResolvedMolecule], *, state_root: Path
) -> list[MoleculeInput]:
    """Reuse resolver-materialized cache_dirs; fall back to re-extract otherwise.

    Production callers see `cache_dir` and `molecule_manifest` populated by
    `resolve_install_inputs`; test mocks that skip those fields fall through
    to `molecule_store.get_or_extract`, which needs a real publisher clone.
    A molecule declaring neither `atoms.behavior` nor inline
    `constitution_fragments` contributes nothing and is skipped so we do not
    pay for its tree extraction.
    """
    inputs: list[MoleculeInput] = []
    for record in resolved:
        if not record_declares_behavior(record):
            continue
        cache_dir = record.cache_dir
        manifest = record.molecule_manifest
        if cache_dir is None or manifest is None:
            cache_dir = molecule_store.get_or_extract(
                record.repo_dir,
                record.source_url,
                record.revision,
                record.molecule_path,
                state_root,
            )
            manifest = MoleculeManifest.from_json(
                (cache_dir / "manifest.json").read_bytes()
            )
        inputs.append(
            MoleculeInput(
                molecule_id=record.molecule_id,
                manifest=manifest,
                molecule_dir=cache_dir,
            )
        )
    return inputs


def _any_declares_behavior(resolved: Sequence[ResolvedMolecule]) -> bool:
    return any(record_declares_behavior(r) for r in resolved)


def record_declares_behavior(record: ResolvedMolecule) -> bool:
    manifest = record.molecule_manifest
    if manifest is None:
        return False
    if manifest.atoms.get("behavior"):
        return True
    return bool(manifest.constitution_fragments)


def _reset_scratch(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _clear_target(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)


def _publish_constitution_d(*, staging: Path, target: Path, prev: Path) -> None:
    """Swap `constitution.d/` from staging with prev-backup rollback."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if prev.exists():
        shutil.rmtree(prev)
    if target.exists():
        target.rename(prev)
    try:
        staging.rename(target)
    except OSError:
        if prev.exists():
            prev.rename(target)
        raise


def _rollback_constitution_d(*, target: Path, prev: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    if prev.exists():
        prev.rename(target)


__all__ = [
    "BehaviorOutcome",
    "CONSTITUTION_D_DIRNAME",
    "LEGACY_FILENAMES",
    "PREV_DIRNAME",
    "SPAEX_DIR",
    "STAGING_DIRNAME",
    "PrecheckOutcome",
    "current_assessment",
    "run",
]
