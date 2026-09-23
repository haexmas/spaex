"""MoleculeManifest — one molecule's `manifest.json` at a pinned SHA.

Renamed from AtomManifest by Spec 013. The v2 scalar `contributes` block is
replaced by the v3 `atoms` category map: category name -> non-empty list of
molecule-directory-relative delivered files. No delivered path may appear in
more than one category (data-model.md "Cross-category path overlap is
refused"); a violation refuses with `atoms-category-overlap`. External skill
references live in `external_skills` as structured
(repository, revision, path) metadata (Spec 018) and are not delivered file
paths; they require no `install_hook` and are installed only through an
explicit, consumer-selected `spaex skills install` adapter.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from spaex.model._immutable import freeze_json
from spaex.model.molecule_id import MoleculeId
from spaex.model.repo_relative_path import RepoRelativePath
from spaex.model.version_constraint import VersionConstraint
from spaex.schema import validator as schema_validator
from spaex.util.errors import MoleculeAtomsCategoryOverlapError


class SpeckitDeclarationParseError(ValueError):
    """A structurally valid manifest with an invalid Spec Kit declaration."""


@dataclass(frozen=True)
class ExternalSkillReference:
    """A provider-declared Agent Skill source (Spec 018), metadata only.

    Never a delivered file path: not materialized by spaex and never added
    to `install.lock`. Installation is a separate, explicit consumer-selected
    operation (`spaex skills install`); the reference carries no installer.
    """

    repository: str
    revision: str
    path: str


@dataclass(frozen=True)
class InstallHook:
    """Parsed install_hook object from a molecule manifest (Spec 016)."""

    interpreter: str
    script: str
    args: tuple[str, ...]
    on_failure: Literal["abort", "warn"]


@dataclass(frozen=True)
class SpeckitCliProvisioning:
    """Pinned PyPI package used to run the official Spec Kit CLI via uv."""

    package: Literal["specify-cli"]
    version: VersionConstraint


@dataclass(frozen=True)
class SpeckitDeclaration:
    """Declarative official Spec Kit integrations owned by a molecule."""

    version_constraint: VersionConstraint
    integrations: Mapping[str, str]
    cli: SpeckitCliProvisioning | None = None
    force: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "integrations", freeze_json(dict(self.integrations)))


@dataclass(frozen=True)
class MoleculeManifest:
    spaex_version: str
    id: str
    version: str
    priority: int
    atoms: Mapping[str, tuple[str, ...]]
    external_skills: tuple[ExternalSkillReference, ...] = ()
    defaults: Mapping[str, Any] = field(default_factory=dict)
    config_schema: str | None = None
    install_hook: InstallHook | None = None
    speckit: SpeckitDeclaration | None = None
    constitution_fragments: Mapping[str, tuple[Mapping[str, Any], ...]] = field(
        default_factory=dict
    )

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

        install_hook = _parse_install_hook(data.get("install_hook"))
        external_skills = _parse_external_skills(data.get("external_skills", ()))
        speckit = _parse_speckit(data.get("speckit"))

        constitution_fragments = _freeze_constitution_fragments(
            data.get("constitution_fragments", {})
        )

        return MoleculeManifest(
            spaex_version=data["spaex_version"],
            id=data["id"],
            version=data["version"],
            priority=data["priority"],
            atoms=freeze_json(data["atoms"]),
            external_skills=external_skills,
            defaults=freeze_json(defaults),
            config_schema=config_schema,
            install_hook=install_hook,
            speckit=speckit,
            constitution_fragments=constitution_fragments,
        )


def _parse_install_hook(raw: Any) -> InstallHook | None:
    """Explicit InstallHook construction. Schema default is documentation-only."""
    if raw is None:
        return None
    args_raw = raw.get("args", [])
    return InstallHook(
        interpreter=raw["interpreter"],
        script=raw["script"],
        args=tuple(args_raw),
        on_failure=raw.get("on_failure", "abort"),
    )


def _parse_external_skills(raw: Any) -> tuple[ExternalSkillReference, ...]:
    """Parse structured external skill references (Spec 018), preserving order.

    `path` is validated the same way as a delivered atom path
    (`RepoRelativePath`), even though it is never materialized: it is still a
    repository-relative path into the referenced source tree.
    """
    references: list[ExternalSkillReference] = []
    for entry in raw:
        RepoRelativePath.validate(entry["path"])
        references.append(
            ExternalSkillReference(
                repository=entry["repository"],
                revision=entry["revision"],
                path=entry["path"],
            )
        )
    return tuple(references)


def _parse_speckit(raw: Any) -> SpeckitDeclaration | None:
    """Parse the typed Spec Kit declaration after schema validation."""
    if raw is None:
        return None
    options: dict[str, str] = {}
    for key, value in raw["integrations"].items():
        option = value.get("integration_options", "")
        if any(token in option for token in ("\x00", "\n", "\r")):
            raise SpeckitDeclarationParseError(
                "speckit integration_options must not contain control characters"
            )
        if any(operator in option for operator in ("&&", "||", ";", "|", ">", "<", "`", "$")):
            raise SpeckitDeclarationParseError(
                "speckit integration_options must not contain shell operators"
            )
        if "--global" in option or "--project" in option:
            raise SpeckitDeclarationParseError(
                "speckit integration_options cannot request global or project installation"
            )
        options[key] = option
    try:
        version_constraint = VersionConstraint.parse(raw["version_constraint"])
    except (TypeError, ValueError) as exc:
        raise SpeckitDeclarationParseError(str(exc)) from exc
    cli_raw = raw.get("cli")
    cli: SpeckitCliProvisioning | None = None
    if cli_raw is not None:
        try:
            cli_version = VersionConstraint.parse(cli_raw["version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SpeckitDeclarationParseError(str(exc)) from exc
        if cli_version.operator != "==":
            raise SpeckitDeclarationParseError(
                "speckit cli.version must be an exact X.Y.Z version"
            )
        if not version_constraint.satisfied_by(cli_version.version):
            raise SpeckitDeclarationParseError(
                "speckit cli.version must satisfy version_constraint"
            )
        cli = SpeckitCliProvisioning(package=cli_raw["package"], version=cli_version)
    force = raw.get("force", False)
    if not isinstance(force, bool):
        raise SpeckitDeclarationParseError("speckit force must be a boolean")
    return SpeckitDeclaration(
        version_constraint=version_constraint,
        integrations=options,
        cli=cli,
        force=force,
    )


def _freeze_constitution_fragments(
    raw: Any,
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    """Freeze the inline constitution_fragments block for read-only exposure.

    The JSON Schema validated shape is `{<atom-id>: [entry, ...]}`. Each entry
    is preserved as a frozen mapping; deep validation of individual fragment
    fields happens in `spaex.behavior.fragment.BehaviorFragment.from_inline`
    at materialization time (Spec 023 T012).
    """
    if not raw:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("constitution_fragments must be an object keyed by atom-id")
    frozen: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for atom_id, entries in raw.items():
        if not isinstance(entries, list):
            raise ValueError(
                f"constitution_fragments[{atom_id!r}] must be a list"
            )
        frozen[atom_id] = tuple(freeze_json(entry) for entry in entries)
    return frozen
