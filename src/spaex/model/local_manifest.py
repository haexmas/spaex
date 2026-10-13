"""LocalManifest — parsed `.spaex/local/manifest.json` (Spec 029).

The per-checkout overlay of molecules one developer adopts for themselves.
It carries only `compounds[]`: identity, version gates, groups and skill
policy stay project-level concerns of the committed consumer manifest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spaex.io import json_deterministic
from spaex.model.consumer_manifest import (
    CompoundEntry,
    ConsumerManifest,
    compounds_to_json,
    parse_compounds,
)
from spaex.schema import validator as schema_validator

LOCAL_MANIFEST_SCHEMA = "local-manifest.v1.schema.json"


@dataclass(frozen=True)
class LocalManifest:
    spaex_version: str
    compounds: tuple[CompoundEntry, ...]

    @staticmethod
    def from_json(raw: bytes) -> LocalManifest:
        """Parse and validate a local overlay manifest."""
        data = json.loads(raw.decode("utf-8"))
        schema_validator.validate(data, LOCAL_MANIFEST_SCHEMA)
        return LocalManifest(
            spaex_version=data["spaex_version"],
            compounds=parse_compounds(data["compounds"]),
        )

    def to_json_bytes(self) -> bytes:
        """Serialize the overlay to deterministic canonical JSON bytes."""
        return json_deterministic.dumps(
            {
                "spaex_version": self.spaex_version,
                "compounds": compounds_to_json(self.compounds),
            }
        )

    def as_consumer_manifest(self, identity: str) -> ConsumerManifest:
        """View the overlay as a consumer manifest for the shared resolver."""
        return ConsumerManifest(
            spaex_version=self.spaex_version,
            identity=identity,
            compounds=self.compounds,
        )
