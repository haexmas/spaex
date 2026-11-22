"""Local-only constitution freshness recomputation (research.md R4, Spec 028)."""

from __future__ import annotations

from pathlib import Path

from spaex.behavior.decisions import DecisionsStoreError
from spaex.behavior.fragment import BehaviorFragment, FragmentValidationError
from spaex.behavior.orchestrate import CONSTITUTION_D_DIRNAME
from spaex.behavior.render import RenderError
from spaex.behavior.state import assess, diagnose
from spaex.paths import SPAEX_DIRNAME, composed_constitution_path


def check_constitution_staleness(repo_root: Path) -> bool:
    """Whether `.spaex/constitution.md` is stale against its own fragments.

    Spec 030: renders the expected text purely from the already-materialized,
    git-tracked fragments and decisions (research R4, R12) - the same
    comparison `spaex constitution build --check` makes, without its
    resolve/materialize step, so this never touches the network or the local
    molecule cache. Stale means: the file is missing, is format version 1,
    differs from a fresh render, or no completed contradiction check covers
    these fragments. Returns `False` when there are no fragments and no
    composed constitution (nothing to be stale).
    """
    constitution_d = repo_root / SPAEX_DIRNAME / CONSTITUTION_D_DIRNAME
    fragments: list[BehaviorFragment] = []
    invalid_fragment = False
    if constitution_d.is_dir():
        for scope_dir in sorted(p for p in constitution_d.iterdir() if p.is_dir()):
            for fragment_path in sorted(scope_dir.glob("*.md")):
                try:
                    fragments.append(
                        BehaviorFragment.from_file(fragment_path, molecule_id=scope_dir.name)
                    )
                except (OSError, UnicodeError, FragmentValidationError):
                    invalid_fragment = True

    if invalid_fragment:
        return True

    path = composed_constitution_path(repo_root)
    if not fragments:
        return path.exists()

    try:
        assessment = assess(
            fragments, repo_root=repo_root, spaex_dir=repo_root / SPAEX_DIRNAME
        )
        existing = path.read_bytes().decode("utf-8") if path.exists() else None
        return diagnose(assessment, existing) != "current"
    except (DecisionsStoreError, RenderError):
        return True
