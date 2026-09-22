"""Local-only constitution freshness recomputation (research.md R4, Spec 028)."""

from __future__ import annotations

from pathlib import Path

from spaex.behavior.composer.clarifications import CLARIFICATIONS_FILENAME, invalidate, load
from spaex.behavior.composer.prompt import (
    COMPOSER_PROMPT_VERSION,
    effective_prompt_sha256,
    load_effective_prompt,
)
from spaex.behavior.emit import compute_build_input_hash, compute_source_hash, read_header_hashes
from spaex.behavior.fragment import BehaviorFragment, FragmentValidationError
from spaex.behavior.orchestrate import CONSTITUTION_D_DIRNAME
from spaex.paths import SPAEX_DIRNAME, composed_constitution_path


def check_constitution_staleness(repo_root: Path) -> bool:
    """Whether `.spaex/constitution.md` is stale against its own fragments.

    Recomputes `source_hash`/`build_input_hash` purely from already-
    materialized, git-tracked local files (research.md R4) — the same
    values `spaex constitution build --check` would compute, but without
    its resolve/materialize step, so this never touches the network or the
    local molecule cache. Returns `False` when there are no fragments and
    no composed constitution (nothing to be stale).
    """
    constitution_d = repo_root / SPAEX_DIRNAME / CONSTITUTION_D_DIRNAME
    fragments: list[BehaviorFragment] = []
    if constitution_d.is_dir():
        for scope_dir in sorted(p for p in constitution_d.iterdir() if p.is_dir()):
            for fragment_path in sorted(scope_dir.glob("*.md")):
                try:
                    fragments.append(
                        BehaviorFragment.from_file(fragment_path, molecule_id=scope_dir.name)
                    )
                except (OSError, FragmentValidationError):
                    continue

    if not fragments:
        return composed_constitution_path(repo_root).exists()

    source_hash = compute_source_hash(fragments)
    prompt_hash = effective_prompt_sha256(load_effective_prompt(repo_root))

    clarifications_path = repo_root / SPAEX_DIRNAME / CLARIFICATIONS_FILENAME
    store = load(clarifications_path)
    current_hashes = {f.scoped_id: f.body_hash for f in fragments}
    store, _removed_keys = invalidate(store, current_hashes)

    build_input_hash = compute_build_input_hash(
        effective_prompt_sha256=prompt_hash,
        composer_prompt_version=COMPOSER_PROMPT_VERSION,
        valid_clarifications=store.entries.values(),
    )

    existing = read_header_hashes(repo_root)
    return existing != (source_hash, build_input_hash)
