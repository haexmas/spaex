"""Behavior-harness transaction (Spec 023 T029).

Runs the whole per-project behavior pipeline inside a single transaction:

1. Build MoleculeInputs from resolved molecules (Spec 016 resolver output).
2. Materialize fragments to a staging tree under `.spaex/.constitution.d.staging/`.
3. Run mechanical pre-check (raises exit 20 / 22 on collision).
4. Compute canonical `source_hash` + `build_input_hash` outside the LLM.
5. Load persisted clarifications; drop invalidated entries.
6. Reproducibility skip (FR-009): if the on-disk `.spaex.md` header already
   carries matching hashes, do not invoke the Composer.
7. Invoke the Composer; parse Shape A or Shape B. Shape B triggers one
   bounded operator clarification round-trip (Phase 6 T042): each question
   is answered once, persisted, and the Composer is re-invoked with the
   staged answers. A non-interactive caller or a declined answer surfaces
   as `behavior-clarification-required` (exit 21); a second Shape B
   response in the same build is an `invalid-output` failure (exit 32).
8. Verify hashes on the Composer output.
9. COMMIT: publish `.spaex/constitution.d/`, `.spaex.md`, and
   `.spaex/clarifications.json` in a rollback-safe sequence. Any failure
   leaves tracked files byte-unchanged (FR-006).

The empty fragment set path (FR-017d) removes `.spaex.md` and clears the
staging tree without invoking the Composer.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from spaex.behavior.composer.clarifications import (
    CLARIFICATIONS_FILENAME,
    CitedFragment,
    Clarification,
    ClarificationsStore,
    derive_key,
    invalidate,
    load,
    save,
    utc_timestamp,
)
from spaex.behavior.composer.failure import ComposerFailureCategory, raise_for
from spaex.behavior.composer.invoke import (
    ClarificationQuestion,
    ComposedShape,
    ComposerInput,
    InvokeOptions,
    InvokeOutcome,
    QuestionsShape,
    invoke_composer,
)
from spaex.behavior.composer.prompt import (
    COMPOSER_PROMPT_VERSION,
    effective_prompt_sha256,
    load_effective_prompt,
)
from spaex.behavior.emit import (
    EmitOutcome,
    compute_build_input_hash,
    compute_source_hash,
    emit_composed,
    read_header_hashes,
    remove_if_exists,
)
from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.materialize import MoleculeInput, materialize
from spaex.behavior.precheck import PrecheckOutcome
from spaex.behavior.stale import STALE_FILENAME, clear_stale, write_stale
from spaex.constitution.resolve import ResolvedMolecule
from spaex.git import molecule_store
from spaex.model.molecule_manifest import MoleculeManifest
from spaex.util import exit_codes
from spaex.util.errors import HaexError

SPAEX_DIR = ".spaex"
CONSTITUTION_D_DIRNAME = "constitution.d"
STAGING_DIRNAME = ".constitution.d.staging"
PREV_DIRNAME = ".constitution.d.prev"


@dataclass(frozen=True)
class BehaviorOutcome:
    """Result of one orchestration run."""

    fragment_count: int
    published: bool = False
    skipped_composer: bool = False
    removed_spaex_md: bool = False
    stale: bool = False
    source_hash: str | None = None
    build_input_hash: str | None = None
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
    operator_answer: Callable[[ClarificationQuestion], str] | None = None,
    abort_on_contradiction: bool = True,
    force_composer: bool = False,
) -> BehaviorOutcome:
    """Execute the behavior-harness transaction for one install.

    Fast-path: no orchestration when no resolved molecule declares
    `atoms.behavior` / inline `constitution_fragments` AND the caller
    supplies no `project_local` fragments. In that case tracked files
    are untouched and no `.spaex/` scratch directories are created,
    keeping the behavior pass invisible to consumers whose molecules
    ship no fragments (plan.md §Backward compatibility, FR-017d).

    `operator_answer`, when given, answers each Shape-B clarification
    question in place of prompting stdin (test seam mirroring
    `InvokeOptions.stub_caller`, kept orchestrate-level because the
    round-trip loop lives here, not in the composer subprocess wrapper).
    Defaults to a real stdin prompt that refuses on a non-interactive
    terminal (Phase 6, T042).

    `abort_on_contradiction` (default `True`, `spaex install`'s behavior):
    a Composer Shape B response is resolved via the interactive
    clarification round, aborting with exit 21 on a declined answer
    (FR-005a, FR-010a). Passing `False` (the add-time plausibility check,
    FR-024a) only changes handling of a detected cross-molecule
    *contradiction*: instead of aborting, it prints a WARN with
    provenance, writes `.spaex/.stale` summarizing the finding, and
    returns without committing `.spaex.md` or `.spaex/constitution.d/` —
    the operation completes without aborting and reconciliation is
    deferred to the next `spaex install`. Every other outcome (no
    contradiction, empty fragment set, reproducibility skip) publishes
    normally regardless of `abort_on_contradiction`, exactly as a plain
    `spaex install` would (contracts/cli-surface.md §add/remove: "On no
    contradiction, `.spaex.md` regenerates cleanly").

    `force_composer` (default `False`): when `True`, the reproducibility
    skip (FR-009) is bypassed even when the on-disk `.spaex.md` header
    already matches the freshly computed fingerprints, forcing a real
    Composer invocation. Used by `spaex constitution build --force`
    (contracts/cli-surface.md §"spaex constitution build"); every other
    caller (`spaex install`, the internal install `spaex add`/`spaex
    remove` trigger) leaves this at its default and is unaffected.
    """
    spaex_dir = repo_root / SPAEX_DIR
    if not project_local and not _any_declares_behavior(resolved):
        target = spaex_dir / CONSTITUTION_D_DIRNAME
        if not any(
            path.exists()
            for path in (
                repo_root / ".spaex.md",
                target,
                spaex_dir / STALE_FILENAME,
            )
        ):
            return BehaviorOutcome(fragment_count=0)
        staging = spaex_dir / STAGING_DIRNAME
        prev = spaex_dir / PREV_DIRNAME
        _reset_scratch(staging)
        _reset_scratch(prev)
        staging.mkdir(parents=True, exist_ok=True)
        removed = _publish_empty_artifacts(
            repo_root=repo_root,
            staging=staging,
            target=target,
            prev=prev,
        )
        return BehaviorOutcome(fragment_count=0, removed_spaex_md=removed)

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
            staging=staging,
            target=target,
            prev=prev,
        )
        return BehaviorOutcome(fragment_count=0, removed_spaex_md=removed)

    canonical_fragments = fragments
    dedup_provenance = {
        m.fragment.scoped_id: m.dedup_provenance
        for m in materialized
        if m.dedup_provenance
    }

    source_hash = compute_source_hash(canonical_fragments)
    prompt_text = load_effective_prompt(repo_root)
    prompt_hash = effective_prompt_sha256(prompt_text)

    clarifications_path = spaex_dir / CLARIFICATIONS_FILENAME
    store = load(clarifications_path)
    current_hashes = {f.scoped_id: f.body_hash for f in canonical_fragments}
    store, removed_keys = invalidate(store, current_hashes)

    build_input_hash = compute_build_input_hash(
        effective_prompt_sha256=prompt_hash,
        composer_prompt_version=COMPOSER_PROMPT_VERSION,
        valid_clarifications=store.entries.values(),
    )

    existing = read_header_hashes(repo_root)
    if (
        existing is not None
        and existing == (source_hash, build_input_hash)
        and not removed_keys
        and not force_composer
    ):
        _commit_behavior_artifacts(
            repo_root=repo_root,
            staging=staging,
            target=target,
            prev=prev,
        )
        return BehaviorOutcome(
            fragment_count=len(canonical_fragments),
            published=True,
            skipped_composer=True,
            source_hash=source_hash,
            build_input_hash=build_input_hash,
            dedup_provenance=dedup_provenance,
        )

    composer_input = ComposerInput(
        fragments=canonical_fragments,
        clarifications=tuple(store.entries.values()),
        expected_source_hash=source_hash,
        expected_build_input_hash=build_input_hash,
    )
    invoke_result = invoke_composer(
        composer_input,
        repo_root=repo_root,
        options=invoke_options,
    )

    if isinstance(invoke_result.result, QuestionsShape):
        if not abort_on_contradiction:
            contradictions = tuple(
                question
                for question in invoke_result.result.questions
                if question.kind == "contradiction"
            )
            if contradictions:
                _warn_stale_contradiction(contradictions)
                write_stale(
                    spaex_dir / STALE_FILENAME,
                    contradictions,
                    detected_at=utc_timestamp(),
                )
                _reset_scratch(staging)
                return BehaviorOutcome(
                    fragment_count=len(canonical_fragments),
                    stale=True,
                    source_hash=source_hash,
                    build_input_hash=build_input_hash,
                    dedup_provenance=dedup_provenance,
                )
            _reset_scratch(staging)
            clear_stale(spaex_dir / STALE_FILENAME)
            return BehaviorOutcome(
                fragment_count=len(canonical_fragments),
                source_hash=source_hash,
                build_input_hash=build_input_hash,
                dedup_provenance=dedup_provenance,
            )
        store, build_input_hash, invoke_result = _resolve_clarifications(
            questions=invoke_result.result.questions,
            canonical_fragments=canonical_fragments,
            store=store,
            source_hash=source_hash,
            prompt_hash=prompt_hash,
            repo_root=repo_root,
            invoke_options=invoke_options,
            operator_answer=operator_answer or _default_operator_answer,
        )

    assert isinstance(invoke_result.result, ComposedShape)

    emit_outcome = _commit_behavior_artifacts(
        repo_root=repo_root,
        staging=staging,
        target=target,
        prev=prev,
        composed=invoke_result.result,
        expected_source_hash=source_hash,
        expected_build_input_hash=build_input_hash,
        clarifications_path=clarifications_path,
        clarifications=store,
        save_clarifications=bool(
            removed_keys or _is_clarifications_content_changed(clarifications_path, store)
        ),
    )
    assert emit_outcome is not None

    return BehaviorOutcome(
        fragment_count=len(canonical_fragments),
        published=True,
        source_hash=emit_outcome.source_hash,
        build_input_hash=emit_outcome.build_input_hash,
        dedup_provenance=dedup_provenance,
    )


@dataclass(frozen=True)
class ComputedFingerprints:
    """Current `source_hash`/`build_input_hash` for a resolved fragment set,
    computed without invoking the Composer.

    Both hashes are `None` for the empty-fragment-set case (FR-017d): no
    resolved molecule declares behavior fragments and no project-local
    fragment is configured, matching the state in which `.spaex.md` should
    not exist.
    """

    source_hash: str | None
    build_input_hash: str | None
    fragment_count: int


def compute_fingerprints(
    *,
    repo_root: Path,
    state_root: Path,
    resolved: Sequence[ResolvedMolecule],
    project_local: Sequence[BehaviorFragment] = (),
) -> ComputedFingerprints:
    """Compute the current fingerprints without invoking the Composer.

    Reuses the exact materialization and hashing steps `run()` performs
    before its reproducibility-skip check (module docstring steps 1-5:
    materialize, compute `source_hash`, load the effective prompt, load and
    invalidate clarifications, compute `build_input_hash`). Used by `spaex
    constitution build --check` to compare against the published
    `.spaex.md` header (via `read_header_hashes`) without ever shelling out
    to an LLM (contracts/cli-surface.md: "--check ... MUST NOT invoke the
    Composer").
    """
    spaex_dir = repo_root / SPAEX_DIR
    if not project_local and not _any_declares_behavior(resolved):
        return ComputedFingerprints(None, None, 0)

    with tempfile.TemporaryDirectory(prefix=".spaex-check-", dir=repo_root) as temp_dir:
        staging = Path(temp_dir)
        molecule_inputs = _build_molecule_inputs(resolved, state_root=state_root)
        materialized = materialize(
            molecule_inputs,
            staging_root=staging,
            project_local=tuple(project_local),
        )
    fragments = tuple(m.fragment for m in materialized)
    if not fragments:
        return ComputedFingerprints(None, None, 0)

    source_hash = compute_source_hash(fragments)
    prompt_text = load_effective_prompt(repo_root)
    prompt_hash = effective_prompt_sha256(prompt_text)

    clarifications_path = spaex_dir / CLARIFICATIONS_FILENAME
    store = load(clarifications_path)
    current_hashes = {f.scoped_id: f.body_hash for f in fragments}
    store, _removed_keys = invalidate(store, current_hashes)

    build_input_hash = compute_build_input_hash(
        effective_prompt_sha256=prompt_hash,
        composer_prompt_version=COMPOSER_PROMPT_VERSION,
        valid_clarifications=store.entries.values(),
    )
    return ComputedFingerprints(source_hash, build_input_hash, len(fragments))


def _resolve_clarifications(
    *,
    questions: Sequence[ClarificationQuestion],
    canonical_fragments: Sequence[BehaviorFragment],
    store: ClarificationsStore,
    source_hash: str,
    prompt_hash: str,
    repo_root: Path,
    invoke_options: InvokeOptions | None,
    operator_answer: Callable[[ClarificationQuestion], str],
) -> tuple[ClarificationsStore, str, InvokeOutcome]:
    """Answer each Shape-B question once, persist it, and re-invoke the
    Composer exactly once with the staged clarifications
    (contracts/composer-interface.md §Shape B, FR-010, FR-010a, FR-011).

    A blank answer means the operator declined to reconcile (FR-005a) and
    aborts with the same diagnostic as a non-interactive caller. A second
    Shape B response from the re-invocation is an `invalid-output` failure;
    the round is bounded to one re-invocation per build.
    """
    fragment_by_scoped_id = {f.scoped_id: f for f in canonical_fragments}
    for question in questions:
        cited = _cited_fragments_for_question(question, fragment_by_scoped_id)
        answer = operator_answer(question).strip()
        if not answer:
            raise HaexError(
                message=(
                    "operator declined to reconcile clarification question: "
                    f"{question.question}"
                ),
                diagnostic_key="behavior-clarification-required",
                exit_code=exit_codes.BEHAVIOR_SEMANTIC_REFUSE,
                hint=(
                    "Provide a reconciling answer (choose one modality, merge, "
                    "or reject both), or drop the molecule whose fragments "
                    "trigger the overlap/contradiction."
                ),
            )
        timestamp = utc_timestamp()
        store = store.with_entry(
            Clarification(
                key=derive_key(cited),
                question=question.question,
                cited_fragments=cited,
                answer=answer,
                asked_at=timestamp,
                answered_at=timestamp,
            )
        )

    build_input_hash = compute_build_input_hash(
        effective_prompt_sha256=prompt_hash,
        composer_prompt_version=COMPOSER_PROMPT_VERSION,
        valid_clarifications=store.entries.values(),
    )
    composer_input = ComposerInput(
        fragments=tuple(canonical_fragments),
        clarifications=tuple(store.entries.values()),
        expected_source_hash=source_hash,
        expected_build_input_hash=build_input_hash,
    )
    invoke_result = invoke_composer(
        composer_input,
        repo_root=repo_root,
        options=invoke_options,
    )
    if isinstance(invoke_result.result, QuestionsShape):
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            "Composer returned a second Shape B response in the same build; "
            "the clarification round is bounded to one re-invocation "
            "(contracts/composer-interface.md §Shape B)",
        )
        raise AssertionError("unreachable")

    return store, build_input_hash, invoke_result


def _cited_fragments_for_question(
    question: ClarificationQuestion,
    fragment_by_scoped_id: Mapping[str, BehaviorFragment],
) -> tuple[CitedFragment, ...]:
    """Resolve a Shape-B question's cited fragments to current body hashes."""
    cited: list[CitedFragment] = []
    for entry in question.cited_fragments:
        molecule_id = entry.get("molecule_id", "")
        fragment_id = entry.get("fragment_id", "")
        fragment = fragment_by_scoped_id.get(f"{molecule_id}/{fragment_id}")
        if fragment is None:
            raise_for(
                ComposerFailureCategory.INVALID_OUTPUT,
                "Shape B question cites unknown fragment "
                f"{molecule_id}/{fragment_id}",
            )
            raise AssertionError("unreachable")
        cited.append(
            CitedFragment(
                molecule_id=molecule_id,
                fragment_id=fragment_id,
                body_sha256=fragment.body_hash,
            )
        )
    return tuple(cited)


def _default_operator_answer(question: ClarificationQuestion) -> str:
    """Prompt stdin for one Shape-B answer; refuse on a non-interactive TTY.

    Mirrors `spaex.cli.add._prompt_interactive`'s isatty guard so pytest and
    CI (never a real TTY) fail fast instead of hanging on stdin.
    """
    if not sys.stdin.isatty():
        raise HaexError(
            message=(
                "Composer requested clarification but stdin is not a TTY; "
                "cannot prompt the operator interactively"
            ),
            diagnostic_key="behavior-clarification-required",
            exit_code=exit_codes.BEHAVIOR_SEMANTIC_REFUSE,
            hint=(
                "Rerun `spaex install` from an interactive terminal to answer "
                "the Composer's clarification question, or drop the molecule "
                "whose fragments trigger the overlap/contradiction."
            ),
        )
    sys.stdout.write(f"\nComposer clarification needed ({question.kind}):\n")
    sys.stdout.write(f"  {question.question}\n")
    for cited in question.cited_fragments:
        sys.stdout.write(
            f"    - {cited.get('molecule_id')}/{cited.get('fragment_id')}\n"
        )
    sys.stdout.write("Answer (blank to decline and abort install): ")
    sys.stdout.flush()
    return sys.stdin.readline().strip()


def _warn_stale_contradiction(questions: Sequence[ClarificationQuestion]) -> None:
    """Print the FR-024a WARN naming each contradiction's fragments/molecules."""
    sys.stderr.write(
        "WARN: Composer plausibility check found a cross-molecule semantic "
        "contradiction; `.spaex.md` is left unchanged and marked stale until "
        "reconciled by the next `spaex install` (see `.spaex/.stale`):\n"
    )
    for question in questions:
        provenance = ", ".join(
            f"{cited.get('molecule_id')}/{cited.get('fragment_id')}"
            for cited in question.cited_fragments
        )
        sys.stderr.write(f"WARN:   [{question.kind}] {question.question} ({provenance})\n")
    sys.stderr.flush()


def _publish_empty_artifacts(
    *, repo_root: Path, staging: Path, target: Path, prev: Path
) -> bool:
    """Commit an empty behavior generation with rollback protection."""
    removed = (repo_root / ".spaex.md").exists()
    _commit_behavior_artifacts(
        repo_root=repo_root,
        staging=staging,
        target=target,
        prev=prev,
        remove_spaex_md=True,
    )
    return removed


def _commit_behavior_artifacts(
    *,
    repo_root: Path,
    staging: Path,
    target: Path,
    prev: Path,
    composed: ComposedShape | None = None,
    expected_source_hash: str | None = None,
    expected_build_input_hash: str | None = None,
    clarifications_path: Path | None = None,
    clarifications: ClarificationsStore | None = None,
    save_clarifications: bool = False,
    remove_spaex_md: bool = False,
) -> EmitOutcome | None:
    """Publish behavior outputs as one rollback boundary."""
    spaex_md = repo_root / ".spaex.md"
    backup_dir = Path(tempfile.mkdtemp(prefix=".behavior-backup-", dir=repo_root))
    backups: dict[Path, Path | None] = {}
    for path in (spaex_md, clarifications_path):
        if path is None or path in backups:
            continue
        backup_path = backup_dir / path.name
        if path.exists():
            shutil.copy2(path, backup_path)
            backups[path] = backup_path
        else:
            backups[path] = None

    constitution_published = False
    emit_outcome: EmitOutcome | None = None
    try:
        _publish_constitution_d(staging=staging, target=target, prev=prev)
        constitution_published = True
        if remove_spaex_md:
            remove_if_exists(repo_root)
            _clear_target(target)
        elif composed is not None:
            if expected_source_hash is None or expected_build_input_hash is None:
                raise ValueError("composed publication requires expected hashes")
            emit_outcome = emit_composed(
                composed,
                repo_root=repo_root,
                expected_source_hash=expected_source_hash,
                expected_build_input_hash=expected_build_input_hash,
            )
            assert emit_outcome is not None

        if save_clarifications:
            if clarifications_path is None or clarifications is None:
                raise ValueError("clarifications publication requires a store")
            save(clarifications_path, clarifications)
    except BaseException:
        if constitution_published:
            _rollback_constitution_d(target=target, prev=prev)
        for path, backup in backups.items():
            _restore_file(path, backup)
        raise
    else:
        _reset_scratch(prev)
        # A successful commit means `.spaex.md` (or its absence, for the
        # empty-fragment-set path) now reflects the current fragment set, so
        # any FR-024a stale marker left by a prior `spaex add`/`spaex remove`
        # no longer applies.
        clear_stale(repo_root / SPAEX_DIR / STALE_FILENAME)
        return emit_outcome
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
        if not _record_declares_behavior(record):
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
    return any(_record_declares_behavior(r) for r in resolved)


def _record_declares_behavior(record: ResolvedMolecule) -> bool:
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


def _is_clarifications_content_changed(
    path: Path, store: ClarificationsStore
) -> bool:
    """Best-effort content compare so we do not touch an unchanged file."""
    if not path.exists():
        return bool(store.entries)
    try:
        current = load(path)
    except Exception:  # noqa: BLE001
        return True
    return dict(current.entries) != dict(store.entries)


__all__ = [
    "BehaviorOutcome",
    "CONSTITUTION_D_DIRNAME",
    "ComputedFingerprints",
    "PREV_DIRNAME",
    "SPAEX_DIR",
    "STAGING_DIRNAME",
    "PrecheckOutcome",
    "compute_fingerprints",
    "run",
]
