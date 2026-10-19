"""Add-time singleton-category pre-check for `spaex add` (Spec 013 FR-019, FR-020).

A repository adopts at most one workflow molecule and at most one
constitution-contributing molecule. `spaex add` refuses before it writes
anything when the molecules a compound will hold after the add would break
either rule.
"""

from __future__ import annotations

from pathlib import Path

from spaex.git import show as git_show
from spaex.git.cache import clone_dir
from spaex.model.atom_category import LEGACY_CONSTITUTION_CATEGORY
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.model.molecule_manifest import MoleculeManifest
from spaex.model.publisher_manifest import PublisherManifest
from spaex.util.errors import (
    ConstitutionAlreadyAdoptedError,
    HaexError,
    PublisherManifestInvalidError,
    WorkflowMoleculeAlreadyAdoptedError,
)

_WORKFLOW_CATEGORY = "workflow"


def _load_molecule_manifest(
    repo_dir: Path, sha: str, molecule_dir_path: str, molecule_id: str
) -> MoleculeManifest:
    molecule_bytes = git_show.show_bytes(
        repo_dir,
        sha,
        f"{molecule_dir_path}/manifest.json",
        not_found_error=PublisherManifestInvalidError,
    )
    try:
        return MoleculeManifest.from_json(molecule_bytes)
    except (ValueError, KeyError) as exc:
        raise PublisherManifestInvalidError(
            message=(
                f"molecule manifest for {molecule_id!r} at "
                f"{molecule_dir_path}/manifest.json is invalid: {exc}"
            ),
            context={"molecule_id": molecule_id, "path": molecule_dir_path},
        ) from exc


def _categories_declared_by(
    molecule_ids: tuple[str, ...],
    publisher: PublisherManifest,
    repo_dir: Path,
    sha: str,
) -> dict[str, tuple[str, ...]]:
    """Return {category: (molecule_ids that declare it)} for ``molecule_ids``."""
    result: dict[str, list[str]] = {}
    for mid in molecule_ids:
        entry = publisher.molecules[mid]
        molecule = _load_molecule_manifest(repo_dir, sha, entry.path, mid)
        for category, paths in molecule.atoms.items():
            if paths:
                result.setdefault(category, []).append(mid)
    return {k: tuple(v) for k, v in result.items()}


def _existing_category_owners(
    manifest: ConsumerManifest,
    state_root: Path,
    category: str,
) -> tuple[str, ...]:
    """Return currently-adopted molecule ids that declare ``category``.

    Reads publisher and molecule manifests from the existing publisher clones.
    A missing clone is treated as "no owner" for this pre-check — install
    itself will surface any clone-availability refusal downstream.
    """
    owners: list[str] = []
    for compound in manifest.compounds:
        repo_dir = clone_dir(state_root, compound.source)
        if not repo_dir.is_dir():
            continue
        try:
            publisher_bytes = git_show.show_bytes(
                repo_dir,
                compound.revision,
                "manifest.json",
                not_found_error=PublisherManifestInvalidError,
            )
            publisher = PublisherManifest.from_json(publisher_bytes)
        except (ValueError, KeyError, HaexError):
            continue
        for mid in compound.molecules:
            entry = publisher.molecules.get(mid)
            if entry is None:
                continue
            try:
                molecule_bytes = git_show.show_bytes(
                    repo_dir,
                    compound.revision,
                    f"{entry.path}/manifest.json",
                    not_found_error=PublisherManifestInvalidError,
                )
                molecule = MoleculeManifest.from_json(molecule_bytes)
            except (ValueError, KeyError, HaexError):
                continue
            if molecule.atoms.get(category):
                owners.append(mid)
    return tuple(owners)


def refuse_singleton_conflict(
    existing_manifest: ConsumerManifest,
    incoming_ids: tuple[str, ...],
    publisher: PublisherManifest,
    repo_dir: Path,
    sha: str,
    state_root: Path,
) -> None:
    """Refuse pre-write when a singleton-category rule is violated.

    ``incoming_ids`` is every molecule the same-source compound will hold after
    the add (added plus carried-over), read at ``sha``; its entries in
    ``existing_manifest`` are therefore not counted as current owners.
    """
    added_category_declarers = _categories_declared_by(incoming_ids, publisher, repo_dir, sha)
    incoming_set = set(incoming_ids)
    for category, refuse_exc in (
        (LEGACY_CONSTITUTION_CATEGORY, ConstitutionAlreadyAdoptedError),
        (_WORKFLOW_CATEGORY, WorkflowMoleculeAlreadyAdoptedError),
    ):
        adding = added_category_declarers.get(category, ())
        if not adding:
            continue
        unique_adding = tuple(sorted(set(adding)))
        if len(unique_adding) > 1:
            raise refuse_exc(
                message=(
                    f"add refuses: category {category!r} would be declared by "
                    f"multiple molecules: {', '.join(unique_adding)}"
                ),
                context={
                    "category": category,
                    "adopted_by": "",
                    "adding": ",".join(unique_adding),
                },
            )
        current_owners = tuple(
            owner
            for owner in _existing_category_owners(existing_manifest, state_root, category)
            if owner not in incoming_set
        )
        if current_owners:
            raise refuse_exc(
                message=(
                    f"add refuses: category {category!r} already adopted by "
                    f"{', '.join(current_owners)}; would-be-added: {', '.join(adding)}"
                ),
                context={
                    "category": category,
                    "adopted_by": ",".join(current_owners),
                    "adding": ",".join(adding),
                },
            )


__all__ = ["refuse_singleton_conflict"]
