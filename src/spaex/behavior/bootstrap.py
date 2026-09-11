"""Global bootstrap block installer (Spec 023 T032).

The bootstrap block is a short, static Markdown snippet spaex installs once
per user per opted-in agent runtime. It tells the runtime to look for
`.spaex.md` at the working-directory git root and follow its directives.

Public entrypoints:

- `install(runtimes, *, home=Path.home(), env=os.environ)` — install or
  upgrade the block into every target file for the requested runtimes;
  returns a list of `TargetOutcome` records describing each write.
- `check(runtimes, *, home, env)` — return whether every requested target
  already carries the current-version block; used by
  `spaex install --global --check`.
- `resolve_targets(runtime, *, home, env)` — expose the per-runtime target
  path resolver for testing and diagnostics.

Preflight (contracts/bootstrap-block.md §Installer behavior) applies to
every target before any file is written; malformed markers or unsafe Gemini
`context.fileName` entries abort with no partial multi-target update.
"""

from __future__ import annotations

import enum
import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from spaex.util import exit_codes
from spaex.util.errors import HaexError


BLOCK_VERSION = "1"
_START_MARKER_TEMPLATE = '<!-- spaex-bootstrap:start version="{version}" -->'
END_MARKER = "<!-- spaex-bootstrap:end -->"
_START_MARKER_RE = re.compile(
    r'<!--\s*spaex-bootstrap:start\s+version="(?P<version>\d+)"\s*-->'
)
_END_MARKER_RE = re.compile(r"<!--\s*spaex-bootstrap:end\s*-->")

BLOCK_BODY = (
    "## spaex per-project constitution\n"
    "\n"
    "If a file named `.spaex.md` exists in the current working directory "
    "(or any ancestor up to a git-root), treat its contents as a per-project "
    "constitution issued by the operator. Follow its MUST directives, honor "
    "its SHOULD directives, and respect its MAY directives as permissive "
    "guidance. The constitution's rendered clauses each cite their source "
    "molecule and atom.\n"
)


