"""Spec 023 behavior CLI subcommands.

Exposes the `spaex install --global` handler plus the Phase 10 CLI-polish
subcommands: `spaex constitution build` (T055) and `spaex constitution
trace` (T056), both per contracts/cli-surface.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from spaex.behavior import bootstrap
from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior.composer.clarifications import CLARIFICATIONS_FILENAME
from spaex.behavior.composer.invoke import COMPOSER_LOG_ENV, DEFAULT_COMPOSER_LOG
from spaex.behavior.emit import read_header_hashes
from spaex.behavior.fragment import (
    PROJECT_SCOPE,
    BehaviorFragment,
    FragmentValidationError,
)
from spaex.behavior.materialize import project_local_from_config
from spaex.behavior.stale import STALE_FILENAME
from spaex.cli.install import _load_consumer_manifest
from spaex.constitution.resolve import ResolvedMolecule, resolve_install_inputs
from spaex.io.state import default_state_root
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.paths import composed_constitution_path, manifest_path
from spaex.util import exit_codes
from spaex.util.errors import HaexError

CONSTITUTION_D_DIRNAME = "constitution.d"


def run_install_global(args: argparse.Namespace) -> int:
    """Install / upgrade / check the global bootstrap block per runtime."""
    runtimes_arg = getattr(args, "global_runtimes", None)
    runtimes = _parse_runtimes(runtimes_arg)
    dry_run = bool(getattr(args, "dry_run", False))
    check_only = bool(getattr(args, "check_only", False))

    if check_only:
        ok = bootstrap.check(runtimes)
        if ok:
            sys.stdout.write(
                "spaex bootstrap: every target is at the current version\n"
            )
            return exit_codes.SUCCESS
        sys.stdout.write(
            "spaex bootstrap: at least one target is missing or older\n"
        )
        return 1

    try:
        outcomes = bootstrap.install(runtimes, dry_run=dry_run)
    except bootstrap.BootstrapError:
        raise
    for outcome in outcomes:
        sys.stdout.write(
            f"{outcome.runtime.value:<8} {outcome.action:<10} {outcome.target}\n"
        )
    return exit_codes.SUCCESS


def run_constitution_build(args: argparse.Namespace) -> int:
    """`spaex constitution build` (T055, contracts/cli-surface.md
    §"spaex constitution build").

    Explicitly invokes the Composer against the current fragment set and
    writes `.spaex/constitution.md`, standing in for the behavior-harness slice of a full
    `spaex install` (no Spec 008 `constitution.md`/hooks/`install.lock`
    publish here). Reuses `behavior_orchestrate.run()`'s fingerprint
    comparison and Composer-invocation machinery unchanged; `--force` maps
    to `run()`'s `force_composer` and `--check` (without `--force`) uses
    `compute_fingerprints()` to compare without ever invoking the Composer.
    """
    repo_root = Path(args.repo_root).resolve()
    state_root = default_state_root()
    force = bool(getattr(args, "force", False))
    check_only = bool(getattr(args, "check_only", False))

    manifest = _load_consumer_manifest(repo_root)
    project_local = project_local_from_config(
        getattr(manifest, "local_fragments", ()), repo_root=repo_root
    )
    _contributions, resolved = resolve_install_inputs(manifest, state_root)

    if check_only and force:
        return _force_check_build(
            repo_root=repo_root,
            state_root=state_root,
            resolved=resolved,
            project_local=project_local,
        )
    if check_only:
        return _check_build(
            repo_root=repo_root,
            state_root=state_root,
            resolved=resolved,
            project_local=project_local,
        )

    outcome = behavior_orchestrate.run(
        repo_root=repo_root,
        state_root=state_root,
        resolved=resolved,
        project_local=project_local,
        force_composer=force,
    )
    _report_constitution_build(outcome)
    return exit_codes.SUCCESS


def _check_build(
    *,
    repo_root: Path,
    state_root: Path,
    resolved: Sequence[ResolvedMolecule],
    project_local: Sequence[BehaviorFragment],
) -> int:
    """`--check` without `--force`: fingerprint comparison only.

    Never invokes the Composer, matching contracts/cli-surface.md's
    explicit prohibition ("With matching fingerprints it MUST NOT invoke
    the Composer").
    """
    fingerprints = behavior_orchestrate.compute_fingerprints(
        repo_root=repo_root,
        state_root=state_root,
        resolved=resolved,
        project_local=project_local,
    )
    spaex_md_exists = composed_constitution_path(repo_root).exists()
    if fingerprints.source_hash is None:
        match = not spaex_md_exists
    else:
        existing = read_header_hashes(repo_root)
        match = existing is not None and existing == (
            fingerprints.source_hash,
            fingerprints.build_input_hash,
        )
    if match:
        sys.stdout.write(
            "spaex constitution build --check: .spaex/constitution.md is current\n"
        )
        return exit_codes.SUCCESS
    sys.stdout.write(
        "spaex constitution build --check: .spaex/constitution.md is stale "
        "(source_hash/build_input_hash differ); run `spaex constitution "
        "build` to regenerate\n"
    )
    return 1


def _force_check_build(
    *,
    repo_root: Path,
    state_root: Path,
    resolved: Sequence[ResolvedMolecule],
    project_local: Sequence[BehaviorFragment],
) -> int:
    """`--force --check`: an explicit fresh Composer comparison
    (contracts/cli-surface.md). Forces a real Composer invocation via
    `force_composer=True`, then reports whether the freshly composed
    `.spaex/constitution.md` matches what was already on disk (the regenerate-then-diff
    pattern SC-003 reproducibility verification calls for).

    `--check` never mutates the repository, even combined with `--force`:
    a CI-verification flag that silently rewrites a committed file on
    drift would be a footgun (the classic lockfile-drift-check pattern is
    always read-only). Any change from the fresh rebuild is reverted
    before returning; only the exit code reports drift.
    """
    spaex_md_path = composed_constitution_path(repo_root)
    with TemporaryDirectory(prefix=".spaex-force-check-", dir=repo_root) as temp_dir:
        snapshots = _snapshot_managed_artifacts(repo_root, Path(temp_dir))
        before = spaex_md_path.read_bytes() if spaex_md_path.exists() else None
        try:
            behavior_orchestrate.run(
                repo_root=repo_root,
                state_root=state_root,
                resolved=resolved,
                project_local=project_local,
                force_composer=True,
            )
            after = spaex_md_path.read_bytes() if spaex_md_path.exists() else None
            matches = before == after
        finally:
            _restore_managed_artifacts(snapshots)

    if matches:
        sys.stdout.write(
            "spaex constitution build --force --check: a fresh Composer "
            "rebuild matches the committed .spaex/constitution.md\n"
        )
        return exit_codes.SUCCESS
    sys.stdout.write(
        "spaex constitution build --force --check: a fresh Composer "
        "rebuild produced different output; .spaex/constitution.md left unchanged "
        "(rerun `spaex constitution build --force` to persist it)\n"
    )
    return 1


@dataclass(frozen=True)
class _ManagedArtifactSnapshot:
    """One managed path and its copy captured before a check-only rebuild."""

    path: Path
    backup: Path | None
    is_directory: bool = False


def _snapshot_managed_artifacts(
    repo_root: Path, snapshot_root: Path
) -> tuple[_ManagedArtifactSnapshot, ...]:
    """Capture all behavior artifacts, including paths that are absent."""
    snapshots: list[_ManagedArtifactSnapshot] = []
    for index, path in enumerate(_managed_artifact_paths(repo_root)):
        if not os.path.lexists(path):
            snapshots.append(_ManagedArtifactSnapshot(path=path, backup=None))
            continue
        backup = snapshot_root / str(index)
        if path.is_dir() and not path.is_symlink():
            shutil.copytree(path, backup)
            snapshots.append(
                _ManagedArtifactSnapshot(path=path, backup=backup, is_directory=True)
            )
        else:
            shutil.copy2(path, backup, follow_symlinks=False)
            snapshots.append(_ManagedArtifactSnapshot(path=path, backup=backup))
    return tuple(snapshots)


def _restore_managed_artifacts(
    snapshots: Sequence[_ManagedArtifactSnapshot],
) -> None:
    """Restore every captured path after a check-only rebuild."""
    for snapshot in snapshots:
        _remove_artifact(snapshot.path)
        if snapshot.backup is None:
            continue
        snapshot.path.parent.mkdir(parents=True, exist_ok=True)
        if snapshot.is_directory:
            shutil.copytree(snapshot.backup, snapshot.path)
        else:
            shutil.copy2(snapshot.backup, snapshot.path, follow_symlinks=False)


def _remove_artifact(path: Path) -> None:
    """Remove a file, symlink, or directory before restoring its snapshot."""
    if not os.path.lexists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _managed_artifact_paths(repo_root: Path) -> tuple[Path, ...]:
    """Return every repository artifact that a Composer build can mutate."""
    spaex_dir = repo_root / behavior_orchestrate.SPAEX_DIR
    paths = [
        composed_constitution_path(repo_root),
        spaex_dir / behavior_orchestrate.CONSTITUTION_D_DIRNAME,
        spaex_dir / CLARIFICATIONS_FILENAME,
        spaex_dir / STALE_FILENAME,
        spaex_dir / behavior_orchestrate.STAGING_DIRNAME,
        spaex_dir / behavior_orchestrate.PREV_DIRNAME,
    ]
    raw_log_path = os.environ.get(COMPOSER_LOG_ENV)
    if raw_log_path:
        log_path = Path(raw_log_path)
        if not log_path.is_absolute():
            log_path = Path.cwd() / log_path
    else:
        log_path = repo_root / DEFAULT_COMPOSER_LOG
    if log_path not in paths:
        paths.append(log_path)
    return tuple(paths)


def _report_constitution_build(outcome: behavior_orchestrate.BehaviorOutcome) -> None:
    if outcome.published and not outcome.skipped_composer:
        sys.stdout.write(
            f"composed .spaex/constitution.md ({outcome.fragment_count} fragment(s))\n"
        )
    elif outcome.skipped_composer:
        sys.stdout.write(
            f"reused .spaex/constitution.md ({outcome.fragment_count} fragment(s), "
            "source_hash/build_input_hash unchanged)\n"
        )
    elif outcome.removed_constitution:
        sys.stdout.write("removed .spaex/constitution.md (no active fragments)\n")
    else:
        sys.stdout.write(
            "spaex constitution build: nothing to do (no fragments)\n"
        )


_MODALITY_ORDER: tuple[str, ...] = (
    "MUST",
    "MUST_NOT",
    "SHOULD",
    "SHOULD_NOT",
    "MAY",
    "MAY_NOT",
)
_SECTION_HEADER_RE = re.compile(r"^## (?P<modality>[A-Z_]+)\s*$")
_CLAUSE_RE = re.compile(
    r"^- (?P<text>.+?)\. _\[from (?P<provenance>`[^`]+`(?:, `[^`]+`)*)\]_$"
)
_PROVENANCE_ID_RE = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class _TracedClause:
    """One `.spaex/constitution.md` clause parsed for `spaex constitution trace`."""

    modality: str
    text: str
    provenance: tuple[str, ...]


def _parse_clauses(body: str) -> list[_TracedClause]:
    """Parse every clause in a composed `.spaex/constitution.md` body.

    Follows contracts/spaex-md-format.md's stable clause regex under each
    `##` modality section header; lines outside a recognized section (the
    title and italic notice lines) are ignored.
    """
    clauses: list[_TracedClause] = []
    current_modality: str | None = None
    for line in body.splitlines():
        section_match = _SECTION_HEADER_RE.match(line)
        if section_match and section_match.group("modality") in _MODALITY_ORDER:
            current_modality = section_match.group("modality")
            continue
        if current_modality is None:
            continue
        clause_match = _CLAUSE_RE.match(line)
        if clause_match is None:
            continue
        provenance = tuple(
            _PROVENANCE_ID_RE.findall(clause_match.group("provenance"))
        )
        clauses.append(
            _TracedClause(
                modality=current_modality,
                text=clause_match.group("text"),
                provenance=provenance,
            )
        )
    return clauses


def run_constitution_trace(args: argparse.Namespace) -> int:
    """`spaex constitution trace <query>` (T056, FR-022,
    contracts/cli-surface.md §"spaex constitution trace").

    `query` is either an exact scoped fragment id (`<molecule-id>/
    <fragment-id>`, found verbatim in some clause's provenance) or a
    substring of a clause's text. A bare `<fragment-id>` (no molecule
    scope) that matches a known fragment id is rejected as ambiguous
    rather than silently treated as a substring query.
    """
    repo_root = Path(args.repo_root).resolve()
    query = str(args.query)
    fmt = getattr(args, "format", None) or "text"

    spaex_md_path = composed_constitution_path(repo_root)
    if not spaex_md_path.exists():
        return _emit_trace_result(
            fmt,
            matches=(),
            error=(
                "no .spaex/constitution.md found; run `spaex install` or "
                "`spaex constitution build` first"
            ),
        )

    body = spaex_md_path.read_text(encoding="utf-8")
    clauses = _parse_clauses(body)
    scoped_ids = {scoped_id for clause in clauses for scoped_id in clause.provenance}
    fragment_ids = {
        scoped_id.split("/", 1)[1] for scoped_id in scoped_ids if "/" in scoped_id
    }

    if "/" in query and query in scoped_ids:
        matches = tuple(c for c in clauses if query in c.provenance)
    elif "/" not in query and query in fragment_ids:
        return _emit_trace_result(
            fmt,
            matches=(),
            error=(
                f"{query!r} is a bare fragment id, which is ambiguous across "
                "molecules; provide <molecule-id>/<fragment-id> instead"
            ),
        )
    else:
        matches = tuple(c for c in clauses if query in c.text)

    if not matches:
        return _emit_trace_result(
            fmt, matches=(), error=f"no clause matches {query!r}"
        )

    molecule_pins = _load_molecule_pins(repo_root)
    return _emit_trace_result(
        fmt, matches=matches, molecule_pins=molecule_pins, repo_root=repo_root
    )


def _emit_trace_result(
    fmt: str,
    *,
    matches: tuple[_TracedClause, ...],
    error: str | None = None,
    molecule_pins: dict[str, tuple[str, str]] | None = None,
    repo_root: Path | None = None,
) -> int:
    if not matches:
        if fmt == "json":
            sys.stdout.write(
                json.dumps({"matches": [], "error": error}, indent=2) + "\n"
            )
        else:
            sys.stdout.write(f"{error}\n")
        return 1

    assert molecule_pins is not None
    assert repo_root is not None
    records = [
        _render_clause(clause, repo_root=repo_root, molecule_pins=molecule_pins)
        for clause in matches
    ]
    if fmt == "json":
        sys.stdout.write(
            json.dumps({"matches": records}, indent=2, sort_keys=True) + "\n"
        )
    else:
        blocks = [_render_clause_text(record, repo_root=repo_root) for record in records]
        sys.stdout.write("\n\n".join(blocks) + "\n")
    return exit_codes.SUCCESS


def _render_clause(
    clause: _TracedClause,
    *,
    repo_root: Path,
    molecule_pins: dict[str, tuple[str, str]],
) -> dict[str, object]:
    sources: list[dict[str, object]] = []
    for scoped_id in clause.provenance:
        molecule_id, _, fragment_id = scoped_id.partition("/")
        atom_source = _lookup_atom_source(repo_root, molecule_id, fragment_id)
        source: dict[str, object] = {
            "scoped_id": scoped_id,
            "atom_source": atom_source,
        }
        if molecule_id == PROJECT_SCOPE:
            source["project_local"] = True
        else:
            pin = molecule_pins.get(molecule_id)
            if pin is not None:
                source["molecule_source"] = pin[0]
                source["molecule_revision"] = pin[1]
                source["pinned_in"] = _manifest_display_path(repo_root)
        sources.append(source)
    return {"modality": clause.modality, "text": clause.text, "sources": sources}


def _render_clause_text(record: dict[str, object], *, repo_root: Path) -> str:
    lines = [
        f'Directive: "{record["text"]}."',
        f"Modality:  {record['modality']}",
        "Sources:",
    ]
    sources = record["sources"]
    assert isinstance(sources, list)
    for source in sources:
        lines.append(f"  - {source['scoped_id']}")
        atom_source = source.get("atom_source") or "(unavailable)"
        lines.append(f"    Atom:    {atom_source}")
        if source.get("project_local"):
            lines.append(
                "    Molecule: (project-local fragment; declared in "
                f"{_manifest_display_path(repo_root)}'s constitution.local_fragments)"
            )
        elif "molecule_source" in source:
            lines.append(
                f"    Molecule: {source['molecule_source']}@"
                f"{source['molecule_revision']} (pinned in "
                f"{source['pinned_in']})"
            )
        else:
            lines.append(
                "    Molecule: (unknown; not found in "
                f"{_manifest_display_path(repo_root)})"
            )
    return "\n".join(lines)


def _lookup_atom_source(
    repo_root: Path, molecule_id: str, fragment_id: str
) -> str | None:
    """Read `atom_source` from the materialized fragment file.

    Not available from `.spaex/constitution.md` itself (only the composed clause text
    and scoped provenance ids are), so this reads
    `.spaex/constitution.d/<molecule-id>/<fragment-id>.md` back, per
    fragment-format.md's header schema. Returns `None` when the fragment
    file is missing or unparseable (e.g. a stale composed Constitution after the
    fragment was removed) rather than failing the whole trace.
    """
    path = (
        repo_root
        / ".spaex"
        / CONSTITUTION_D_DIRNAME
        / molecule_id
        / f"{fragment_id}.md"
    )
    if not path.exists():
        return None
    try:
        fragment = BehaviorFragment.from_file(path, molecule_id=molecule_id)
    except (OSError, FragmentValidationError):
        return None
    return fragment.atom_source


def _load_molecule_pins(repo_root: Path) -> dict[str, tuple[str, str]]:
    """Best-effort `molecule_id -> (source, revision)` map from the manifest.

    Returns an empty map when the manifest is missing or invalid:
    `constitution trace`'s own exit codes are only 0/1
    (contracts/cli-surface.md §"spaex constitution trace"), so an unrelated
    manifest problem must not fail the whole command.
    """
    path = manifest_path(repo_root)
    if not path.exists():
        return {}
    try:
        manifest = ConsumerManifest.from_json(path.read_bytes())
    except (OSError, ValueError, KeyError):
        return {}
    pins: dict[str, tuple[str, str]] = {}
    for compound in manifest.compounds:
        for molecule_id in compound.molecules:
            pins[molecule_id] = (compound.source, compound.revision)
    return pins


def _manifest_display_path(repo_root: Path) -> str:
    """Return the active manifest path for human-readable provenance output."""
    return manifest_path(repo_root).relative_to(repo_root).as_posix()


def maybe_emit_no_bootstrap_hint() -> None:
    """T036: point the operator at `spaex install --global` when none present.

    Called at the end of a per-project install. Runs `bootstrap.check` for
    every default runtime; if none carry the block, emits one stderr hint.
    Safe to call unconditionally; a broken resolver (e.g. malformed Gemini
    settings) is silently ignored so a bad user config never breaks the
    per-project install.
    """
    for runtime in bootstrap.ALL_RUNTIMES:
        try:
            if bootstrap.check([runtime]):
                return
        except HaexError:
            continue
    sys.stderr.write(
        "hint: no runtime global bootstrap detected on this machine; "
        "run `spaex install --global` so agent runtimes discover "
        ".spaex/constitution.md "
        "(FR-023, contracts/cli-surface.md)\n"
    )


def _parse_runtimes(raw: str | None) -> list[bootstrap.Runtime]:
    if not raw:
        return list(bootstrap.ALL_RUNTIMES)
    names = [name.strip() for name in raw.split(",") if name.strip()]
    parsed: list[bootstrap.Runtime] = []
    for name in names:
        try:
            parsed.append(bootstrap.Runtime(name))
        except ValueError as exc:
            raise HaexError(
                message=(
                    f"unknown runtime {name!r}; expected one of "
                    f"{[r.value for r in bootstrap.ALL_RUNTIMES]}"
                ),
                diagnostic_key="behavior-bootstrap-unknown-runtime",
                exit_code=exit_codes.USAGE,
                hint="Pass a comma-separated list of claude, codex, gemini.",
            ) from exc
    return parsed


__all__ = [
    "maybe_emit_no_bootstrap_hint",
    "run_constitution_build",
    "run_constitution_trace",
    "run_install_global",
]
