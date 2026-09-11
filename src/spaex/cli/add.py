"""`haex add` — adopt one or more molecules from a source repository.

Spec 013 T074 / T075. Reads and mutates ``.spaex.json`` under the
permanent advisory manifest lock, then delegates to ``haex install``
in-process through ``write_and_reinstall``. See
``specs/013-add-cli-and-molecule-rename/contracts/haex-add.cli.md`` for
the full contract.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from spaex.git import publisher_fetch
from spaex.git import show as git_show
from spaex.install.manifest_lock import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    MANIFEST_LOCK_NAME,
    MANIFEST_NAME,
    ManifestLockContext,
    parse_lock_timeout,
)
from spaex.install.write_and_reinstall import write_and_reinstall
from spaex.io.state import default_state_root
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.model.molecule_manifest import MoleculeManifest
from spaex.model.publisher_manifest import PublisherManifest
from spaex.model.source_url import canonicalize
from spaex.util import exit_codes
from spaex.util.errors import (
    ConstitutionAlreadyAdoptedError,
    HaexError,
    InteractiveSelectionUnavailableError,
    MoleculeIdNotInSourceError,
    PublisherManifestInvalidError,
    PublisherManifestMissingError,
    UsageError,
    WorkflowMoleculeAlreadyAdoptedError,
)

_WORKFLOW_CATEGORY = "workflow"
_CONSTITUTION_CATEGORY = "constitution"


def _load_publisher_manifest(repo_dir: Path, sha: str, source: str) -> PublisherManifest:
    """Load the pinned publisher manifest and map failures to typed refusals."""
    # The contract distinguishes:
    #   publisher-manifest-missing -> no manifest.json at the resolved SHA
    #   publisher-manifest-invalid -> present, but non-JSON, wrong schema, or
    #                                 spaex_version != "4"
    try:
        publisher_bytes = git_show.show_bytes(
            repo_dir,
            sha,
            "manifest.json",
            not_found_error=PublisherManifestMissingError,
        )
    except PublisherManifestMissingError as exc:
        raise PublisherManifestMissingError(
            message=f"publisher manifest missing at {source}@{sha[:12]}",
            context={"source": source, "revision": sha},
        ) from exc
    try:
        return PublisherManifest.from_json(publisher_bytes)
    except (ValueError, KeyError) as exc:
        raise PublisherManifestInvalidError(
            message=f"publisher manifest invalid at {source}@{sha[:12]}: {exc}",
            context={"source": source, "revision": sha},
        ) from exc


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


def _select_molecule_ids(
    args: argparse.Namespace,
    publisher: PublisherManifest,
) -> tuple[str, ...]:
    if args.all and args.molecule_ids:
        raise UsageError(
            message="`--all` is mutually exclusive with positional molecule ids"
        )
    if args.all:
        ids = tuple(sorted(publisher.molecules.keys()))
        if not ids:
            raise UsageError(message="publisher molecule selection was empty")
        return ids
    if args.molecule_ids:
        ids = tuple(mid.strip() for mid in args.molecule_ids.split(",") if mid.strip())
        if not ids:
            raise UsageError(message="molecule id list was empty after parsing")
        return ids
    if not sys.stdin.isatty():
        raise InteractiveSelectionUnavailableError(
            message=(
                "no molecule ids given, no --all, and stdin is not a TTY; "
                "cannot prompt interactively"
            ),
            context={"available_molecules": ",".join(sorted(publisher.molecules))},
        )
    return _prompt_interactive(publisher)


def _prompt_interactive(publisher: PublisherManifest) -> tuple[str, ...]:
    available = sorted(publisher.molecules)
    sys.stdout.write(f"Available molecules at {publisher.publisher}:\n")
    for index, mid in enumerate(available, start=1):
        sys.stdout.write(f"  [{index}] {mid}\n")
    sys.stdout.write(
        "Enter comma-separated ids or numeric indexes (e.g. '1,3' or 'com.a.b'): "
    )
    sys.stdout.flush()
    raw = sys.stdin.readline().strip()
    if not raw:
        raise UsageError(message="empty selection")
    selected: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            idx = int(token)
            if idx < 1 or idx > len(available):
                raise UsageError(message=f"index {idx} out of range")
            selected.append(available[idx - 1])
        else:
            selected.append(token)
    if not selected:
        raise UsageError(message="molecule selection was empty after parsing")
    return tuple(selected)


def _verify_ids_in_source(molecule_ids: tuple[str, ...], publisher: PublisherManifest) -> None:
    missing = [mid for mid in molecule_ids if mid not in publisher.molecules]
    if missing:
        raise MoleculeIdNotInSourceError(
            message=(
                f"publisher {publisher.publisher!r} does not declare "
                f"molecule(s): {', '.join(missing)}"
            ),
            context={
                "publisher": publisher.publisher,
                "missing": ",".join(missing),
            },
        )


def _categories_declared_by(
    molecule_ids: tuple[str, ...],
    publisher: PublisherManifest,
    repo_dir: Path,
    sha: str,
) -> dict[str, tuple[str, ...]]:
    """Return {category: (molecule_ids that declare it)} for the added set."""
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
    from spaex.migrate.transform import clone_dir

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


def _refuse_singleton_conflict(
    added_category_declarers: dict[str, tuple[str, ...]],
    existing_manifest: ConsumerManifest,
    state_root: Path,
    added_set: set[str],
    retracted_set: set[str],
) -> None:
    """Refuse pre-write when a singleton-category rule is violated."""
    for category, refuse_exc in (
        (_CONSTITUTION_CATEGORY, ConstitutionAlreadyAdoptedError),
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
            if owner not in added_set and owner not in retracted_set
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


def _mutate_compounds(
    manifest: ConsumerManifest,
    source: str,
    revision: str,
    added_ids: tuple[str, ...],
) -> ConsumerManifest:
    """Return a new ConsumerManifest with the compound merged/replaced/appended."""
    from spaex.model.consumer_manifest import CompoundEntry

    new_compounds: list[CompoundEntry] = []
    consumed = False
    for compound in manifest.compounds:
        if compound.source == source:
            if compound.revision == revision:
                merged = tuple(sorted(set(compound.molecules) | set(added_ids)))
                new_compounds.append(
                    CompoundEntry(
                        source=source,
                        revision=revision,
                        molecules=merged,
                        track=compound.track,
                        config=compound.config,
                    )
                )
            else:
                new_compounds.append(
                    CompoundEntry(
                        source=source,
                        revision=revision,
                        molecules=tuple(sorted(set(added_ids))),
                        track=compound.track,
                        config={
                            molecule_id: config
                            for molecule_id, config in compound.config.items()
                            if molecule_id in added_ids
                        },
                    )
                )
            consumed = True
        else:
            new_compounds.append(compound)
    if not consumed:
        new_compounds.append(
            CompoundEntry(
                source=source,
                revision=revision,
                molecules=tuple(sorted(set(added_ids))),
            )
        )
    return ConsumerManifest(
        spaex_version=manifest.spaex_version,
        identity=manifest.identity,
        compounds=tuple(new_compounds),
        spaex_min_version=manifest.spaex_min_version,
        groups=manifest.groups,
        active_feature=manifest.active_feature,
        identity_note=manifest.identity_note,
        local_fragments=manifest.local_fragments,
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach `haex add` arguments to ``parser``."""
    parser.add_argument("source_url", help="Publisher repo URL (https:// or ssh://)")
    parser.add_argument(
        "molecule_ids",
        nargs="?",
        default="",
        help="Comma-separated molecule ids to adopt",
    )
    parser.add_argument("--revision", default=None, help="Full 40-hex SHA to pin")
    parser.add_argument("--all", action="store_true", help="Adopt every molecule at the pinned SHA")
    parser.add_argument(
        "--lock-timeout",
        dest="lock_timeout",
        type=parse_lock_timeout,
        default=DEFAULT_LOCK_TIMEOUT_SECONDS,
        help="Manifest-lock timeout in seconds (default 30; 0 = fail-fast)",
    )
    parser.add_argument(
        "--no-install-hooks",
        dest="skip_hooks",
        action="store_true",
        help=(
            "Skip per-molecule install_hook execution during the internal "
            "install triggered by this add. Every molecule declaring "
            "install_hook records hook_status='skipped' in install.lock; "
            "atoms still materialize. Per-invocation only; a later "
            "`spaex install` without this flag runs the hooks (Spec 016 "
            "FR-027)."
        ),
    )