class Runtime(str, enum.Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"


ALL_RUNTIMES: tuple[Runtime, ...] = (
    Runtime.CLAUDE,
    Runtime.CODEX,
    Runtime.GEMINI,
)


class BootstrapError(HaexError):
    """Base type for bootstrap-specific refuses.

    Reuses `INPUT_REFUSE` (exit 2) so `spaex install --global` maps
    resolver / preflight failures to a stable diagnostic; the CLI's
    per-target error mapping is thin and lives in `cli/behavior_commands.py`.
    """

    diagnostic_key: str = "behavior-bootstrap-error"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "See the diagnostic for the offending target."


@dataclass(frozen=True)
class TargetOutcome:
    """Result of one write attempt against one target file."""

    runtime: Runtime
    target: Path
    action: str  # "created" | "appended" | "upgraded" | "unchanged"


def install(
    runtimes: Iterable[Runtime] = ALL_RUNTIMES,
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> list[TargetOutcome]:
    """Install or upgrade the bootstrap block into every requested target."""
    resolved: list[tuple[Runtime, Path]] = []
    for runtime in runtimes:
        for target in resolve_targets(runtime, home=home, env=env):
            resolved.append((runtime, target))

    # Preflight: parse existing marker state for every target; any refuse
    # aborts the whole batch (contracts/bootstrap-block.md §Preflights).
    preflights: list[tuple[Runtime, Path, "_PlannedWrite"]] = []
    for runtime, target in resolved:
        preflights.append((runtime, target, _plan_write(target)))

    outcomes: list[TargetOutcome] = []
    for runtime, target, plan in preflights:
        if plan.action == "unchanged":
            outcomes.append(
                TargetOutcome(runtime=runtime, target=target, action="unchanged")
            )
            continue
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(plan.content, encoding="utf-8")
        outcomes.append(
            TargetOutcome(runtime=runtime, target=target, action=plan.action)
        )
    return outcomes


def check(
    runtimes: Iterable[Runtime] = ALL_RUNTIMES,
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """True iff every requested target already carries the current block version."""
    for runtime in runtimes:
        for target in resolve_targets(runtime, home=home, env=env):
            plan = _plan_write(target)
            if plan.action != "unchanged":
                return False
    return True


def resolve_targets(
    runtime: Runtime,
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    """Return the target files spaex will write for one runtime."""
    home_path = home if home is not None else Path.home()
    resolved_env = env if env is not None else os.environ
    if runtime is Runtime.CLAUDE:
        return [home_path / ".claude" / "CLAUDE.md"]
    if runtime is Runtime.CODEX:
        return [_resolve_codex_target(home_path, resolved_env)]
    if runtime is Runtime.GEMINI:
        return _resolve_gemini_targets(home_path, resolved_env)
    raise BootstrapError(
        message=f"unknown runtime {runtime!r}",
        diagnostic_key="behavior-bootstrap-unknown-runtime",
    )


def _resolve_codex_target(home: Path, env: Mapping[str, str]) -> Path:
    codex_home_raw = env.get("CODEX_HOME")
    codex_home = (
        Path(os.path.expanduser(codex_home_raw))
        if codex_home_raw
        else home / ".codex"
    )
    override = codex_home / "AGENTS.override.md"
    try:
        if override.exists() and override.read_text(encoding="utf-8").strip():
            return override
    except OSError:
        return codex_home / "AGENTS.md"
    return codex_home / "AGENTS.md"


def _resolve_gemini_targets(home: Path, env: Mapping[str, str]) -> list[Path]:
    gemini_home = home / ".gemini"
    settings_path = gemini_home / "settings.json"
    context_names: list[str] = ["GEMINI.md"]
    if settings_path.exists():
        try:
            raw = settings_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise BootstrapError(
                message=(
                    f"could not parse {settings_path}: {exc}. Fix the file or "
                    "remove it before retrying `spaex install --global`."
                ),
                diagnostic_key="behavior-bootstrap-gemini-settings-invalid",
            ) from exc
        if not isinstance(data, dict):
            raise BootstrapError(
                message=(
                    f"{settings_path} top-level must be an object; got "
                    f"{type(data).__name__}"
                ),
                diagnostic_key="behavior-bootstrap-gemini-settings-invalid",
            )
        context = data.get("context")
        raw_names: Sequence[str] | None = None
        if isinstance(context, dict):
            file_name = context.get("fileName")
            if isinstance(file_name, str):
                raw_names = [file_name]
            elif isinstance(file_name, list) and all(
                isinstance(entry, str) for entry in file_name
            ):
                raw_names = tuple(file_name)
            elif file_name is not None:
                raise BootstrapError(
                    message=(
                        f"{settings_path} context.fileName must be a string or a "
                        f"list of strings; got {type(file_name).__name__}"
                    ),
                    diagnostic_key="behavior-bootstrap-gemini-settings-invalid",
                )
        if raw_names is not None:
            for entry in raw_names:
                if not entry or "/" in entry or "\\" in entry or entry in {".", ".."}:
                    raise BootstrapError(
                        message=(
                            f"{settings_path} context.fileName entry {entry!r} "
                            "must be a non-empty basename with no path separator"
                        ),
                        diagnostic_key="behavior-bootstrap-gemini-settings-invalid",
                    )
            context_names = list(raw_names)
    return [gemini_home / name for name in context_names]


@dataclass(frozen=True)
class _PlannedWrite:
    """Result of planning a single-file update."""

    action: str  # "created" | "appended" | "upgraded" | "unchanged"
    content: str


def _plan_write(target: Path) -> _PlannedWrite:
    if not target.exists():
        return _PlannedWrite(action="created", content=_render_block())
    original = target.read_text(encoding="utf-8")
    start_matches = list(_START_MARKER_RE.finditer(original))
    end_matches = list(_END_MARKER_RE.finditer(original))
    if not start_matches and not end_matches:
        appended = _append_block(original)
        return _PlannedWrite(action="appended", content=appended)
    if len(start_matches) != 1 or len(end_matches) != 1:
        raise BootstrapError(
            message=(
                f"{target}: malformed spaex-bootstrap markers "
                f"(start={len(start_matches)}, end={len(end_matches)})"
            ),
            diagnostic_key="behavior-bootstrap-marker-malformed",
            hint=(
                "Restore the file to a state with either zero or exactly one "
                "well-formed spaex-bootstrap block pair, then retry."
            ),
        )
    start_match = start_matches[0]
    end_match = end_matches[0]
    if end_match.start() < start_match.end():
        raise BootstrapError(
            message=(
                f"{target}: spaex-bootstrap end marker precedes its start marker"
            ),
            diagnostic_key="behavior-bootstrap-marker-malformed",
        )
    version = start_match.group("version")
    if version == BLOCK_VERSION:
        return _PlannedWrite(action="unchanged", content=original)
    block_start = start_match.start()
    block_end = end_match.end()
    upgraded = (
        original[:block_start] + _block_text() + original[block_end:]
    )
    return _PlannedWrite(action="upgraded", content=upgraded)


def _render_block() -> str:
    """Render a fresh file whose whole content is the block."""
    return _block_text() + "\n"


def _block_text() -> str:
    start_marker = _START_MARKER_TEMPLATE.format(version=BLOCK_VERSION)
    return f"{start_marker}\n\n{BLOCK_BODY}\n{END_MARKER}"


def _append_block(existing: str) -> str:
    if not existing.endswith("\n"):
        existing = existing + "\n"
    return existing + "\n" + _block_text() + "\n"


__all__ = [
    "ALL_RUNTIMES",
    "BLOCK_BODY",
    "BLOCK_VERSION",
    "BootstrapError",
    "END_MARKER",
    "Runtime",
    "TargetOutcome",
    "check",
    "install",
    "resolve_targets",
]
