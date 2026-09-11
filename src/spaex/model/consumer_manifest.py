"""ConsumerManifest — parsed `.spaex.json` v3.

Renamed from v2 by Spec 013: top-level `atoms[]` -> `compounds[]`,
per-entry `includes[]` -> `molecules[]`, `AtomEntry` -> `CompoundEntry`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from spaex.io import json_deterministic
from spaex.model._immutable import freeze_json, thaw_json
from spaex.model.molecule_id import MoleculeId
from spaex.model.source_url import canonicalize
from spaex.model.version_constraint import VersionConstraint
from spaex.schema import validator as schema_validator
from spaex.util.errors import SpaexVersionUnsupportedError

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ConfigEntry:
    priority: int | None = None
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompoundEntry:
    source: str
    revision: str
    molecules: tuple[str, ...]
    track: str | None = None
    config: Mapping[str, ConfigEntry] = field(default_factory=dict)


@dataclass(frozen=True)
class ConsumerManifest:
    spaex_version: str
    identity: str
    compounds: tuple[CompoundEntry, ...]
    spaex_min_version: VersionConstraint | None = None
    groups: tuple[str, ...] = ()
    active_feature: str | None = None
    identity_note: str | None = None
    local_fragments: tuple[Mapping[str, Any], ...] = ()

    @staticmethod
    def from_json(raw: bytes) -> ConsumerManifest:
        """Parse and validate a canonical v4 consumer manifest."""
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict):
            if "haex_hive_version" in data:
                raise SpaexVersionUnsupportedError(
                    message="legacy haex_hive_version is not supported by the v4 read gate",
                    context={"version": str(data["haex_hive_version"])},
                )
            if "spaex_version" in data and data["spaex_version"] != "4":
                raise SpaexVersionUnsupportedError(
                    message=(
                        f"unsupported spaex_version {data['spaex_version']!r}; "
                        'the consumer manifest must declare "4"'
                    ),
                    context={"version": str(data["spaex_version"])},
                )
        schema_validator.validate(data, "consumer-manifest.v4.schema.json")

        MoleculeId.parse_identity(data["identity"])
        min_version = None
        if "spaex_min_version" in data:
            min_version = VersionConstraint.parse(data["spaex_min_version"])

        compounds: list[CompoundEntry] = []
        for entry in data.get("compounds", []):
            source = entry["source"]
            canonical = canonicalize(source)
            if canonical != source:
                raise ValueError(
                    f"compounds[].source must be canonical: got {source!r}, expected {canonical!r}"
                )
            if not _SHA40_RE.match(entry["revision"]):
                raise ValueError(
                    f"compounds[].revision must be 40 lowercase hex: {entry['revision']!r}"
                )
            molecules = tuple(MoleculeId.parse(m) for m in entry["molecules"])
            if len(set(molecules)) != len(molecules):
                raise ValueError("compounds[].molecules must be unique")
            config: dict[str, ConfigEntry] = {}
            for key, value in entry.get("config", {}).items():
                MoleculeId.parse(key)
                if key not in set(molecules):
                    raise ValueError(f"compounds[].config[{key!r}] not resolved via molecules")
                config[key] = ConfigEntry(
                    priority=value.get("priority"),
                    values=freeze_json(value.get("values", {})),
                )
            compounds.append(
                CompoundEntry(
                    source=source,
                    revision=entry["revision"],
                    molecules=molecules,
                    track=entry.get("track"),
                    config=freeze_json(config),
                )
            )

        local_fragments = tuple(
            freeze_json(entry)
            for entry in data.get("constitution", {}).get("local_fragments", [])
        )

        return ConsumerManifest(
            spaex_version=data["spaex_version"],
            identity=data["identity"],
            compounds=tuple(compounds),
            spaex_min_version=min_version,
            groups=tuple(data.get("groups", [])),
            active_feature=data.get("active_feature"),
            identity_note=data.get("identity_note"),
            local_fragments=local_fragments,
        )

    def to_json_bytes(self) -> bytes:
        """Serialize the manifest to deterministic canonical JSON bytes."""
        obj: dict[str, Any] = {
            "spaex_version": self.spaex_version,
            "identity": self.identity,
            "compounds": [
                {
                    **(
                        {
                            "source": c.source,
                            "revision": c.revision,
                            "molecules": list(c.molecules),
                        }
                    ),
                    **({"track": c.track} if c.track else {}),
                    **(
                        {
                            "config": {
                                k: {
                                    **({"priority": v.priority} if v.priority is not None else {}),
                                    **({"values": thaw_json(v.values)} if v.values else {}),
                                }
                                for k, v in c.config.items()
                            }
                        }
                        if c.config
                        else {}
                    ),
                }
                for c in self.compounds
            ],
        }
        if self.spaex_min_version is not None:
            op = self.spaex_min_version.operator
            v = self.spaex_min_version.version
            obj["spaex_min_version"] = (
                f"{'>=' if op == '>=' else ''}{v[0]}.{v[1]}.{v[2]}"
            )
        if self.groups:
            obj["groups"] = list(self.groups)
        if self.active_feature is not None:
            obj["active_feature"] = self.active_feature
        if self.identity_note is not None:
            obj["identity_note"] = self.identity_note
        if self.local_fragments:
            obj["constitution"] = {
                "local_fragments": [thaw_json(e) for e in self.local_fragments]
            }
        return json_deterministic.dumps(obj)
