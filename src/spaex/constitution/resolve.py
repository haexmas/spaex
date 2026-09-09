"""D11 two-step contribution resolution: PublisherManifest -> PublisherMoleculeEntry
-> MoleculeManifest.

Every molecule-id in every `compounds[].molecules[]` MUST resolve; a molecule
that resolves but does not declare an `atoms.constitution` list is filtered
out silently (it is a non-contribution, not an error). Contributions are
ordered by effective molecule priority, then molecule ID, with paths from the
same molecule retaining publisher declaration order.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from spaex.git import revparse as git_revparse
from spaex.git import show as git_show
from spaex.migrate.transform import clone_dir
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.model.install_lock import ConstitutionSource
from spaex.model.molecule_manifest import InstallHook, MoleculeManifest
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


@dataclass(frozen=True)
class ResolvedMolecule:
    """Complete molecule-level resolver record (Spec 016).

    Emitted for EVERY molecule the consumer selects, including molecules
    without an `atoms.constitution` list (hook-only molecules). The hook
    runner consumes this record and asks the Spec 017 molecule store to
    materialize the tree on demand via `repo_dir`, `source_url`,
    `revision`, and `molecule_path`. `repo_dir` is a local execution
    input, never a cache identity or versioned cross-device reference.
    """

    molecule_id: str
    source_url: str
    revision: str
    repo_dir: Path
    molecule_path: str
    install_hook: InstallHook | None
    effective_priority: int


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
    contributions, _ = resolve_install_inputs(manifest, state_root)
    return contributions


def resolve_molecules(
    manifest: ConsumerManifest, state_root: Path
) -> list[ResolvedMolecule]:
    """Resolve every molecule the consumer selects, hook-only molecules included.

    Same publisher / molecule-manifest fetch and cross-check work as
    `resolve_constitution_contributions`, but the returned records carry
    the metadata the install-hook runner needs (repo_dir, molecule_path,
    install_hook, effective_priority) and every selected molecule is
    represented, whether or not it contributes an `atoms.constitution`
    entry. Records are sorted by (effective_priority ascending, molecule_id
    UTF-8 byte order ascending), matching the constitution-assembly rule.
    """
    _, resolved = resolve_install_inputs(manifest, state_root)
    return resolved


def resolve_install_inputs(
    manifest: ConsumerManifest, state_root: Path
) -> tuple[list[ResolvedConstitutionContribution], list[ResolvedMolecule]]:
    """Resolve constitution contributions and molecule records in one pass.

    The shared resolver records contain all manifest metadata needed by both
    consumers. Only contribution bodies are read after the records have been
    collected, so the publisher and molecule manifests are fetched once per
    install invocation.
    """
    records = list(_iterate_resolved_molecules(manifest, state_root))
    pending: list[tuple[int, str, int, ResolvedConstitutionContribution]] = []
    resolved: list[ResolvedMolecule] = []

    for record in records:
        resolved.append(
            ResolvedMolecule(
                molecule_id=record.molecule_id,
                source_url=record.source_url,
                revision=record.revision.lower(),
                repo_dir=record.repo_dir,
                molecule_path=record.publisher_path,
                install_hook=record.molecule_manifest.install_hook,
                effective_priority=record.effective_priority,
            )
        )
        constitution_paths = record.molecule_manifest.atoms.get("constitution", ())
        for path_index, constitution_path in enumerate(constitution_paths):
            contribution_path = f"{record.publisher_path}/{constitution_path}"
            body = git_show.show_bytes(
                record.repo_dir,
                record.revision,
                contribution_path,
                not_found_error=ContributionFileNotFoundError,
            )
            contribution = ResolvedConstitutionContribution(
                source=ConstitutionSource(
                    id=record.molecule_id,
                    revision=record.revision,
                    source=record.source_url,
                ),
                body=body,
            )
            pending.append(
                (record.effective_priority, record.molecule_id, path_index, contribution)
            )

    pending.sort(key=lambda item: (item[0], item[1].encode("utf-8"), item[2]))
    resolved.sort(key=lambda m: (m.effective_priority, m.molecule_id.encode("utf-8")))
    return [item[3] for item in pending], resolved


@dataclass(frozen=True)
class _ResolverRecord:
    """Internal per-molecule tuple shared between the two public resolvers."""

    source_url: str
    revision: str
    repo_dir: Path
    molecule_id: str
    publisher_path: str
    molecule_manifest: MoleculeManifest
    effective_priority: int


def _iterate_resolved_molecules(
    manifest: ConsumerManifest, state_root: Path
) -> Iterator[_ResolverRecord]:
    """Yield one `_ResolverRecord` per selected molecule.

    Performs the D11 two-step lookup, cross-manifest consistency checks,
    and consumer-priority override calculation. Publisher + molecule
    manifests are fetched via git_show; hook and constitution-body reads
    are done by the consumers of this iterator.
    """
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

            yield _ResolverRecord(
                source_url=source,
                revision=revision,
                repo_dir=repo_dir,
                molecule_id=molecule_id,
                publisher_path=publisher_entry.path,
                molecule_manifest=molecule_manifest,
                effective_priority=effective_priority,
            )
