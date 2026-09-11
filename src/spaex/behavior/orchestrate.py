"""Behavior-harness transaction (Spec 023 T029).

Runs the whole per-project behavior pipeline inside a single transaction:

1. Build MoleculeInputs from resolved molecules (Spec 016 resolver output).
2. Materialize fragments to a staging tree under `.spaex/.constitution.d.staging/`.
3. Run mechanical pre-check (raises exit 20 / 22 on collision).
4. Compute canonical `source_hash` + `build_input_hash` outside the LLM.
5. Load persisted clarifications; drop invalidated entries.
6. Reproducibility skip (FR-009): if the on-disk `.spaex.md` header already
   carries matching hashes, do not invoke the Composer.
7. Invoke the Composer; parse Shape A or Shape B. Shape B has no operator
   round-trip in the Phase 3 MVP and surfaces as `invalid-output` (Phase 6
   T042 wires the clarification loop).
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
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from spaex.behavior.composer.clarifications import (
    CLARIFICATIONS_FILENAME,
    ClarificationsStore,
    invalidate,
    load,
    save,
)
from spaex.behavior.composer.invoke import (
    ComposedShape,
    ComposerInput,
    InvokeOptions,
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
) -> BehaviorOutcome:
    """Execute the behavior-harness transaction for one install.

    Fast-path: no orchestration when no resolved molecule declares
    `atoms.behavior` / inline `constitution_fragments` AND the caller
    supplies no `project_local` fragments. In that case tracked files
    are untouched and no `.spaex/` scratch directories are created,
    keeping the behavior pass invisible to consumers whose molecules
    ship no fragments (plan.md §Backward compatibility, FR-017d).
    """
    if not project_local and not _any_declares_behavior(resolved):
        return BehaviorOutcome(fragment_count=0)

    spaex_dir = repo_root / SPAEX_DIR
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
        raise HaexError(
            message=(
                "Composer requested clarification but the Phase 3 install path "
                "cannot yet prompt the operator; wire the clarification loop "
                "(Phase 6 T042) or supply the answers via an updated "
                ".spaex/clarifications.json"
            ),
            diagnostic_key="behavior-clarification-required",
            exit_code=exit_codes.BEHAVIOR_SEMANTIC_REFUSE,
            hint=(
                "Rerun after the clarification loop is wired, or drop the "
                "molecule whose fragments trigger the overlap/contradiction."
            ),
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

    return BehaviorOutcome(
        fragment_count=len(canonical_fragments),
        published=True,
        source_hash=emit_outcome.source_hash,
        build_input_hash=emit_outcome.build_input_hash,
        dedup_provenance=dedup_provenance,
    )


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
        backup = backup_dir / path.name
        if path.exists():
            shutil.copy2(path, backup)
            backups[path] = backup
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
    "PREV_DIRNAME",
    "SPAEX_DIR",
    "STAGING_DIRNAME",
    "PrecheckOutcome",
    "run",
]
