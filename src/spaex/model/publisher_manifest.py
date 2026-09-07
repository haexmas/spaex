"""PublisherManifest — root `manifest.json` at a publisher repo's pinned SHA.

Renamed from v2 by Spec 013: top-level `atoms{}` -> `molecules{}`,
`PublisherAtomEntry` -> `PublisherMoleculeEntry`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from spaex.model._immutable import freeze_json
from spaex.model.molecule_id import MoleculeId
from spaex.model.repo_relative_path import RepoRelativePath
from spaex.schema import validator as schema_validator


@dataclass(frozen=True)
class PublisherMoleculeEntry:
    path: str
    version: str
    description: str | None = None


@dataclass(frozen=True)
class PublisherManifest:
    spaex_version: str
    publisher: str
    molecules: Mapping[str, PublisherMoleculeEntry]

    @staticmethod
    def from_json(raw: bytes) -> PublisherManifest:
        """Parse and validate a v4 publisher manifest and molecule index."""
        data = json.loads(raw.decode("utf-8"))
        schema_validator.validate(data, "publisher-manifest.v4.schema.json")

        publisher = MoleculeId.parse(data["publisher"])
        prefix = publisher + "."
        molecules: dict[str, PublisherMoleculeEntry] = {}
        for molecule_id, entry in data.get("molecules", {}).items():
            MoleculeId.parse(molecule_id)
            if not molecule_id.startswith(prefix):
                raise ValueError(
                    f"molecule-id {molecule_id!r} does not have publisher prefix {publisher!r}"
                )
            RepoRelativePath.validate(entry["path"])
            molecules[molecule_id] = PublisherMoleculeEntry(
                path=entry["path"],
                version=entry["version"],
                description=entry.get("description"),
            )
        return PublisherManifest(
            spaex_version=data["spaex_version"],
            publisher=publisher,
            molecules=freeze_json(molecules),
        )
