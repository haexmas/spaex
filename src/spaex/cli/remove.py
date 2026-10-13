"""`spaex remove` — retract one or more molecules from `.spaex/manifest.json`.

Spec 013 T085. See ``specs/013-add-cli-and-molecule-rename/contracts/
haex-remove.cli.md`` for the full contract.

Preflight-all-or-nothing: a mixed request `haex remove <present>,<absent>`
refuses at step 2 with `unknown-molecule-id` naming every missing id.
Nothing is written unless every named id is present in at least one
compound's `molecules[]`. Compounds whose `molecules[]` becomes empty
after retraction are dropped. Delete-orphans (Spec 008 US3) removes any
files the retracted molecules had previously contributed.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path
from typing import TypeVar

from spaex.install import local_scope
from spaex.cli.reinstall_options import add_reinstall_arguments, reinstall_kwargs
from spaex.install.manifest_lock import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    ManifestLockContext,
    active_manifest_lock_path,
    parse_lock_timeout,
)
from spaex.install.write_and_reinstall import write_and_reinstall
from spaex.model.consumer_manifest import (
    CompoundEntry,
    ConsumerManifest,
)
from spaex.model.install_lock import InstallLock
from spaex.model.local_manifest import LocalManifest
from spaex.paths import (
    LOCAL_MANIFEST_RELATIVE_PATH,
    MANIFEST_RELATIVE_PATH,
    local_lock_path,
    local_manifest_path,
    manifest_path,
)
from spaex.util import exit_codes
from spaex.util.errors import HaexError, UnknownMoleculeIdError


def _parse_ids(raw: str) -> tuple[str, ...]:
    ids = tuple(mid.strip() for mid in raw.split(",") if mid.strip())
    if not ids:
        raise HaexError(
            message="no molecule ids given",
            diagnostic_key="usage",
            exit_code=exit_codes.USAGE,
        )
    return ids


ManifestT = TypeVar("ManifestT", ConsumerManifest, LocalManifest)


def _adopted_ids(manifest: ConsumerManifest | LocalManifest | None) -> set[str]:
    compounds = manifest.compounds if manifest is not None else ()
    return {mid for compound in compounds for mid in compound.molecules}


def _preflight_ids_present(
    manifest: ConsumerManifest | LocalManifest,
    requested: tuple[str, ...],
    *,
    hint: str | None = None,
) -> None:
    present = _adopted_ids(manifest)
    missing = [mid for mid in requested if mid not in present]
    if missing:
        error = UnknownMoleculeIdError(
            message=(
                "no adopted compound lists the requested molecule id(s): "
                + ", ".join(missing)
            ),
            context={"missing": ",".join(missing)},
        )
        if hint is not None:
            error.hint = hint
        raise error


def _apply_removal(manifest: ManifestT, remove_ids: tuple[str, ...]) -> ManifestT:
    """Return a manifest without the requested molecules or empty compounds."""
    removal_set = set(remove_ids)
    new_compounds: list[CompoundEntry] = []
    for compound in manifest.compounds:
        kept = tuple(mid for mid in compound.molecules if mid not in removal_set)
        if not kept:
            continue
        if kept == compound.molecules:
            new_compounds.append(compound)
            continue
        new_config = {
            mid: entry for mid, entry in compound.config.items() if mid in kept
        }
        new_compounds.append(
            CompoundEntry(
                source=compound.source,
                revision=compound.revision,
                molecules=kept,
                track=compound.track,
                config=new_config,
            )
        )
    # replace() keeps every other top-level field, e.g. skill_installation.
    return dataclasses.replace(manifest, compounds=tuple(new_compounds))


def _warn_external_carriers(
    repo_root: Path, remove_ids: tuple[str, ...], lock_path: Path | None = None
) -> None:
    """Warn when removed molecules left hook or external Spec Kit artifacts."""
    lock_path = lock_path or repo_root / ".spaex" / "install.lock"
    if not lock_path.exists():
        return
    lock = InstallLock.from_json(lock_path.read_bytes())
    carriers = {
        m.id
        for m in lock.molecules
        if m.hook_status is not None or m.speckit is not None
    }
    for mid in remove_ids:
        record = next((m for m in lock.molecules if m.id == mid), None)
        if record is not None and record.hook_status is not None:
            sys.stderr.write(
                f"WARN: molecule {mid} had an install_hook; side effects "
                "(git hooks, gitignore entries, provisioned tools, "
                "agent-harness registrations) may remain. Consult the "
                "molecule's README for reverse steps.\n"
            )
        if (
            mid in carriers
            and record is not None
            and record.speckit is not None
            and record.speckit.selected
        ):
            sys.stderr.write(
                f"WARN: molecule {mid} installed external Spec Kit integrations; "
                "agent skill files may remain after removal and are not "
                "automatically uninstalled.\n"
            )
    sys.stderr.flush()


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach `haex remove` arguments to ``parser``."""
    parser.add_argument(
        "molecule_ids",
        help="Comma-separated reverse-DNS molecule ids to retract",
    )
    parser.add_argument(
        "--lock-timeout",
        dest="lock_timeout",
        type=parse_lock_timeout,
        default=DEFAULT_LOCK_TIMEOUT_SECONDS,
        help="Manifest-lock timeout in seconds (default 30; 0 = fail-fast)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Retract molecules adopted for this checkout only (Spec 029).",
    )
    add_reinstall_arguments(parser, command="remove")


