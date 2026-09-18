"""Atom-category kind classification (Spec 027 data-model.md GenericAtomCategory).

A molecule's `atoms` map (v4 schema) permits any category key; this module
classifies each key at read time, not at declaration time. `behavior` keeps
its existing specialized handling (Spec 023/026). `skill`/`skills` remain
rejected by the molecule-manifest schema. `constitution` (the pre-Spec-023
legacy category — the file(s) listed there are joined verbatim into
`.spaex/constitution.md` by `spaex.constitution.resolve`/`publish`) keeps
its own, older, entirely separate publication path — it is not a Spec 027
generic atom at all, despite superficially having "just a category key and
some declared paths" the same shape as one. `nix_packages` is the one fixed
composable category (Spec 027 FR-006a): multiple molecules may each
contribute a fragment, merged deterministically rather than refused for
shared ownership. Every other category key is exclusive (Spec 027 FR-001):
single owner per declared path, verbatim delivery.
"""

from __future__ import annotations

BEHAVIOR_CATEGORY = "behavior"
LEGACY_CONSTITUTION_CATEGORY = "constitution"
RESERVED_CATEGORIES = frozenset({"skill", "skills"})
COMPOSABLE_CATEGORY = "nix_packages"

_NON_EXCLUSIVE_CATEGORIES = RESERVED_CATEGORIES | {
    BEHAVIOR_CATEGORY,
    LEGACY_CONSTITUTION_CATEGORY,
    COMPOSABLE_CATEGORY,
}


def is_exclusive(category: str) -> bool:
    """Return whether `category` is materialized as an exclusive generic atom."""
    return category not in _NON_EXCLUSIVE_CATEGORIES


__all__ = [
    "BEHAVIOR_CATEGORY",
    "COMPOSABLE_CATEGORY",
    "LEGACY_CONSTITUTION_CATEGORY",
    "RESERVED_CATEGORIES",
    "is_exclusive",
]
