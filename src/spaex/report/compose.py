"""Builds `CompositionReport` for `spaex status` (data-model.md, Spec 028)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from spaex.behavior.clauses import parse_clauses
from spaex.behavior.fragment import PROJECT_SCOPE
from spaex.behavior.orchestrate import CONSTITUTION_D_DIRNAME
from spaex.cli.install import _load_consumer_manifest
from spaex.model.consumer_manifest import flatten_compound_pins
from spaex.model.install_lock import (
    HookStatus,
    InstallLock,
    path_owners,
    read_with_consistent_generation,
)
from spaex.paths import (
    COMPOSED_CONSTITUTION_RELATIVE_PATH,
    SPAEX_DIRNAME,
    composed_constitution_path,
)
from spaex.report.staleness import check_constitution_staleness

InstallState = Literal["installed", "pinned_not_installed", "installed_not_pinned"]


@dataclass(frozen=True)
class AtomGrouping:
    """Per-molecule breakdown of what spaex materialized from its atoms (data-model.md)."""

    behavior_fragments: tuple[str, ...]
    composed_artifacts: tuple[str, ...]
    files: tuple[str, ...]


@dataclass(frozen=True)
class MoleculeRecord:
    """One molecule appearing in either the manifest's pins or the install lock."""

    molecule_id: str
    pinned: tuple[str, str] | None
    installed: tuple[str, str] | None
    install_state: InstallState
    hook_status: HookStatus | None
    atoms: AtomGrouping


@dataclass(frozen=True)
class DriftFinding:
    """One disagreement between the manifest, the install lock, or the composed constitution."""

    kind: Literal[
        "pinned_not_installed",
        "installed_not_pinned",
        "revision_mismatch",
        "constitution_stale",
    ]
    molecule_id: str | None
    pinned: tuple[str, str] | None
    installed: tuple[str, str] | None


@dataclass(frozen=True)
class ConstitutionSummary:
    """Summary of the composed `.spaex/constitution.md` (data-model.md)."""

    exists: bool
    clause_counts: dict[str, int]
    contributing_molecules: tuple[str, ...]
    project_local_fragment_ids: tuple[str, ...]
    stale: bool


@dataclass(frozen=True)
class CompositionReport:
    """The full `spaex status` report (data-model.md)."""

    molecules: tuple[MoleculeRecord, ...]
    constitution: ConstitutionSummary | None
    drift: tuple[DriftFinding, ...]


def behavior_fragment_ids(repo_root: Path, molecule_id: str) -> list[str]:
    """Sorted fragment-id stems under `.spaex/constitution.d/<molecule_id>/`."""
    molecule_dir = repo_root / SPAEX_DIRNAME / CONSTITUTION_D_DIRNAME / molecule_id
    if not molecule_dir.is_dir():
        return []
    return sorted(p.stem for p in molecule_dir.glob("*.md"))


def project_local_fragment_ids(repo_root: Path) -> list[str]:
    """Sorted fragment-id stems under `.spaex/constitution.d/_project/`."""
    return behavior_fragment_ids(repo_root, PROJECT_SCOPE)


def build_atom_grouping(
    repo_root: Path, molecule_id: str, lock: InstallLock
) -> AtomGrouping:
    """Group `molecule_id`'s recorded paths by what spaex did with them (research.md R1)."""
    owners = path_owners(lock)
    composed_artifacts: list[str] = []
    files: list[str] = []
    for path, owner_ids in owners.items():
        if path == COMPOSED_CONSTITUTION_RELATIVE_PATH or molecule_id not in owner_ids:
            continue
        if len(owner_ids) > 1:
            composed_artifacts.append(path)
        else:
            files.append(path)
    return AtomGrouping(
        behavior_fragments=tuple(behavior_fragment_ids(repo_root, molecule_id)),
        composed_artifacts=tuple(sorted(composed_artifacts)),
        files=tuple(sorted(files)),
    )


