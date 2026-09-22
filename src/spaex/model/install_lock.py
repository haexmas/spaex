"""InstallLock v3 — the on-disk contract for `.spaex/install.lock`.

2026-09-03 npm/pip-shape simplification (Spec 008 amendment): install.lock
now carries only `{spaex_version, generation_id, molecules[]}`, where
each molecule entry is `{id, source, revision, paths}`. Retired:
`generated_by`, the `constitution` block (`sources[]`/`assembled_by`),
`participating_roots[]`, `generation_inputs[]`, and the separate
`.spaex/visibility.json` file with its `visibility_marker`
cross-reference. Everything retired is either derivable from git history
(tool version), derivable from `molecules[].paths[]` (constitution
provenance: the molecule whose paths include `.spaex/constitution.md`;
participating roots: the set of leading dot-segments across every path),
or was only ever relevant to the retired multi-source LLM merge
(generation_inputs, per ADR 0010).

The still-present `unknown_top_level` bag preserves *actually* unknown
fields (anything the schema doesn't yet describe) across a read/write
round-trip, so a future v4 field can survive a v3 reader.

Spec 027 adds one new known top-level field, `content_hashes` (path ->
`sha256:<hex>`), used only to detect operator modification of an
exclusive generic-atom root file since spaex last wrote it (FR-007). It
does not change `molecules[].paths`' meaning: a path under a leading
dot-segment still names its participating root; a bare filename (no
leading dot-segment, Spec 027) has no such root and lives at the literal
repository root instead.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

from spaex.io import json_deterministic, transaction
from spaex.model._immutable import freeze_json, thaw_json
from spaex.model.source_url import CanonicalSourceUrl
from spaex.schema import validator as schema_validator
from spaex.util.errors import InstallLockGenerationInconsistentError, InstallLockSchemaInvalidError

T = TypeVar("T")

HookStatus = Literal["ok", "failed", "skipped"]
SpeckitOutcomeStatus = Literal["installed", "already_satisfied", "skipped"]

_KNOWN_TOP_LEVEL_FIELDS = frozenset(
    {"spaex_version", "generation_id", "molecules", "content_hashes"}
)

# Retired by the 2026-09-03 npm/pip-shape amendment (Spec 008). Enumerated
# explicitly so a lock carrying any of them refuses at the runtime read gate,
# not just the strict schema/FR-005 gate. Without this, `from_json` would
# stash them in `unknown_top_level` and `to_json_bytes` would republish them.
_RETIRED_TOP_LEVEL_FIELDS = frozenset(
    {
        "generated_by",
        "constitution",
        "atoms",
        "participating_roots",
        "generation_inputs",
        "visibility_marker",
    }
)


@dataclass(frozen=True)
class ConstitutionSource:
    """Provenance for a resolved constitution contribution.

    Internal to the resolve/assemble pipeline; not part of the on-disk
    install.lock schema. Constitution provenance in the published lock is
    derived from `MoleculeEntry.paths` instead (data-model.md §InstallLock).
    """

    id: str
    revision: str
    source: str


@dataclass(frozen=True)
class SpeckitLockRecord:
    """Successful Spec Kit integration state persisted per molecule."""

    cli_version: str
    declaration_fingerprint: str
    selected: tuple[str, ...]
    outcomes: Mapping[str, SpeckitOutcomeStatus]

    def __post_init__(self) -> None:
        selected = tuple(sorted(set(self.selected)))
        outcomes = dict(self.outcomes)
        invalid = sorted(
            key
            for key in selected
            if outcomes.get(key) != "installed" and outcomes.get(key) != "already_satisfied"
        )
        if invalid:
            raise InstallLockSchemaInvalidError(
                message=(
                    "selected Spec Kit integration(s) must have a successful outcome: "
                    + ", ".join(invalid)
                ),
                context={"integrations": ",".join(invalid)},
            )
        object.__setattr__(self, "selected", selected)
        object.__setattr__(self, "outcomes", freeze_json(outcomes))


@dataclass(frozen=True)
class MoleculeEntry:
    """One installed molecule's sealed contribution (data-model.md §MoleculeEntry).

    Behavior molecules use the shared ``.spaex/constitution.md`` publication
    path in ``paths``; their inspectable fragment files are not duplicated in
    the lock entry.
    """

    id: str
    source: str
    revision: str
    paths: tuple[str, ...]
    hook_status: HookStatus | None = None
    speckit: SpeckitLockRecord | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", tuple(self.paths))


@dataclass(frozen=True)
class InstallLock:
    spaex_version: str
    generation_id: str
    molecules: tuple[MoleculeEntry, ...]
    content_hashes: Mapping[str, str] = field(default_factory=dict)
    unknown_top_level: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "molecules", tuple(self.molecules))
        object.__setattr__(
            self, "content_hashes", freeze_json(dict(self.content_hashes))
        )
        object.__setattr__(
            self,
            "unknown_top_level",
            freeze_json(dict(self.unknown_top_level)),
        )

    @staticmethod
    def from_json(raw: bytes) -> InstallLock:
        """Parse an install lock while preserving unknown top-level fields."""
        try:
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                # Refuse retired v2-era / pre-amendment fields explicitly. The
                # strict v3 schema also rejects them, but `from_json` splits
                # unknown keys into `unknown_top_level` for forward-compat, so
                # without this check a lock carrying `generated_by` (or another
                # retired field) would pass the runtime gate and be republished.
                retired_present = sorted(
                    key for key in data if key in _RETIRED_TOP_LEVEL_FIELDS
                )
                if retired_present:
                    raise InstallLockSchemaInvalidError(
                        message=(
                            "install.lock carries retired top-level field(s): "
                            + ", ".join(retired_present)
                        ),
                        context={
                            "schema": "install-lock.v4.schema.json",
                            "retired_fields": ",".join(retired_present),
                        },
                    )
                # Keep unknown top-level fields so a v3 reader can round-trip
                # fields introduced by a newer lock schema. The v3 schema has
                # additionalProperties=false, so validate only its known
                # projection while retaining the complete unknown bag.
                unknown = {
                    key: value
                    for key, value in data.items()
                    if key not in _KNOWN_TOP_LEVEL_FIELDS
                }
                validation_data = {
                    key: value
                    for key, value in data.items()
                    if key in _KNOWN_TOP_LEVEL_FIELDS
                }
            else:
                unknown = {}
                validation_data = data
            schema_validator.validate(validation_data, "install-lock.v4.schema.json")
        except InstallLockSchemaInvalidError:
            raise
        except (UnicodeError, ValueError) as exc:
            detail = (
                f": {exc}"
                if isinstance(exc, schema_validator.SchemaValidationError)
                else ""
            )
            raise InstallLockSchemaInvalidError(
                message=(
                    "install.lock is not valid against install-lock.v4.schema.json"
                    + detail
                ),
                context={"schema": "install-lock.v4.schema.json"},
            ) from exc

        molecules = _parse_molecules(data["molecules"])
        return InstallLock(
            spaex_version=data["spaex_version"],
            generation_id=data["generation_id"],
            molecules=molecules,
            content_hashes=data.get("content_hashes", {}),
            unknown_top_level=unknown,
        )

    def to_json_bytes(self) -> bytes:
        """Serialize the install lock and retained extension fields deterministically."""
        obj: dict[str, Any] = {
            "spaex_version": self.spaex_version,
            "generation_id": self.generation_id,
            "molecules": [_serialize_molecule(m) for m in self.molecules],
        }
        if self.content_hashes:
            obj["content_hashes"] = dict(thaw_json(self.content_hashes))
        for k, v in self.unknown_top_level.items():
            obj.setdefault(k, thaw_json(v))
        return json_deterministic.dumps(obj)


def path_owners(lock: InstallLock) -> dict[str, tuple[str, ...]]:
    """Map every path recorded in `lock` to the molecule id(s) that own it.

    A path owned by more than one molecule (e.g. `.spaex/constitution.md`,
    or a Spec 027 composable generated artifact) lists every owner, in
    `lock.molecules` order (research.md R2 addendum, data-model.md
    `PathOwnership`/`AtomGrouping`).
    """
    owners: dict[str, list[str]] = {}
    for molecule in lock.molecules:
        for path in molecule.paths:
            owners.setdefault(path, []).append(molecule.id)
    return {path: tuple(ids) for path, ids in owners.items()}


def read_with_consistent_generation(
    repo_root: Path, build: Callable[[InstallLock], T]
) -> T:
    """Read `.spaex/install.lock`, run `build` against it, and confirm its
    `generation_id` did not change while `build` ran (research.md R9, FR-015).

    `.spaex/` is published as one atomic unit, so a concurrent `spaex
    install` can complete its swap between any two separate reads under
    `.spaex/` that `build` performs (manifest, constitution fragments,
    constitution body, ...). Bracketing with `generation_id` catches such a
    torn read: read the lock, run `build`, then re-read the lock's
    `generation_id` alone. A missing lock (never installed) is treated as
    an empty `InstallLock`, never an error by itself. Retries the whole
    read+build+re-read sequence once on a mismatch; raises
    `InstallLockGenerationInconsistentError` naming both observed
    generation ids if it still disagrees after the retry.
    """
    lock_path = repo_root / transaction.SPAEX_DIR / transaction.INSTALL_LOCK_NAME

    def _read_lock() -> InstallLock:
        """Read the current lock, using an empty lock before the first install."""
        if not lock_path.exists():
            return InstallLock(spaex_version="4", generation_id="", molecules=())
        return InstallLock.from_json(lock_path.read_bytes())

    first_id = second_id = ""
    for _attempt in range(2):
        lock = _read_lock()
        first_id = lock.generation_id
        result = build(lock)
        second_id = _read_lock().generation_id
        if second_id == first_id:
            return result

    raise InstallLockGenerationInconsistentError(
        message=(
            "install.lock's generation changed while reading it, even after "
            f"one retry: observed {first_id!r} then {second_id!r}"
        ),
        context={"first_generation_id": first_id, "second_generation_id": second_id},
    )


def _parse_molecules(raw: Any) -> tuple[MoleculeEntry, ...]:
    return tuple(
        MoleculeEntry(
            id=item["id"],
            source=CanonicalSourceUrl.validate(item["source"]),
            revision=item["revision"],
            paths=tuple(item["paths"]),
            hook_status=item.get("hook_status"),
            speckit=_parse_speckit_record(item.get("speckit")),
        )
        for item in raw
    )


def _serialize_molecule(molecule: MoleculeEntry) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "id": molecule.id,
        "source": molecule.source,
        "revision": molecule.revision,
        "paths": list(molecule.paths),
    }
    if molecule.hook_status is not None:
        obj["hook_status"] = molecule.hook_status
    if molecule.speckit is not None:
        obj["speckit"] = {
            "cli_version": molecule.speckit.cli_version,
            "declaration_fingerprint": molecule.speckit.declaration_fingerprint,
            "selected": list(molecule.speckit.selected),
            "outcomes": thaw_json(molecule.speckit.outcomes),
        }
    return obj


def _parse_speckit_record(raw: Any) -> SpeckitLockRecord | None:
    if raw is None:
        return None
    return SpeckitLockRecord(
        cli_version=raw["cli_version"],
        declaration_fingerprint=raw["declaration_fingerprint"],
        selected=tuple(raw["selected"]),
        outcomes=raw["outcomes"],
    )
