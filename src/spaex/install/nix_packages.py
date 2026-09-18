"""Compose the `nix_packages` category into one generated dependency file (Spec 027).

Multiple molecules may each declare a `nix_packages` fragment — a single
JSON-array-of-strings file listing package identifiers for a shared Nix
devShell. `spaex install`/`spaex remove` merge every *currently resolved*
molecule's fragment deterministically (research.md §2: sorted, deduplicated
union — a plain, order-independent set operation, not the `behavior`-atom
Composer's LLM-based prose merge) into `.spaex/generated/nix-packages.json`,
recomputing the whole file from scratch on every run rather than patching it
incrementally (research.md §4).

The written file's entire content is the bare sorted `packages` array — no
wrapping object. `contributing_molecule_ids` is returned for the caller to
record in install.lock's shared-ownership `paths` entries only; it is never
written to the file itself (an object shape there would break the
`builtins.fromJSON (builtins.readFile ...)` a consuming `flake.nix` uses).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from spaex.constitution.resolve import ResolvedMolecule
from spaex.io import json_deterministic
from spaex.model.atom_category import COMPOSABLE_CATEGORY
from spaex.util.errors import NixPackagesFragmentInvalidError

GENERATED_PACKAGES_PATH = ".spaex/generated/nix-packages.json"


@dataclass(frozen=True)
class PackageFragment:
    """One molecule's contribution toward the composable `nix_packages` category."""

    molecule_id: str
    packages: tuple[str, ...]


@dataclass(frozen=True)
class ComposedFile:
    """The merged result of every active molecule's `PackageFragment`."""

    packages: tuple[str, ...]
    contributing_molecule_ids: tuple[str, ...]

    def to_json_bytes(self) -> bytes:
        """Serialize the file's entire on-disk content: a bare sorted array."""
        return json_deterministic.dumps(list(self.packages))


def collect_package_fragments(
    resolved: Sequence[ResolvedMolecule],
) -> tuple[PackageFragment, ...]:
    """Read every resolved molecule's `nix_packages` fragment, if declared.

    Raises `NixPackagesFragmentInvalidError` (FR-009) when a fragment is not
    a non-empty JSON array of non-empty strings, or when a molecule
    declares more than one file under the category (data-model.md: exactly
    one fragment file per molecule) — aborting for the whole generation,
    not skipping just the offending molecule, so composition never
    silently proceeds without an active molecule's contribution.
    """
    fragments: list[PackageFragment] = []
    for record in sorted(resolved, key=lambda r: r.molecule_id):
        manifest = record.molecule_manifest
        if manifest is None or record.cache_dir is None:
            continue
        rel_paths = manifest.atoms.get(COMPOSABLE_CATEGORY)
        if not rel_paths:
            continue
        if len(rel_paths) != 1:
            raise NixPackagesFragmentInvalidError(
                message=(
                    f"molecule {record.molecule_id!r} declares "
                    f"{len(rel_paths)} nix_packages files; exactly one is required"
                ),
                context={"molecule_id": record.molecule_id},
            )
        fragments.append(
            _parse_fragment(record.molecule_id, record.cache_dir / rel_paths[0])
        )
    return tuple(fragments)


def _parse_fragment(molecule_id: str, path: Path) -> PackageFragment:
    """Parse and validate one molecule's package fragment."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise NixPackagesFragmentInvalidError(
            message=f"molecule {molecule_id!r} nix_packages fragment is not valid JSON: {exc}",
            context={"molecule_id": molecule_id},
        ) from exc
    if (
        not isinstance(data, list)
        or not data
        or not all(isinstance(item, str) and item for item in data)
    ):
        raise NixPackagesFragmentInvalidError(
            message=(
                f"molecule {molecule_id!r} nix_packages fragment must be a "
                "non-empty JSON array of non-empty strings"
            ),
            context={"molecule_id": molecule_id},
        )
    seen: dict[str, None] = {}
    for item in data:
        seen.setdefault(item, None)
    return PackageFragment(molecule_id=molecule_id, packages=tuple(seen))


def compose(fragments: Sequence[PackageFragment]) -> ComposedFile | None:
    """Merge every fragment's packages into one sorted, deduplicated `ComposedFile`.

    Returns `None` when `fragments` is empty (no molecule contributes),
    signaling the caller to omit/delete the generated file entirely
    (FR-006b) rather than publish an empty one.
    """
    if not fragments:
        return None
    package_set: set[str] = set()
    contributor_ids: set[str] = set()
    for fragment in fragments:
        package_set.update(fragment.packages)
        contributor_ids.add(fragment.molecule_id)
    return ComposedFile(
        packages=tuple(sorted(package_set)),
        contributing_molecule_ids=tuple(sorted(contributor_ids)),
    )


__all__ = [
    "GENERATED_PACKAGES_PATH",
    "ComposedFile",
    "PackageFragment",
    "collect_package_fragments",
    "compose",
]
