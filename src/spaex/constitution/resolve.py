"""D11 two-step contribution resolution: PublisherManifest -> PublisherMoleculeEntry
-> MoleculeManifest.

Every molecule-id in every `compounds[].molecules[]` MUST resolve; a molecule
that resolves but does not declare an `atoms.constitution` list is filtered
out silently (it is a non-contribution, not an error). Contributions are
ordered by effective molecule priority, then molecule ID, with paths from the
same molecule retaining publisher declaration order.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from spaex.git import revparse as git_revparse
from spaex.git import show as git_show
from spaex.migrate.transform import clone_dir
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.model.install_lock import ConstitutionSource
from spaex.model.molecule_manifest import MoleculeManifest
from spaex.model.publisher_manifest import PublisherManifest
from spaex.model.source_url import CanonicalSourceUrl
from spaex.util.errors import (
    AtomIdCollisionError,
    ContributionFileNotFoundError,
    MissingAtomManifestError,
    MissingPublisherManifestError,
    PublisherCloneUnavailableError,
)


@dataclass(frozen=True)
class ResolvedConstitutionContribution:
    """A resolved constitution contribution with source metadata and body content."""

    source: ConstitutionSource
    body: bytes


def resolve_constitution_contributions(
    manifest: ConsumerManifest, state_root: Path
) -> list[ResolvedConstitutionContribution]:
    """Resolve constitution contributions from consumer manifest compounds.

    For each compound entry, fetches the publisher manifest and molecule
    manifest from the cloned publisher repo, validates consistency, and
    collects constitution contributions. Molecules that resolve but do not
    declare an `atoms.constitution` list are silently filtered out.

    Args:
        manifest: Consumer manifest containing compound entries with source/revision/molecules.
        state_root: Path to spaex state directory containing publisher clones.

    Returns:
        List of resolved contributions with source metadata and body bytes.

    Raises:
        PublisherCloneUnavailableError: If a publisher clone is not found.
        MissingPublisherManifestError: If publisher manifest is missing or invalid.
        MissingAtomManifestError: If molecule manifest is missing, invalid, or inconsistent.
        AtomIdCollisionError: If a molecule-id resolves to multiple (source, revision) pairs.
        ContributionFileNotFoundError: If a declared contribution file is not found.
    """
    pending: list[tuple[int, str, int, ResolvedConstitutionContribution]] = []
    seen: dict[str, tuple[str, str]] = {}

    for compound_entry in manifest.compounds:
        source = CanonicalSourceUrl.validate(compound_entry.source)
        revision = compound_entry.revision
        repo_dir = clone_dir(state_root, source)
        if not repo_dir.is_dir():
            raise PublisherCloneUnavailableError(
                message=f"no publisher clone found for {source!r}",
                context={"source": source},
            )
        git_revparse.full_sha(repo_dir, revision)

        publisher_bytes = git_show.show_bytes(
            repo_dir,
            revision,
            "manifest.json",
            not_found_error=MissingPublisherManifestError,
        )
        try:
            publisher = PublisherManifest.from_json(publisher_bytes)
        except (ValueError, KeyError) as exc:
            raise MissingPublisherManifestError(
                message=f"publisher manifest at {source!r}@{revision[:12]} is invalid: {exc}",
                context={"source": source, "sha_short": revision[:12]},
            ) from exc

        for molecule_id in compound_entry.molecules:
            key = (source, revision)
            if molecule_id in seen and seen[molecule_id] != key:
                raise AtomIdCollisionError(
                    message=(
                        f"molecule-id {molecule_id!r} resolves to two different "
                        "(source, revision) pairs"
                    ),
                    context={"atom_id": molecule_id},
                )
            seen[molecule_id] = key

            publisher_entry = publisher.molecules.get(molecule_id)
            if publisher_entry is None:
                raise MissingAtomManifestError(
                    message=(
                        f"publisher {publisher.publisher!r} does not declare "
                        f"molecule {molecule_id!r}"
                    ),
                    context={"atom_id": molecule_id, "publisher": publisher.publisher},
                )

            molecule_bytes = git_show.show_bytes(
                repo_dir,
                revision,
                f"{publisher_entry.path}/manifest.json",
                not_found_error=MissingAtomManifestError,
            )
            try:
                molecule_manifest = MoleculeManifest.from_json(molecule_bytes)
            except (ValueError, KeyError) as exc:
                raise MissingAtomManifestError(
                    message=f"molecule manifest for {molecule_id!r} is invalid: {exc}",
                    context={"atom_id": molecule_id},
                ) from exc

            if molecule_manifest.id != molecule_id:
                raise MissingAtomManifestError(
                    message=(
                        f"molecule manifest id {molecule_manifest.id!r} does not match "
                        f"publisher key {molecule_id!r}"
                    ),
                    context={"atom_id": molecule_id, "manifest_id": molecule_manifest.id},
                )
            if molecule_manifest.version != publisher_entry.version:
                raise MissingAtomManifestError(
                    message=(
                        f"molecule {molecule_id!r} version {molecule_manifest.version!r} "
                        f"does not match publisher-declared version {publisher_entry.version!r}"
                    ),
                    context={"atom_id": molecule_id},
                )

            config_entry = compound_entry.config.get(molecule_id)
            effective_priority = molecule_manifest.priority
            if config_entry is not None and config_entry.priority is not None:
                effective_priority = config_entry.priority

            constitution_paths = molecule_manifest.atoms.get("constitution", ())
            for path_index, constitution_path in enumerate(constitution_paths):
                contribution_path = f"{publisher_entry.path}/{constitution_path}"
                body = git_show.show_bytes(
                    repo_dir,
                    revision,
                    contribution_path,
                    not_found_error=ContributionFileNotFoundError,
                )
                contribution = ResolvedConstitutionContribution(
                    source=ConstitutionSource(
                        id=molecule_id, revision=revision, source=source
                    ),
                    body=body,
                )
                pending.append(
                    (effective_priority, molecule_id, path_index, contribution)
                )

    pending.sort(key=lambda item: (item[0], item[1].encode("utf-8"), item[2]))
    return [item[3] for item in pending]
