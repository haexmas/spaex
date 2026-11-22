"""Spec 023 behavior CLI subcommands.

Exposes the `spaex install --global` handler plus the Phase 10 CLI-polish
subcommands: `spaex constitution build` (T055) and `spaex constitution
trace` (T056), both per contracts/cli-surface.md.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from spaex.behavior import bootstrap
from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior import render as behavior_render
from spaex.behavior import state as behavior_state
from spaex.behavior.composer.invoke import COMPOSER_LOG_ENV, DEFAULT_COMPOSER_LOG
from spaex.behavior.decisions import DECISIONS_FILENAME
from spaex.behavior.fragment import (
    PROJECT_SCOPE,
    BehaviorFragment,
    FragmentValidationError,
)
from spaex.behavior.materialize import project_local_from_config
from spaex.behavior.passages import canonical_lines
from spaex.cli.install import _load_consumer_manifest
from spaex.constitution.resolve import ResolvedMolecule, resolve_install_inputs
from spaex.io.state import default_state_root
from spaex.model.consumer_manifest import ConsumerManifest, flatten_compound_pins
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
    """`spaex constitution build` (T055, reworked by Spec 030).

    Renders `.spaex/constitution.md` from the current fragments and the
    persisted decisions, standing in for the behavior-harness slice of a full
    `spaex install` (no Spec 008 `constitution.md`/hooks/`install.lock`
    publish here). The check runs only when no completed one covers the
    current fragments; `--force` reruns it, and `--check` compares the file
    with a fresh render and the check state without ever calling the model.
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
        force_check=force,
    )
    _report_constitution_build(outcome)
    return exit_codes.SUCCESS


_CHECK_MESSAGES = {
    "missing": "is missing",
    "version": "is format version 1 (out of date)",
    "out-of-date": "differs from a fresh render of the fragments and decisions",
    "unchecked": "is current, but no completed contradiction check covers these fragments",
}


def _check_build(
    *,
    repo_root: Path,
    state_root: Path,
    resolved: Sequence[ResolvedMolecule],
    project_local: Sequence[BehaviorFragment],
) -> int:
    """`--check` without `--force`: compare the file with a fresh render.

    Never invokes the model (contracts/cli-surface-delta.md): the expected
    text is a pure function of the fragments and the valid decisions, and the
    check state is read from `decisions.json`.
    """
    assessment = behavior_orchestrate.current_assessment(
        repo_root=repo_root,
        state_root=state_root,
        resolved=resolved,
        project_local=project_local,
    )
    path = composed_constitution_path(repo_root)
    if assessment is None:
        if not path.exists():
            sys.stdout.write(
                "spaex constitution build --check: no active fragments, "
                ".spaex/constitution.md is absent as expected\n"
            )
            return exit_codes.SUCCESS
        sys.stdout.write(
            "spaex constitution build --check: .spaex/constitution.md exists but "
            "no fragment is active; run `spaex constitution build` to remove it\n"
        )
        return 1
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    try:
        diagnosis = behavior_state.diagnose(assessment, existing)
    except behavior_render.RenderError as exc:
        sys.stdout.write(
            "spaex constitution build --check: saved decisions conflict; "
            f"{exc}\n"
        )
        return 1
    if diagnosis == "current":
        sys.stdout.write(
            "spaex constitution build --check: .spaex/constitution.md is current\n"
        )
        return exit_codes.SUCCESS
    sys.stdout.write(
        f"spaex constitution build --check: .spaex/constitution.md "
        f"{_CHECK_MESSAGES[diagnosis]}; run `spaex install` or "
        "`spaex constitution build` to fix it\n"
    )
    return 1


