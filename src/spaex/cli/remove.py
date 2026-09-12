"""`haex remove` — retract one or more molecules from `.spaex.json`.

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
import sys
from pathlib import Path

from spaex.install.manifest_lock import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    ManifestLockContext,
    parse_lock_timeout,
)
from spaex.install.write_and_reinstall import write_and_reinstall
from spaex.model.consumer_manifest import (
    CompoundEntry,
    ConsumerManifest,
)
from spaex.model.install_lock import InstallLock
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


def _preflight_ids_present(
    manifest: ConsumerManifest, requested: tuple[str, ...]
) -> None:
    present: set[str] = set()
    for compound in manifest.compounds:
        present.update(compound.molecules)
    missing = [mid for mid in requested if mid not in present]
    if missing:
        raise UnknownMoleculeIdError(
            message=(
                "no adopted compound lists the requested molecule id(s): "
                + ", ".join(missing)
            ),
            context={"missing": ",".join(missing)},
        )


def _apply_removal(
    manifest: ConsumerManifest, remove_ids: tuple[str, ...]
) -> ConsumerManifest:
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


def _warn_hook_carriers(repo_root: Path, remove_ids: tuple[str, ...]) -> None:
    """Emit FR-029 WARN for retracted molecules whose current install.lock
    record carries an install-hook status (evidence that the pinned revision
    declared install_hook). Silent when install.lock is absent (fresh-consumer
    edge case). Order follows ``remove_ids`` for deterministic output.
    """
    lock_path = repo_root / ".spaex" / "install.lock"
    if not lock_path.exists():
        return
    lock = InstallLock.from_json(lock_path.read_bytes())
    hook_carriers = {m.id for m in lock.molecules if m.hook_status is not None}
    for mid in remove_ids:
        if mid in hook_carriers:
            sys.stderr.write(
                f"WARN: molecule {mid} had an install_hook; side effects "
                "(git hooks, gitignore entries, provisioned tools, "
                "agent-harness registrations) may remain. Consult the "
                "molecule's README for reverse steps.\n"
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


def run(args: argparse.Namespace) -> int:
    """Retract requested molecules and reinstall the resulting manifest."""
    repo_root = Path(args.repo_root).resolve()
    manifest_path = repo_root / ".spaex.json"
    if not manifest_path.exists():
        raise HaexError(
            message=f"{manifest_path} is missing",
            context={"path": str(manifest_path)},
            diagnostic_key="spaex-json-missing",
            exit_code=exit_codes.INCOMPLETE_TRANSACTION,
            hint="Nothing to retract; there is no consumer manifest here.",
        )

    # A molecule is removed once even if the operator repeats its ID.
    remove_ids = tuple(dict.fromkeys(_parse_ids(args.molecule_ids)))

    lock = ManifestLockContext(
        repo_root / ".spaex.json.lock",
        timeout_seconds=args.lock_timeout,
    )
    with lock:
        try:
            current = ConsumerManifest.from_json(manifest_path.read_bytes())
        except (ValueError, KeyError) as exc:
            raise HaexError(
                message=f".spaex.json is not a valid v4 manifest: {exc}",
                context={"path": str(manifest_path)},
                diagnostic_key="spaex-json-invalid",
                exit_code=exit_codes.INCOMPLETE_TRANSACTION,
                hint="Repair `.spaex.json` before retracting molecules.",
            ) from exc
        _preflight_ids_present(current, remove_ids)

        new_manifest = _apply_removal(current, remove_ids)
        new_bytes = new_manifest.to_json_bytes()

        _warn_hook_carriers(repo_root, remove_ids)

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
