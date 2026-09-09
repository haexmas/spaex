"""Execute one molecule's install_hook and report its outcome (Spec 016).

The hook runner is invoked by `cli/install.py::run` in effective-priority
order after every atom has been staged into the Spec-008 generation and
before publication (FR-009 through FR-011). Ordering, transaction
rollback, and install.lock hook_status recording all live in the
orchestrator; this module owns the per-hook invocation contract:

* interpreter probing (`shutil.which`), no store call on miss (FR-013 aux);
* on-demand molecule-tree materialization via Spec 017's
  `molecule_store.get_or_extract()`;
* execution-time script-path containment against the returned molecule
  directory on EVERY invocation, including cache hits (FR-014, FR-015);
* subprocess launch with cwd = consumer repo root, complete stdio + env
  inheritance (FR-012, FR-013).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from spaex.constitution.resolve import ResolvedMolecule
from spaex.git import molecule_store
from spaex.util.errors import MoleculeTreeExtractionError, MoleculeTreePathNotFoundError
from spaex.util.path_containment import PathEscapeError, canonicalise_within


class HookOutcomeKind(Enum):
    OK = auto()
    NONZERO_EXIT = auto()
    LAUNCH_FAILURE = auto()
    INTERRUPTED = auto()


@dataclass(frozen=True)
class HookOutcome:
    kind: HookOutcomeKind
    reason: str | None = None
    exit_code: int | None = None


def _launch_failure(reason: str) -> HookOutcome:
    return HookOutcome(kind=HookOutcomeKind.LAUNCH_FAILURE, reason=reason)


def run_install_hook(
    resolved: ResolvedMolecule,
    consumer_repo_root: Path,
    state_root: Path,
) -> HookOutcome:
    """Run one molecule's install_hook. Never raises for hook-domain failures.

    The molecule's `install_hook` MUST be non-None; a caller for a
    hook-less molecule should record the skip itself rather than dispatch
    here. Every failure mode below returns a HookOutcome the orchestrator
    translates into hook_status and (per on_failure policy) transaction
    rollback.
    """
    hook = resolved.install_hook
    assert hook is not None, "run_install_hook requires a molecule with install_hook"

    if shutil.which(hook.interpreter) is None:
        return _launch_failure("interpreter_not_on_path")

    try:
        molecule_dir = molecule_store.get_or_extract(
            resolved.repo_dir,
            resolved.source_url,
            resolved.revision,
            resolved.molecule_path,
            state_root,
        )
    except (MoleculeTreePathNotFoundError, MoleculeTreeExtractionError):
        return _launch_failure("molecule_tree_unavailable")

    try:
        canonical_target = canonicalise_within(molecule_dir, molecule_dir / hook.script)
    except PathEscapeError:
        return _launch_failure("path_containment_failure")

    argv = [hook.interpreter, str(canonical_target), *hook.args]
    try:
        completed = subprocess.run(argv, cwd=consumer_repo_root, check=False)
    except KeyboardInterrupt:
        return HookOutcome(kind=HookOutcomeKind.INTERRUPTED, reason="interrupted")
    except OSError:
        return _launch_failure("process_launch_oserror")

    if completed.returncode == 0:
        return HookOutcome(kind=HookOutcomeKind.OK)
    return HookOutcome(
        kind=HookOutcomeKind.NONZERO_EXIT,
        exit_code=completed.returncode,
    )
