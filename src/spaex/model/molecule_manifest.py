"""MoleculeManifest — one molecule's `manifest.json` at a pinned SHA.

Renamed from AtomManifest by Spec 013. The v2 scalar `contributes` block is
replaced by the v3 `atoms` category map: category name -> non-empty list of
molecule-directory-relative delivered files. No delivered path may appear in
more than one category (data-model.md "Cross-category path overlap is
refused"); a violation refuses with `atoms-category-overlap`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from spaex.model._immutable import freeze_json
from spaex.model.molecule_id import MoleculeId
from spaex.model.repo_relative_path import RepoRelativePath
from spaex.schema import validator as schema_validator
from spaex.util.errors import MoleculeAtomsCategoryOverlapError


@dataclass(frozen=True)
class MoleculeManifest:
    spaex_version: str
    id: str
    version: str
    priority: int
    atoms: Mapping[str, tuple[str, ...]]
    defaults: Mapping[str, Any] = field(default_factory=dict)
    config_schema: str | None = None

    @staticmethod
    def from_json(raw: bytes) -> MoleculeManifest:
        """Parse and validate a v4 molecule manifest and its contributed paths."""
        data = json.loads(raw.decode("utf-8"))
        schema_validator.validate(data, "molecule-manifest.v4.schema.json")

        MoleculeId.parse(data["id"])

        seen_paths: dict[str, str] = {}
        for category, paths in data["atoms"].items():
            for path in paths:
                RepoRelativePath.validate(path)
                owner = seen_paths.get(path)
                if owner is not None and owner != category:
                    raise MoleculeAtomsCategoryOverlapError(
                        message=(
                            f"molecule {data['id']!r} path {path!r} appears in both "
                            f"category {owner!r} and {category!r}"
                        ),
                        context={"molecule_id": data["id"], "path": path},
                    )
                seen_paths[path] = category

        config_schema = data.get("config_schema")
        if config_schema is not None:
            RepoRelativePath.validate(config_schema)

        defaults = data.get("defaults", {})
        if "priority" in defaults:
            raise ValueError(
                f"molecule {data['id']!r} defaults MUST NOT declare priority"
            )

        return MoleculeManifest(
            spaex_version=data["spaex_version"],
            id=data["id"],
            version=data["version"],
            priority=data["priority"],
            atoms=freeze_json(data["atoms"]),
            defaults=freeze_json(defaults),
            config_schema=config_schema,
        )