def _remove_local(
    args: argparse.Namespace,
    repo_root: Path,
    lock: ManifestLockContext,
    remove_ids: tuple[str, ...],
) -> int:
    """Spec 029: retract from the local overlay; the project manifest is never written."""
    overlay = local_scope.load_overlay(repo_root) or LocalManifest(
        spaex_version="4", compounds=()
    )
    _preflight_ids_present(
        overlay,
        remove_ids,
        hint=f"The molecule id is not adopted in `{LOCAL_MANIFEST_RELATIVE_PATH}`.",
    )
    _warn_external_carriers(repo_root, remove_ids, local_lock_path(repo_root))
    exit_code = write_and_reinstall(
        repo_root,
        _apply_removal(overlay, remove_ids).to_json_bytes(),
        lock,
        **reinstall_kwargs(args),
        abort_on_behavior_contradiction=False,
        target=local_manifest_path(repo_root),
    )
    sys.stdout.write(f"retracted {len(remove_ids)} local molecule(s):\n")
    for mid in remove_ids:
        sys.stdout.write(f"  {mid}\n")
    return exit_code


def run(args: argparse.Namespace) -> int:
    """Retract requested molecules and reinstall the resulting manifest."""
    repo_root = Path(args.repo_root).resolve()
    path = manifest_path(repo_root)
    if not path.exists():
        raise HaexError(
            message=f"{path} is missing",
            context={"path": str(path)},
            diagnostic_key="spaex-json-missing",
            exit_code=exit_codes.INCOMPLETE_TRANSACTION,
            hint="Nothing to retract; there is no consumer manifest here.",
        )

    # A molecule is removed once even if the operator repeats its ID.
    remove_ids = tuple(dict.fromkeys(_parse_ids(args.molecule_ids)))

    lock = ManifestLockContext(
        active_manifest_lock_path(repo_root),
        timeout_seconds=args.lock_timeout,
    )
    with lock:
        if getattr(args, "local", False):
            return _remove_local(args, repo_root, lock, remove_ids)
        try:
            current = ConsumerManifest.from_json(path.read_bytes())
        except (ValueError, KeyError) as exc:
            raise HaexError(
                message=f"{MANIFEST_RELATIVE_PATH} is not a valid v4 manifest: {exc}",
                context={"path": str(path)},
                diagnostic_key="spaex-manifest-invalid",
                exit_code=exit_codes.INCOMPLETE_TRANSACTION,
                hint=f"Repair `{MANIFEST_RELATIVE_PATH}` before retracting molecules.",
            ) from exc
        locally_adopted = _adopted_ids(local_scope.load_overlay(repo_root))
        _preflight_ids_present(
            current,
            remove_ids,
            hint=(
                f"Adopted only in `{LOCAL_MANIFEST_RELATIVE_PATH}`; "
                "use `spaex remove --local`."
                if locally_adopted & set(remove_ids)
                else None
            ),
        )

        new_manifest = _apply_removal(current, remove_ids)
        new_bytes = new_manifest.to_json_bytes()

        _warn_external_carriers(repo_root, remove_ids)

        exit_code = write_and_reinstall(
            repo_root,
            new_bytes,
            lock,
            # FR-024a: add-time plausibility check, identical treatment to
            # `spaex add` (contracts/cli-surface.md §add/remove).
            abort_on_behavior_contradiction=False,
        )

        sys.stdout.write(f"retracted {len(remove_ids)} molecule(s):\n")
        for mid in remove_ids:
            sys.stdout.write(f"  {mid}\n")
        return exit_code


__all__ = ["add_arguments", "run"]