def run(args: argparse.Namespace) -> int:
    """Adopt the requested molecules and reinstall the resulting manifest."""
    repo_root = Path(args.repo_root).resolve()
    state_root = default_state_root()

    manifest_path = repo_root / MANIFEST_NAME
    if not manifest_path.exists():
        raise HaexError(
            message=(
                f"{manifest_path} is missing; create it before running `spaex add`"
            ),
            context={"path": str(manifest_path)},
            diagnostic_key="spaex-json-missing",
            exit_code=exit_codes.INCOMPLETE_TRANSACTION,
            hint="Create a v4 .spaex.json first.",
        )

    lock = ManifestLockContext(
        repo_root / MANIFEST_LOCK_NAME,
        timeout_seconds=args.lock_timeout,
    )
    with lock:
        canonical_source = canonicalize(args.source_url)
        sha = publisher_fetch.resolve_sha(canonical_source, args.revision)
        repo_dir = publisher_fetch.ensure_object(canonical_source, sha, state_root)
        publisher = _load_publisher_manifest(repo_dir, sha, canonical_source)

        molecule_ids = _select_molecule_ids(args, publisher)
        _verify_ids_in_source(molecule_ids, publisher)

        current_manifest = ConsumerManifest.from_json(manifest_path.read_bytes())

        added_category_declarers = _categories_declared_by(
            molecule_ids, publisher, repo_dir, sha
        )
        retracted_set = {
            molecule_id
            for compound in current_manifest.compounds
            if compound.source == canonical_source and compound.revision != sha
            for molecule_id in compound.molecules
        }
        _refuse_singleton_conflict(
            added_category_declarers,
            current_manifest,
            state_root,
            added_set=set(molecule_ids),
            retracted_set=retracted_set,
        )

        new_manifest = _mutate_compounds(
            current_manifest, canonical_source, sha, molecule_ids
        )
        new_bytes = new_manifest.to_json_bytes()

        exit_code = write_and_reinstall(
            repo_root,
            new_bytes,
            lock,
            skip_hooks=bool(getattr(args, "skip_hooks", False)),
        )

        sys.stdout.write(
            f"added {len(molecule_ids)} molecule(s) at {canonical_source}@{sha[:12]}:\n"
        )
        for mid in molecule_ids:
            sys.stdout.write(f"  {mid}\n")
        return exit_code


__all__ = ["add_arguments", "run"]