def build_constitution_summary(
    repo_root: Path, lock: InstallLock
) -> ConstitutionSummary | None:
    """Summarize the composed constitution, or `None` when there isn't one."""
    constitution_d = repo_root / SPAEX_DIRNAME / CONSTITUTION_D_DIRNAME
    contributing_molecules = (
        sorted(
            p.name
            for p in constitution_d.iterdir()
            if p.is_dir()
            and p.name != PROJECT_SCOPE
            and any(p.glob("*.md"))
        )
        if constitution_d.is_dir()
        else []
    )
    project_local_ids = project_local_fragment_ids(repo_root)
    constitution_path = composed_constitution_path(repo_root)
    constitution_exists = constitution_path.exists()

    if not contributing_molecules and not project_local_ids and not constitution_exists:
        return None

    clause_counts: dict[str, int] = {}
    if constitution_exists:
        clauses = parse_clauses(constitution_path.read_text(encoding="utf-8"))
        for clause in clauses:
            clause_counts[clause.modality] = clause_counts.get(clause.modality, 0) + 1

    return ConstitutionSummary(
        exists=constitution_exists,
        clause_counts=clause_counts,
        contributing_molecules=tuple(contributing_molecules),
        project_local_fragment_ids=tuple(project_local_ids),
        stale=check_constitution_staleness(repo_root),
    )


def _build_drift_findings(
    molecules: tuple[MoleculeRecord, ...], constitution: ConstitutionSummary | None
) -> tuple[DriftFinding, ...]:
    """Assemble drift findings from already-built molecule records and constitution summary
    (research.md R3, R4)."""
    findings: list[DriftFinding] = []
    for molecule in molecules:
        if molecule.install_state == "pinned_not_installed":
            findings.append(
                DriftFinding(
                    kind="pinned_not_installed",
                    molecule_id=molecule.molecule_id,
                    pinned=molecule.pinned,
                    installed=None,
                )
            )
        elif molecule.install_state == "installed_not_pinned":
            findings.append(
                DriftFinding(
                    kind="installed_not_pinned",
                    molecule_id=molecule.molecule_id,
                    pinned=None,
                    installed=molecule.installed,
                )
            )
        elif (
            molecule.pinned is not None
            and molecule.installed is not None
            and molecule.pinned[1] != molecule.installed[1]
        ):
            findings.append(
                DriftFinding(
                    kind="revision_mismatch",
                    molecule_id=molecule.molecule_id,
                    pinned=molecule.pinned,
                    installed=molecule.installed,
                )
            )
    if constitution is not None and constitution.stale:
        findings.append(
            DriftFinding(
                kind="constitution_stale", molecule_id=None, pinned=None, installed=None
            )
        )
    return tuple(sorted(findings, key=lambda f: (f.molecule_id is None, f.molecule_id or "")))


def build_composition_report(repo_root: Path) -> CompositionReport:
    """Build the full `spaex status` report from on-disk `.spaex/` state (FR-002, FR-015)."""
    def _build(lock: InstallLock) -> CompositionReport:
        manifest = _load_consumer_manifest(repo_root)
        pinned_map = flatten_compound_pins(manifest)
        installed_map = {molecule.id: molecule for molecule in lock.molecules}
        molecule_ids = sorted(set(pinned_map) | set(installed_map))

        molecules: list[MoleculeRecord] = []
        for molecule_id in molecule_ids:
            pinned = pinned_map.get(molecule_id)
            installed_entry = installed_map.get(molecule_id)
            installed = (
                (installed_entry.source, installed_entry.revision)
                if installed_entry is not None
                else None
            )
            if pinned is not None and installed_entry is not None:
                install_state: InstallState = "installed"
            elif installed_entry is None:
                install_state = "pinned_not_installed"
            else:
                install_state = "installed_not_pinned"
            molecules.append(
                MoleculeRecord(
                    molecule_id=molecule_id,
                    pinned=pinned,
                    installed=installed,
                    install_state=install_state,
                    hook_status=installed_entry.hook_status if installed_entry else None,
                    atoms=build_atom_grouping(repo_root, molecule_id, lock),
                )
            )

        molecules_tuple = tuple(molecules)
        constitution = build_constitution_summary(repo_root, lock)
        return CompositionReport(
            molecules=molecules_tuple,
            constitution=constitution,
            drift=_build_drift_findings(molecules_tuple, constitution),
        )

    return read_with_consistent_generation(repo_root, _build)
