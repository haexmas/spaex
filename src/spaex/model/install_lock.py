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
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from spaex.io import json_deterministic
from spaex.model._immutable import freeze_json, thaw_json
from spaex.model.source_url import CanonicalSourceUrl
from spaex.schema import validator as schema_validator
from spaex.util.errors import InstallLockSchemaInvalidError

_KNOWN_TOP_LEVEL_FIELDS = frozenset({"spaex_version", "generation_id", "molecules"})

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
class MoleculeEntry:
    """One installed molecule's sealed contribution (data-model.md §MoleculeEntry)."""

    id: str
    source: str
    revision: str
    paths: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", tuple(self.paths))


@dataclass(frozen=True)
class InstallLock:
    spaex_version: str
    generation_id: str
    molecules: tuple[MoleculeEntry, ...]
    unknown_top_level: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "molecules", tuple(self.molecules))
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
            unknown_top_level=unknown,
        )

    def to_json_bytes(self) -> bytes:
        """Serialize the install lock and retained extension fields deterministically."""
        obj: dict[str, Any] = {
            "spaex_version": self.spaex_version,
            "generation_id": self.generation_id,
            "molecules": [_serialize_molecule(m) for m in self.molecules],
        }
        for k, v in self.unknown_top_level.items():
            obj.setdefault(k, thaw_json(v))
        return json_deterministic.dumps(obj)


def _parse_molecules(raw: Any) -> tuple[MoleculeEntry, ...]:
    return tuple(
        MoleculeEntry(
            id=item["id"],
            source=CanonicalSourceUrl.validate(item["source"]),
            revision=item["revision"],
            paths=tuple(item["paths"]),
        )
        for item in raw
    )


def _serialize_molecule(molecule: MoleculeEntry) -> dict[str, Any]:
    return {
        "id": molecule.id,
        "source": molecule.source,
        "revision": molecule.revision,
        "paths": list(molecule.paths),
    }