def _force_check_build(
    *,
    repo_root: Path,
    state_root: Path,
    resolved: Sequence[ResolvedMolecule],
    project_local: Sequence[BehaviorFragment],
) -> int:
    """`--force --check`: an explicit fresh comparison. Reruns the check via
    `force_check=True`, then reports whether the freshly rendered
    `.spaex/constitution.md` matches what was already on disk.

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
                force_check=True,
            )
            after = spaex_md_path.read_bytes() if spaex_md_path.exists() else None
            matches = before == after
        finally:
            _restore_managed_artifacts(snapshots)

    if matches:
        sys.stdout.write(
            "spaex constitution build --force --check: a fresh check and render "
            "match the committed .spaex/constitution.md\n"
        )
        return exit_codes.SUCCESS
    sys.stdout.write(
        "spaex constitution build --force --check: a fresh check and render "
        "produced different output; .spaex/constitution.md left unchanged "
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
        spaex_dir / DECISIONS_FILENAME,
        *(spaex_dir / name for name in behavior_orchestrate.LEGACY_FILENAMES),
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
    if outcome.published and not outcome.skipped_check:
        sys.stdout.write(
            f"composed .spaex/constitution.md ({outcome.fragment_count} fragment(s), "
            f"{outcome.decision_count} decision(s))\n"
        )
    elif outcome.skipped_check:
        sys.stdout.write(
            f"reused .spaex/constitution.md ({outcome.fragment_count} fragment(s), "
            "fragments and decisions unchanged, no check needed)\n"
        )
    elif outcome.removed_constitution:
        sys.stdout.write("removed .spaex/constitution.md (no active fragments)\n")
    else:
        sys.stdout.write(
            "spaex constitution build: nothing to do (no fragments)\n"
        )


def run_constitution_trace(args: argparse.Namespace) -> int:
    """`spaex constitution trace <query>` (T056, reworked by Spec 030 research R11).

    `query` is an exact scoped fragment id (`<molecule-id>/<fragment-id>`), a
    molecule id, or a phrase from a fragment. A bare `<fragment-id>` (no
    molecule scope) that matches a known fragment id is rejected as ambiguous
    rather than silently treated as a phrase.
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

    text = spaex_md_path.read_text(encoding="utf-8")
    try:
        document = behavior_render.parse(text)
    except behavior_render.RenderError as exc:
        return _emit_trace_result(
            fmt,
            matches=(),
            error=(
                f".spaex/constitution.md is not a format version 2 constitution ({exc}); "
                "run `spaex install` or `spaex constitution build`"
            ),
        )
    if document.version != behavior_render.FORMAT_VERSION or not document.blocks:
        return _emit_trace_result(
            fmt,
            matches=(),
            error=(
                f".spaex/constitution.md is format version {document.version}, not "
                f"{behavior_render.FORMAT_VERSION}; run `spaex install` or "
                "`spaex constitution build`"
            ),
        )
    blocks = document.blocks
    scoped_ids = {block.scoped_id for block in blocks}
    molecule_ids = {scoped_id.split("/", 1)[0] for scoped_id in scoped_ids}
    fragment_ids = {scoped_id.split("/", 1)[1] for scoped_id in scoped_ids if "/" in scoped_id}

    matches: list[_TraceMatch]
    if "/" in query and query in scoped_ids:
        matches = [_TraceMatch(block) for block in blocks if block.scoped_id == query]
    elif "/" not in query and query in molecule_ids:
        matches = [
            _TraceMatch(block)
            for block in blocks
            if block.scoped_id.split("/", 1)[0] == query
        ]
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
        matches = _phrase_matches(blocks, query, repo_root=repo_root)

    if not matches:
        return _emit_trace_result(fmt, matches=(), error=f"no fragment matches {query!r}")

    molecule_pins = _load_molecule_pins(repo_root)
    return _emit_trace_result(
        fmt, matches=tuple(matches), molecule_pins=molecule_pins, repo_root=repo_root
    )


@dataclass(frozen=True)
class _TraceMatch:
    """A traced fragment block, or one line of it when found by phrase."""

    block: behavior_render.ParsedBlock
    line: int | None = None
    line_text: str | None = None
    excluded_kept: tuple[str, ...] | None = None


def _phrase_matches(
    blocks: Sequence[behavior_render.ParsedBlock],
    phrase: str,
    *,
    repo_root: Path,
) -> list[_TraceMatch]:
    found: list[_TraceMatch] = []
    for block in blocks:
        molecule_id, _, fragment_id = block.scoped_id.partition("/")
        fragment_path = (
            repo_root
            / ".spaex"
            / CONSTITUTION_D_DIRNAME
            / molecule_id
            / f"{fragment_id}.md"
        )
        try:
            fragment = BehaviorFragment.from_file(
                fragment_path, molecule_id=molecule_id
            )
            lines = canonical_lines(fragment.body)
        except (OSError, UnicodeError, FragmentValidationError):
            lines = block.body.split("\n")
            if lines and lines[-1] == "":
                lines.pop()
        excluded_offsets: list[tuple[int, int, tuple[str, ...]]] = []
        for prior_markers, exclusion in enumerate(block.exclusions):
            start = exclusion.file_start - block.start_line + 1 - prior_markers * 2
            end = start + len(exclusion.text_lines) - 1
            excluded_offsets.append((start, end, exclusion.kept))
        for source_number, line in enumerate(lines, start=1):
            if phrase not in line:
                continue
            inside = next(
                (
                    (start, end, kept)
                    for start, end, kept in excluded_offsets
                    if start <= source_number <= end
                ),
                None,
            )
            extra_markers = sum(
                1 if start <= source_number <= end else 2 if end < source_number else 0
                for start, end, _kept in excluded_offsets
            )
            number = block.start_line + source_number - 1 + extra_markers
            found.append(
                _TraceMatch(
                    block,
                    line=number,
                    line_text=line,
                    excluded_kept=inside[2] if inside is not None else None,
                )
            )
    return found


