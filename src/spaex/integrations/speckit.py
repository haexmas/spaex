"""Typed boundary around the official Spec Kit integration installer.

spaex owns declaration validation, selection, provenance, and diagnostics. The
official ``specify`` CLI owns agent-specific files, layouts, and conflict
behavior; this module never copies a Spec Kit skill itself.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TextIO

from spaex.constitution.resolve import ResolvedMolecule
from spaex.integrations.runner import (
    CliExecutable,
    build_install_argv,
    resolve_cli_executable,
)
from spaex.model.install_lock import InstallLock, SpeckitLockRecord, SpeckitOutcomeStatus
from spaex.model.molecule_manifest import SpeckitDeclaration
from spaex.model.version_constraint import VersionConstraint
from spaex.util.errors import (
    SpeckitCliFailedError,
    SpeckitCliMissingError,
    SpeckitCliVersionIncompatibleError,
    SpeckitDeclarationConflictError,
    SpeckitIntegrationUnsupportedError,
    SpeckitSelectionRequiredError,
)

_VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")
_KEY_RE = re.compile(r"^│\s*([a-z0-9][a-z0-9-]*)\s+│")


@dataclass(frozen=True)
class SpeckitCliResult:
    """Captured result from one official CLI command."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class SpeckitInstallRecords(Mapping[str, SpeckitLockRecord]):
    """CLI results plus the lock records safe to publish for this run."""

    results: Mapping[str, SpeckitLockRecord]
    publication_records: Mapping[str, SpeckitLockRecord]

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", MappingProxyType(dict(self.results)))
        object.__setattr__(
            self,
            "publication_records",
            MappingProxyType(dict(self.publication_records)),
        )

    def __getitem__(self, key: str) -> SpeckitLockRecord:
        return self.results[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)


def parse_version_output(output: str) -> tuple[int, int, int]:
    """Extract the first semantic version from official CLI output."""
    match = _VERSION_RE.search(output)
    if match is None:
        raise ValueError("specify output did not contain a semantic version")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def parse_supported_integrations(output: str) -> tuple[str, ...]:
    """Parse integration keys from the official table output."""
    keys = sorted(
        {match.group(1) for line in output.splitlines() if (match := _KEY_RE.search(line))}
    )
    return tuple(keys)


def parse_selection(raw: str, declared: set[str] | Sequence[str]) -> tuple[str, ...]:
    """Parse ``all``, ``none``, or a comma-separated declared-key selection."""
    declared_set = set(declared)
    value = raw.strip().lower()
    if value == "all":
        return tuple(sorted(declared_set))
    if value in {"", "none"}:
        return ()
    selected = tuple(sorted({part.strip() for part in value.split(",") if part.strip()}))
    unknown = sorted(set(selected) - declared_set)
    if unknown:
        raise ValueError(f"unknown Spec Kit integration(s): {', '.join(unknown)}")
    return selected


