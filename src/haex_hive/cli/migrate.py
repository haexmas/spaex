"""`haex migrate` handler.

Spec 007 originally landed the v1 → v2 transform for `.haex-hive.json`.
Spec 013 T053-T056 extends the command to chain v1 → v2 → v3 for the
consumer manifest and to apply v2 → v3 to every publisher-root and
per-molecule ``manifest.json`` visible under the repo. Every proposal
lands as a ``.migrated`` sibling per Principle VI's review-gate
discipline; originals are never touched. All proposals produced by one
invocation are registered so a failure inside the invocation unlinks
them (Spec 013 T052 registry).
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from haex_hive.cli.diagnostics import emit_refuse
from haex_hive.io import json_deterministic
from haex_hive.migrate import sidecar, transform, walker
from haex_hive.migrate.registry import ProposalRegistry
from haex_hive.migrate.v2_to_v3 import v2_to_v3
from haex_hive.util import exit_codes
from haex_hive.util.errors import HaexError, UsageError


def _state_root() -> Path:
    if os.environ.get("HAEX_HIVE_STATE"):
        return Path(os.environ["HAEX_HIVE_STATE"])
    return Path.home() / ".local" / "share" / "haex-hive"


@dataclass
class _InputOutcome:
    kind: str  # walker.MigrationInput.kind
    source: Path
    proposal: Path
    outcome: str  # "noop" | "proposal" | "refused"
    diff: str = ""
    proposal_bytes: bytes = b""
    refusal: HaexError | None = None


def _detect_version(raw: bytes) -> int | None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("haex_hive_version")
    if version in ("1", "2", "3"):
        return int(version)
    return None


def _unified_diff(before: bytes, after: bytes, name: str) -> str:
    def normalize_line_endings(raw: bytes) -> str:
        return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")

    before_lines = normalize_line_endings(before).splitlines(keepends=True)
    after_lines = normalize_line_endings(after).splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=name,
        tofile=name + ".migrated",
        lineterm="",
    )
    return "".join(line if line.endswith("\n") else line + "\n" for line in diff)


def _classify_input(
    entry: walker.MigrationInput, repo_root: Path, state_root: Path
) -> _InputOutcome:
    version = _detect_version(entry.raw)
    if version == 3:
        return _InputOutcome(
            kind=entry.kind,
            source=entry.source,
            proposal=entry.proposal,
            outcome="noop",
        )

    try:
        if entry.kind == "consumer" and version == 1:
            v2_bytes = transform.migrate_v1_to_v2(entry.raw, repo_root, state_root)
            v2_data = json.loads(v2_bytes.decode("utf-8"))
            transform.validate_v2_consumer_manifest(v2_data)
            v3_data = v2_to_v3(v2_data)
        else:
            data = json.loads(entry.raw.decode("utf-8"))
            v3_data = v2_to_v3(data)
        proposal_bytes = json_deterministic.dumps(v3_data)
    except HaexError as exc:
        return _InputOutcome(
            kind=entry.kind,
            source=entry.source,
            proposal=entry.proposal,
            outcome="refused",
            refusal=exc,
        )
    except (UnicodeError, ValueError) as exc:
        return _InputOutcome(
            kind=entry.kind,
            source=entry.source,
            proposal=entry.proposal,
            outcome="refused",
            refusal=HaexError(
                message=f"{entry.source} is not valid JSON: {exc}",
                context={"path": str(entry.source)},
                diagnostic_key="haex-hive-json-invalid",
                exit_code=exit_codes.INPUT_REFUSE,
            ),
        )

    diff = _unified_diff(
        entry.raw, proposal_bytes, str(entry.source.relative_to(repo_root))
    )
    return _InputOutcome(
        kind=entry.kind,
        source=entry.source,
        proposal=entry.proposal,
        outcome="proposal",
        diff=diff,
        proposal_bytes=proposal_bytes,
    )


def _invocation_exit_code(outcomes: list[_InputOutcome]) -> int:
    has_refusal = any(o.outcome == "refused" for o in outcomes)
    has_proposal = any(o.outcome == "proposal" for o in outcomes)
    if has_refusal and not has_proposal:
        return exit_codes.INPUT_REFUSE  # 2 — hard refusal
    if has_refusal and has_proposal:
        return 1  # mixed
    return exit_codes.SUCCESS


def _emit_proposals(outcomes: list[_InputOutcome], registry: ProposalRegistry) -> None:
    try:
        for outcome in outcomes:
            if outcome.outcome != "proposal":
                continue
            if outcome.kind == "consumer":
                sidecar.publish_sidecar(outcome.source.parent, outcome.proposal_bytes)
                registry.register(outcome.proposal)
            else:
                registry.emit(outcome.proposal, outcome.proposal_bytes)
    except OSError:
        registry.rollback()
        raise


def run(args: argparse.Namespace) -> int:
    if args.dry_run and args.check:
        emit_refuse(UsageError(message="--dry-run and --check are mutually exclusive"))
        return exit_codes.USAGE

    repo_root = Path(args.repo_root).resolve()
    write_mode = not (args.dry_run or args.check)
    v1_path = repo_root / ".haex-hive.json"

    if not v1_path.exists():
        emit_refuse(
            HaexError(
                message=f".haex-hive.json not found in {repo_root}",
                context={"path": str(v1_path)},
                diagnostic_key="haex-hive-json-missing",
                exit_code=exit_codes.SYSTEM_REFUSE,
                hint="Run this command inside a repo containing .haex-hive.json.",
            )
        )
        return exit_codes.SYSTEM_REFUSE

    if write_mode:
        sidecar.invalidate_stale_sidecar(repo_root)

    state_root = _state_root()
    outcomes: list[_InputOutcome] = []
    for entry in walker.walk_local_manifests(repo_root):
        try:
            outcomes.append(_classify_input(entry, repo_root, state_root))
        except HaexError as exc:
            outcomes.append(
                _InputOutcome(
                    kind=entry.kind,
                    source=entry.source,
                    proposal=entry.proposal,
                    outcome="refused",
                    refusal=exc,
                )
            )

    if all(o.outcome == "noop" for o in outcomes):
        sys.stderr.write("already at v3 (nothing to migrate)\n")
        return exit_codes.SUCCESS

    if write_mode:
        registry = ProposalRegistry()
        try:
            _emit_proposals(outcomes, registry)
            registry.commit()
        except Exception:
            registry.rollback()
            raise

    for outcome in outcomes:
        if outcome.outcome == "proposal":
            sys.stdout.write(outcome.diff)
        elif outcome.outcome == "refused" and outcome.refusal is not None:
            emit_refuse(
                outcome.refusal,
                extra={"path": str(outcome.source.relative_to(repo_root))},
            )

    return _invocation_exit_code(outcomes)
