"""`spaex status`/`spaex trace` CLI subcommands (Spec 028, contracts/status-and-trace-cli.md)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spaex.behavior.clauses import MODALITY_ORDER
from spaex.report.compose import (
    CompositionReport,
    ConstitutionSummary,
    DriftFinding,
    MoleculeRecord,
    build_composition_report,
)
from spaex.report.trace import FileAttribution, MoleculeOwner, PathOwnership, resolve_trace_query
from spaex.util import exit_codes

_INSTALL_STATE_PHRASE = {
    "installed": "installed",
    "pinned_not_installed": "pinned, not installed",
    "installed_not_pinned": "installed, not pinned",
}

_DRIFT_PHRASE = {
    "pinned_not_installed": "pinned but not installed",
    "installed_not_pinned": "installed but no longer pinned",
}


def run_status(args: argparse.Namespace) -> int:
    """`spaex status` (contracts/status-and-trace-cli.md §"spaex status")."""
    repo_root = Path(args.repo_root).resolve()
    fmt = getattr(args, "format", None) or "text"

    report = build_composition_report(repo_root)
    record = _build_status_record(report)

    if fmt == "json":
        sys.stdout.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(_render_status_text(record))
    return exit_codes.SUCCESS


def _render_source_revision(pair: tuple[str, str] | None) -> dict[str, str] | None:
    if pair is None:
        return None
    source, revision = pair
    return {"source": source, "revision": revision}


def _render_molecule_record(molecule: MoleculeRecord) -> dict[str, object]:
    return {
        "molecule_id": molecule.molecule_id,
        "pinned": _render_source_revision(molecule.pinned),
        "installed": _render_source_revision(molecule.installed),
        "install_state": molecule.install_state,
        "hook_status": molecule.hook_status,
        "atoms": {
            "behavior_fragments": list(molecule.atoms.behavior_fragments),
            "composed_artifacts": list(molecule.atoms.composed_artifacts),
            "files": list(molecule.atoms.files),
        },
    }


def _render_constitution_summary(
    summary: ConstitutionSummary | None,
) -> dict[str, object] | None:
    if summary is None:
        return None
    return {
        "exists": summary.exists,
        "clause_counts": dict(summary.clause_counts),
        "contributing_molecules": list(summary.contributing_molecules),
        "project_local_fragment_ids": list(summary.project_local_fragment_ids),
        "stale": summary.stale,
    }


def _render_drift_finding(finding: DriftFinding) -> dict[str, object]:
    return {
        "kind": finding.kind,
        "molecule_id": finding.molecule_id,
        "pinned": _render_source_revision(finding.pinned),
        "installed": _render_source_revision(finding.installed),
    }


def _build_status_record(report: CompositionReport) -> dict[str, object]:
    return {
        "format_version": 1,
        "molecules": [_render_molecule_record(m) for m in report.molecules],
        "constitution": _render_constitution_summary(report.constitution),
        "drift": [_render_drift_finding(d) for d in report.drift],
    }


def _render_status_text(record: dict[str, object]) -> str:
    lines = ["spaex status", ""]
    lines.extend(_render_molecules_text(record["molecules"]))
    lines.append("")
    lines.extend(_render_constitution_text(record["constitution"]))
    drift = record["drift"]
    assert isinstance(drift, list)
    if drift:
        lines.append("")
        lines.extend(_render_drift_text(drift))
    return "\n".join(lines) + "\n"


def _render_molecules_text(molecules: object) -> list[str]:
    assert isinstance(molecules, list)
    pinned_count = sum(1 for m in molecules if m["pinned"] is not None)
    installed_count = sum(1 for m in molecules if m["installed"] is not None)
    lines = [f"Molecules ({pinned_count} pinned, {installed_count} installed):"]
    for molecule in molecules:
        pinned = molecule["pinned"]
        installed = molecule["installed"]
        if pinned and installed and pinned["revision"] != installed["revision"]:
            revision = (
                f"@{installed['revision'][:8]} "
                f"(pinned @{pinned['revision'][:8]})"
            )
        else:
            revision_source = installed or pinned
            revision = f"@{revision_source['revision'][:8]}" if revision_source else ""
        phrase = _INSTALL_STATE_PHRASE[molecule["install_state"]]
        lines.append(f"  {molecule['molecule_id']}{revision} — {phrase}")
        atoms = molecule["atoms"]
        if atoms["behavior_fragments"]:
            lines.append(f"    behavior fragments: {', '.join(atoms['behavior_fragments'])}")
        if atoms["composed_artifacts"]:
            lines.append(f"    composed artifacts: {', '.join(atoms['composed_artifacts'])}")
        if atoms["files"]:
            lines.append(f"    files: {', '.join(atoms['files'])}")
    return lines


def _render_constitution_text(summary: object) -> list[str]:
    if summary is None:
        return ["Constitution: none"]
    assert isinstance(summary, dict)
    clause_counts = summary["clause_counts"]
    total = sum(clause_counts.values())
    breakdown = ", ".join(
        f"{modality}: {clause_counts[modality]}"
        for modality in MODALITY_ORDER
        if modality in clause_counts
    )
    contributing = ", ".join(summary["contributing_molecules"]) or "none"
    project_local = ", ".join(summary["project_local_fragment_ids"]) or "none"
    status = "stale" if summary["stale"] else "current"
    return [
        f"Constitution: {total} clauses ({breakdown})",
        f"  contributing molecules: {contributing}",
        f"  project-local fragments: {project_local}",
        f"  status: {status}",
    ]


def _render_drift_text(drift: list[object]) -> list[str]:
    lines = ["Drift:"]
    for finding in drift:
        assert isinstance(finding, dict)
        kind = finding["kind"]
        if kind == "constitution_stale":
            lines.append("  the composed constitution is stale")
        elif kind == "revision_mismatch":
            pinned = finding["pinned"]
            installed = finding["installed"]
            lines.append(
                f"  {finding['molecule_id']}: revision mismatch "
                f"(pinned {pinned['revision']}, installed {installed['revision']})"
            )
        else:
            lines.append(f"  {finding['molecule_id']}: {_DRIFT_PHRASE[kind]}")
    lines.append("  → run `spaex install` to reconcile")
    return lines


def run_trace(args: argparse.Namespace) -> int:
    """`spaex trace <path>` (contracts/status-and-trace-cli.md §"spaex trace")."""
    repo_root = Path(args.repo_root).resolve()
    fmt = getattr(args, "format", None) or "text"

    attribution = resolve_trace_query(repo_root, str(args.path))
    record = _build_trace_record(attribution)

    if fmt == "json":
        sys.stdout.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(_render_trace_text(record))
    return exit_codes.SUCCESS if attribution.matches else 1


def _render_owner(owner: MoleculeOwner) -> dict[str, object]:
    return {"molecule_id": owner.molecule_id, "source": owner.source, "revision": owner.revision}


def _render_path_ownership(match: PathOwnership) -> dict[str, object]:
    return {
        "path": match.path,
        "owners": [_render_owner(owner) for owner in match.owners],
        "constitution_trace_hint": match.constitution_trace_hint,
    }


def _build_trace_record(attribution: FileAttribution) -> dict[str, object]:
    return {
        "format_version": 1,
        "query": attribution.query,
        "kind": attribution.kind,
        "matches": [_render_path_ownership(m) for m in attribution.matches],
        "error": attribution.error,
    }


def _render_trace_text(record: dict[str, object]) -> str:
    if record["error"] is not None:
        return (
            f"No molecule is recorded for {record['query']}.\n"
            "Hand-written files and files created by a molecule's install_hook "
            "are not\ntracked by spaex.\n"
        )
    matches = record["matches"]
    assert isinstance(matches, list)
    blocks = [_render_path_ownership_text(match) for match in matches]
    return "\n\n".join(blocks) + "\n"


def _render_path_ownership_text(match: object) -> str:
    assert isinstance(match, dict)
    owners = match["owners"]
    lines = [f"Path: {match['path']}"]
    if len(owners) == 1:
        owner = owners[0]
        lines.append("Owner:")
        lines.append(
            f"  {owner['molecule_id']}@{owner['revision'][:8]} (recorded in .spaex/install.lock)"
        )
    else:
        lines.append(f"Owners ({len(owners)}):")
        for owner in owners:
            lines.append(f"  {owner['molecule_id']}@{owner['revision'][:8]}")
    if match["constitution_trace_hint"]:
        lines.append("")
        lines.append("For clause-level provenance, run `spaex constitution trace <query>`.")
    return "\n".join(lines)