def select_integrations(
    explicit: str | None,
    declared: Sequence[str],
    *,
    persisted: Sequence[str] | None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> tuple[str, ...]:
    """Select integrations without allowing an implicit multi-agent rollout.

    Concrete explicit selections are trusted because they name the exact
    integrations to install. The special ``all`` shorthand is treated as a
    request to open the interactive selector, so an automated caller cannot
    silently expand a declaration to every supported agent.
    """
    explicit_is_all = explicit is not None and explicit.strip().lower() == "all"
    if explicit is not None and not explicit_is_all:
        try:
            return parse_selection(explicit, declared)
        except ValueError as exc:
            raise SpeckitSelectionRequiredError(message=str(exc)) from exc
    if persisted is not None and not explicit_is_all:
        try:
            return parse_selection(",".join(persisted), declared)
        except ValueError as exc:
            raise SpeckitSelectionRequiredError(message=str(exc)) from exc

    input_stream = stdin if stdin is not None else sys.stdin
    output_stream = stdout if stdout is not None else sys.stdout
    if stdin is None and not input_stream.isatty():
        raise SpeckitSelectionRequiredError(
            message=(
                "Spec Kit integrations require an interactive selection when "
                "`all` was requested; use --speckit-agents with explicit keys "
                "or --no-speckit-integrations"
                if explicit_is_all
                else "Spec Kit integrations are declared but no selection was "
                "provided; use --speckit-agents or --no-speckit-integrations"
            ),
            context={"available": ",".join(sorted(declared))},
        )
    output_stream.write("Spec Kit agents that can receive skills:\n")
    output_stream.write("  " + ", ".join(sorted(declared)) + "\n")
    output_stream.write(
        "Which agents should receive the Spec Kit skills? (all, none, or comma-separated keys): "
    )
    output_stream.flush()
    try:
        raw = input_stream.readline()
    except OSError as exc:
        raise SpeckitSelectionRequiredError(message=f"could not read selection: {exc}") from exc
    try:
        return parse_selection(raw, declared)
    except ValueError as exc:
        raise SpeckitSelectionRequiredError(message=str(exc)) from exc


def declaration_fingerprint(
    declaration: SpeckitDeclaration,
    source: str,
    revision: str,
    config: Mapping[str, object] | None = None,
) -> str:
    """Hash the declaration and immutable molecule identity canonically."""
    declaration_payload: dict[str, object] = {
        "version_constraint": _constraint_text(declaration),
        "integrations": dict(sorted(declaration.integrations.items())),
    }
    # Keep fingerprints byte-compatible for existing declarations that used
    # the default false value; explicit force changes the installation policy.
    if declaration.force:
        declaration_payload["force"] = True
    # Preserve fingerprints in existing locks for declarations without provisioning.
    if declaration.cli is not None:
        declaration_payload["cli"] = {
            "package": declaration.cli.package,
            "version": _constraint_text(declaration.cli.version),
        }
    payload = {
        "declaration": declaration_payload,
        "source": source,
        "revision": revision,
        "config": dict(config or {}),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def run_cli(
    argv: Sequence[str],
    *,
    repo_root: Path,
    capture_output: bool = True,
) -> SpeckitCliResult:
    """Run one official CLI command with inherited visible output semantics."""
    try:
        if capture_output:
            completed = subprocess.run(
                list(argv),
                cwd=repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        else:
            completed = subprocess.run(
                list(argv),
                cwd=repo_root,
                text=True,
                encoding="utf-8",
                check=False,
            )
    except FileNotFoundError as exc:
        raise SpeckitCliMissingError(
            message="the official `specify` executable was not found on PATH",
            context={"executable": argv[0]},
        ) from exc
    except OSError as exc:
        raise SpeckitCliFailedError(
            message=f"could not launch official Spec Kit CLI: {exc}",
            context={"command": " ".join(argv)},
        ) from exc
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if capture_output and stdout:
        sys.stdout.write(stdout)
    if capture_output and stderr:
        sys.stderr.write(stderr)
    return SpeckitCliResult(
        argv=tuple(argv),
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def verify_cli(
    declaration: SpeckitDeclaration,
    *,
    repo_root: Path,
    executable: CliExecutable | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Verify CLI version and supported keys before any install invocation."""
    executable_argv = resolve_cli_executable(declaration, executable)
    version_result = run_cli([*executable_argv, "version"], repo_root=repo_root)
    if version_result.returncode != 0:
        raise SpeckitCliFailedError(
            message="official `specify version` failed",
            context={"exit_code": str(version_result.returncode)},
        )
    try:
        version = parse_version_output(version_result.stdout + "\n" + version_result.stderr)
    except ValueError as exc:
        raise SpeckitCliVersionIncompatibleError(message=str(exc)) from exc
    required = declaration.version_constraint
    if declaration.cli is not None and not declaration.cli.version.satisfied_by(version):
        required = declaration.cli.version
    if not required.satisfied_by(version):
        version_text = ".".join(str(part) for part in version)
        raise SpeckitCliVersionIncompatibleError(
            message=(f"specify CLI {version_text} does not satisfy {_constraint_text(required)!r}"),
            context={"installed": version_text, "required": _constraint_text(required)},
        )

    list_result = run_cli(
        [*executable_argv, "integration", "list"],
        repo_root=repo_root,
    )
    if list_result.returncode != 0:
        raise SpeckitCliFailedError(
            message="official `specify integration list` failed",
            context={"exit_code": str(list_result.returncode)},
        )
    return ".".join(str(part) for part in version), parse_supported_integrations(list_result.stdout)


def _detect_drifted_keys(
    keys: Sequence[str],
    *,
    repo_root: Path,
    executable: Sequence[str],
) -> frozenset[str]:
    """Flag previously-installed integrations whose managed files are gone.

    ``install.lock`` only remembers that an integration was *selected*; it
    never checks whether the official CLI's own output tree (``.claude/``,
    ``.agents/``, ...) still exists on disk. That tree is typically
    per-checkout and gitignored, so a fresh clone, a ``git clean``, or a
    manual deletion all silently desync it from the lock without spaex
    noticing — the next install would otherwise skip these keys forever.
    This asks the official CLI's own health check instead of trusting the
    record.
    """
    result = run_cli([*executable, "integration", "status", "--json"], repo_root=repo_root)
    if result.returncode != 0:
        return frozenset()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(payload, dict):
        return frozenset()
    manifests = payload.get("manifests")
    if not isinstance(manifests, dict):
        return frozenset()
    return frozenset(
        key
        for key in keys
        if not isinstance(manifests.get(key), dict)
        or not manifests[key].get("readable", False)
        or manifests[key].get("missing_files")
    )


def _clear_stale_registrations(repo_root: Path, keys: frozenset[str]) -> None:
    """Drop drifted keys from the official CLI's own installation record.

    As of specify-cli 1.0.6, ``specify integration install <key>`` refuses
    to touch a key it already considers installed — even with ``--force``,
    it just reports "no files changed" and exits 0. Clearing only the
    drifted key's own entry in ``.specify/integration.json`` (never
    touching sibling keys) is what makes the official CLI treat the
    follow-up ``install`` call in ``install_selected`` as a genuine fresh
    install instead of a no-op.
    """
    path = repo_root / ".specify" / "integration.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    installed = data.get("installed_integrations")
    if not isinstance(installed, list):
        return
    remaining = [key for key in installed if key not in keys]
    if remaining == installed:
        return
    data["installed_integrations"] = remaining
    settings = data.get("integration_settings")
    if isinstance(settings, dict):
        for key in keys:
            settings.pop(key, None)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def install_selected(
    declaration: SpeckitDeclaration,
    selected: Sequence[str],
    *,
    repo_root: Path,
    cli_version: str,
    executable: CliExecutable | None = None,
) -> dict[str, SpeckitOutcomeStatus]:
    """Install selected integrations serially through the official CLI."""
    outcomes: dict[str, SpeckitOutcomeStatus] = {}
    cli_executable = resolve_cli_executable(declaration, executable)
    for key in sorted(selected):
        result = run_cli(
            build_install_argv(
                cli_executable,
                key,
                declaration.integrations[key],
                force=declaration.force,
            ),
            repo_root=repo_root,
            capture_output=False,
        )
        if result.returncode != 0:
            raise SpeckitCliFailedError(
                message=f"official Spec Kit installation failed for {key!r}",
                context={"integration": key, "exit_code": str(result.returncode)},
            )
        outcomes[key] = "installed"
    return outcomes


def ensure_supported(selected: Sequence[str], supported: Sequence[str]) -> None:
    """Refuse unsupported keys before any integration install command."""
    unsupported = sorted(set(selected) - set(supported))
    if unsupported:
        raise SpeckitIntegrationUnsupportedError(
            message=(
                f"Spec Kit integration(s) not supported by this CLI: {', '.join(unsupported)}"
            ),
            context={"unsupported": ",".join(unsupported), "available": ",".join(supported)},
        )


def emit_results(records: Mapping[str, SpeckitLockRecord]) -> None:
    """Emit one stable JSON result object for each declared integration."""
    outcomes = [
        {
            "integration": integration,
            "status": status,
            "cli_version": record.cli_version,
            "molecule": molecule_id,
        }
        for molecule_id, record in sorted(records.items())
        for integration, status in sorted(record.outcomes.items())
    ]
    if outcomes:
        sys.stdout.write(json.dumps({"speckit": outcomes}, sort_keys=True) + "\n")


def prepare_install(
    resolved: Sequence[ResolvedMolecule],
    *,
    repo_root: Path,
    existing_lock: InstallLock | None,
    explicit_selection: str | None = None,
    disabled: bool = False,
    executable: CliExecutable | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> SpeckitInstallRecords:
    """Validate declarations, select agents, and install external integrations.

    ``resolved`` is intentionally accepted as a sequence of resolver records
    with the small public attributes used here. Keeping this adapter at the
    resolver boundary avoids coupling the external CLI to constitution files.
    """
    declarations = [
        record
        for record in resolved
        if getattr(getattr(record, "molecule_manifest", None), "speckit", None) is not None
    ]
    if not declarations:
        return SpeckitInstallRecords({}, {})

    first_manifest = declarations[0].molecule_manifest
    assert first_manifest is not None
    first = first_manifest.speckit
    assert first is not None
    for record in declarations[1:]:
        manifest = record.molecule_manifest
        assert manifest is not None
        declaration = manifest.speckit
        assert declaration is not None
        if declaration != first:
            raise SpeckitDeclarationConflictError(
                message="adopted molecules declare incompatible Spec Kit policies",
                context={"molecules": ",".join(sorted(r.molecule_id for r in declarations))},
            )

    fingerprints = {
        record.molecule_id: declaration_fingerprint(first, record.source_url, record.revision)
        for record in declarations
    }
    existing_by_id = {
        entry.id: entry.speckit
        for entry in (existing_lock.molecules if existing_lock is not None else ())
        if entry.speckit is not None
    }
    persisted: tuple[str, ...] | None = None
    for record in declarations:
        previous = existing_by_id.get(record.molecule_id)
        if (
            previous is not None
            and previous.declaration_fingerprint == fingerprints[record.molecule_id]
            and previous.selected
        ):
            # An empty selection is the persisted shape of a skipped or
            # explicitly disabled integration run, not a successful agent
            # choice. Ask again on the next interactive install so adding a
            # Spec Kit molecule cannot silently omit all agent skills.
            persisted = previous.selected
            break

    if disabled:
        skipped_records = {
            record.molecule_id: SpeckitLockRecord(
                cli_version="not-run",
                declaration_fingerprint=fingerprints[record.molecule_id],
                selected=(),
                outcomes={key: "skipped" for key in first.integrations},
            )
            for record in declarations
        }
        publication_records = {
            record.molecule_id: (
                previous
                if (previous := existing_by_id.get(record.molecule_id)) is not None
                and previous.declaration_fingerprint == fingerprints[record.molecule_id]
                else skipped_records[record.molecule_id]
            )
            for record in declarations
        }
        return SpeckitInstallRecords(skipped_records, publication_records)

    selected = select_integrations(
        explicit_selection,
        tuple(first.integrations),
        persisted=persisted,
        stdin=stdin,
        stdout=stdout,
    )
    if not selected:
        skipped_records = {
            record.molecule_id: SpeckitLockRecord(
                cli_version="not-run",
                declaration_fingerprint=fingerprints[record.molecule_id],
                selected=(),
                outcomes={key: "skipped" for key in first.integrations},
            )
            for record in declarations
        }
        return SpeckitInstallRecords(skipped_records, skipped_records)

    cli_executable = resolve_cli_executable(first, executable)
    cli_version, supported = verify_cli(first, repo_root=repo_root, executable=cli_executable)
    ensure_supported(selected, supported)
    existing_for_first = existing_by_id.get(declarations[0].molecule_id)
    already_selected = (
        existing_for_first is not None
        and existing_for_first.declaration_fingerprint == fingerprints[declarations[0].molecule_id]
        and existing_for_first.cli_version == cli_version
    )
    previous_selected = (
        existing_for_first.selected if already_selected and existing_for_first else ()
    )
    carried_over = tuple(key for key in selected if already_selected and key in previous_selected)
    drifted = (
        _detect_drifted_keys(carried_over, repo_root=repo_root, executable=cli_executable)
        if carried_over
        else frozenset()
    )
    if drifted:
        _clear_stale_registrations(repo_root, drifted)
    new_keys = tuple(
        key
        for key in selected
        if not already_selected or key not in previous_selected or key in drifted
    )
    outcomes = install_selected(
        first,
        new_keys,
        repo_root=repo_root,
        cli_version=cli_version,
        executable=cli_executable,
    )
    if existing_for_first is not None and already_selected:
        outcomes = {
            **dict(existing_for_first.outcomes),
            **outcomes,
        }
    records = {
        record.molecule_id: SpeckitLockRecord(
            cli_version=cli_version,
            declaration_fingerprint=fingerprints[record.molecule_id],
            selected=selected,
            outcomes={key: outcomes.get(key, "already_satisfied") for key in selected},
        )
        for record in declarations
    }
    return SpeckitInstallRecords(records, records)


def _constraint_text(declaration: SpeckitDeclaration | VersionConstraint) -> str:
    constraint = (
        declaration.version_constraint
        if isinstance(declaration, SpeckitDeclaration)
        else declaration
    )
    operator = constraint.operator
    major, minor, patch = constraint.version
    return f"{operator if operator == '>=' else ''}{major}.{minor}.{patch}"


__all__ = [
    "SpeckitCliResult",
    "SpeckitInstallRecords",
    "build_install_argv",
    "declaration_fingerprint",
    "emit_results",
    "ensure_supported",
    "install_selected",
    "parse_selection",
    "parse_supported_integrations",
    "parse_version_output",
    "run_cli",
    "resolve_cli_executable",
    "select_integrations",
    "verify_cli",
]