def _emit_trace_result(
    fmt: str,
    *,
    matches: tuple[_TraceMatch, ...],
    error: str | None = None,
    molecule_pins: dict[str, tuple[str, str]] | None = None,
    repo_root: Path | None = None,
) -> int:
    """Write matching fragments in the requested format and return the trace exit code."""
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
        _render_match(match, repo_root=repo_root, molecule_pins=molecule_pins)
        for match in matches
    ]
    if fmt == "json":
        sys.stdout.write(
            json.dumps({"matches": records}, indent=2, sort_keys=True) + "\n"
        )
    else:
        blocks = [_render_match_text(record, repo_root=repo_root) for record in records]
        sys.stdout.write("\n\n".join(blocks) + "\n")
    return exit_codes.SUCCESS


def _render_match(
    match: _TraceMatch,
    *,
    repo_root: Path,
    molecule_pins: dict[str, tuple[str, str]],
) -> dict[str, object]:
    """Build a provenance record for a fragment block or a line inside it."""
    scoped_id = match.block.scoped_id
    molecule_id, _, fragment_id = scoped_id.partition("/")
    source: dict[str, object] = {
        "scoped_id": scoped_id,
        "atom_source": _lookup_atom_source(repo_root, molecule_id, fragment_id),
    }
    if molecule_id == PROJECT_SCOPE:
        source["project_local"] = True
    else:
        pin = molecule_pins.get(molecule_id)
        if pin is not None:
            source["molecule_source"] = pin[0]
            source["molecule_revision"] = pin[1]
            source["pinned_in"] = _manifest_display_path(repo_root)
    record: dict[str, object] = {
        "source": source,
        "modality": match.block.modality,
        "lines": [match.block.start_line, match.block.end_line],
        "exclusions": [
            {"lines": [e.file_start, e.file_end], "kept": list(e.kept)}
            for e in match.block.exclusions
        ],
    }
    if match.line is not None:
        record["line"] = match.line
        record["text"] = match.line_text
        record["excluded"] = match.excluded_kept is not None
        if match.excluded_kept is not None:
            record["kept"] = list(match.excluded_kept)
    return record


def _render_match_text(record: dict[str, object], *, repo_root: Path) -> str:
    source = record["source"]
    assert isinstance(source, dict)
    lines_range = record["lines"]
    assert isinstance(lines_range, list)
    lines = [f"Fragment: {source['scoped_id']}"]
    if "line" in record:
        lines.append(f"Line:     {record['line']}: {record['text']}")
        if record.get("excluded"):
            lines.append(f"Excluded: yes, kept {', '.join(record['kept'])}")  # type: ignore[arg-type]
    lines.append(
        f"Lines:    {lines_range[0]}-{lines_range[1]} of .spaex/constitution.md"
    )
    if record.get("modality"):
        lines.append(f"Modality: {record['modality']}")
    lines.append(f"Atom:     {source.get('atom_source') or '(unavailable)'}")
    if source.get("project_local"):
        lines.append(
            "Molecule: (project-local fragment; declared in "
            f"{_manifest_display_path(repo_root)}'s constitution.local_fragments)"
        )
    elif "molecule_source" in source:
        lines.append(
            f"Molecule: {source['molecule_source']}@"
            f"{source['molecule_revision']} (pinned in {source['pinned_in']})"
        )
    else:
        lines.append(
            "Molecule: (unknown; not found in "
            f"{_manifest_display_path(repo_root)})"
        )
    exclusions = record["exclusions"]
    assert isinstance(exclusions, list)
    for exclusion in exclusions:
        lines.append(
            f"Excluded passage: lines {exclusion['lines'][0]}-{exclusion['lines'][1]}, "
            f"kept {', '.join(exclusion['kept'])}"
        )
    return "\n".join(lines)


def _lookup_atom_source(
    repo_root: Path, molecule_id: str, fragment_id: str
) -> str | None:
    """Read `atom_source` from the materialized fragment file.

    Not carried by `.spaex/constitution.md` itself, so this reads
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
    return flatten_compound_pins(manifest)


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


def maybe_emit_local_bootstrap_hint() -> None:
    """Spec 029: a local behavior document needs bootstrap block version 3 or newer.

    Emits one stderr hint when no runtime carries the current block, so the
    operator's agents would not read `.spaex/local/constitution.md`.
    """
    for runtime in bootstrap.ALL_RUNTIMES:
        try:
            if bootstrap.check([runtime]):
                return
        except HaexError:
            continue
    sys.stderr.write(
        "hint: run `spaex install --global` so agent runtimes also read "
        ".spaex/local/constitution.md (bootstrap block version "
        f"{bootstrap.BLOCK_VERSION})\n"
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
