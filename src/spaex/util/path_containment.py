"""Canonicalise-and-contain helper for hook-script targets (Spec 016).

The install-hook runner materialises a molecule tree via
`spaex.git.molecule_store.get_or_extract()` and then executes a script
under it. Between extraction and execution the script path is joined with
the molecule directory and MUST be canonicalised (symlinks followed, `..`
resolved) and checked against the same directory on every invocation,
including cache hits (Spec 016 FR-014 / FR-015). Archive-time validation
does not establish this execution-time boundary: a committed
`mol/install.py -> ../sibling/install.py` can pass the archive check but
resolve outside the returned molecule directory after publication.
"""

from __future__ import annotations

from pathlib import Path


class PathEscapeError(Exception):
    """Canonical target escapes its containment root or is unresolvable."""


def canonicalise_within(root: Path, candidate: Path) -> Path:
    """Return the canonical `candidate` path if it is a strict descendant of `root`.

    Both `root` and `candidate` are resolved with `Path.resolve(strict=True)`
    so intermediate symlinks are followed and `..` segments are normalised.
    A `..` segment that stays inside `root` after resolution is allowed; one
    that would escape raises. A candidate that equals `root` raises: the hook
    target must be a real file below the molecule directory, never the
    directory itself. A broken or unreadable candidate also raises.
    """
    try:
        canonical_root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PathEscapeError(f"root not resolvable: {root}") from exc

    try:
        canonical_candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PathEscapeError(f"candidate not resolvable: {candidate}") from exc

    if canonical_candidate == canonical_root:
        raise PathEscapeError(
            f"candidate equals containment root: {canonical_root}"
        )

    try:
        canonical_candidate.relative_to(canonical_root)
    except ValueError as exc:
        raise PathEscapeError(
            f"candidate {canonical_candidate} escapes root {canonical_root}"
        ) from exc

    return canonical_candidate
