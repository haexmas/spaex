"""`spaex` CLI root: argparse dispatch + version gate."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
from collections.abc import Sequence
from pathlib import Path

from spaex.cli.diagnostics import emit_refuse
from spaex.install.manifest_lock import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    parse_lock_timeout,
)
from spaex.model.version_constraint import VersionConstraint
from spaex.util import exit_codes
from spaex.util.errors import HaexError, VersionBelowMinError

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def _installed_version() -> tuple[int, int, int]:
    """Return the installed package version as a numeric tuple."""
    try:
        version = importlib.metadata.version("spaex")
    except importlib.metadata.PackageNotFoundError:
        return (2, 0, 0)
    match = _VERSION_RE.match(version)
    if not match:
        return (2, 0, 0)
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


INSTALLED_VERSION = _installed_version()
INSTALLED_VERSION_STRING = ".".join(str(n) for n in INSTALLED_VERSION)


def _check_min_version(repo_root: Path) -> None:
    """Refuse execution when the repository requires a newer spaex version."""
    manifest_path = repo_root / ".spaex.json"
    if not manifest_path.exists():
        return
    try:
        raw = manifest_path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    min_version_raw = data.get("spaex_min_version")
    if not min_version_raw:
        return
    try:
        constraint = VersionConstraint.parse(min_version_raw)
    except ValueError as exc:
        raise VersionBelowMinError(
            message=f"invalid spaex_min_version: {exc}",
        ) from None
    if not constraint.satisfied_by(INSTALLED_VERSION):
        installed = ".".join(str(n) for n in INSTALLED_VERSION)
        raise VersionBelowMinError(
            message=f"installed spaex {installed} does not satisfy {min_version_raw!r}",
            context={"installed": installed, "required": min_version_raw},
        )


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line parser."""
    parser = argparse.ArgumentParser(prog="spaex")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate_help = "rewrite v1, v2, or v3 manifests into their v4 shape (Spec 014)"
    migrate = subparsers.add_parser(
        "migrate",
        help=migrate_help,
        description=migrate_help,
    )
    migrate.add_argument("--dry-run", action="store_true")
    migrate.add_argument("--check", action="store_true")

    constitution = subparsers.add_parser("constitution", help="constitution commands")
    constitution_sub = constitution.add_subparsers(dest="constitution_command", required=True)

    show = constitution_sub.add_parser("show", help="print effective constitution")
    show.add_argument("--no-preface", action="store_true")

    install = subparsers.add_parser(
        "install",
        help="resolve `.spaex.json` molecules and publish a new generation (Spec 008)",
    )
    install.add_argument(
        "--lock-timeout",
        dest="lock_timeout",
        type=parse_lock_timeout,
        default=DEFAULT_LOCK_TIMEOUT_SECONDS,
        help="Manifest-lock timeout in seconds (default 30; 0 = fail-fast)",
    )
    install.add_argument(
        "--no-install-hooks",
        dest="skip_hooks",
        action="store_true",
        help=(
            "Skip per-molecule install_hook execution for this invocation. "
            "Every molecule declaring install_hook records hook_status='skipped' "
            "in install.lock; atoms still materialize. Per-invocation only; "
            "the next `spaex install` without this flag runs the hooks again. "
            "Use for sandboxed / CI runs or when auditing a molecule before "
            "letting its hook touch the repo (Spec 016 FR-026, FR-028)."
        ),
    )
    # Spec 023: --global switches install into bootstrap-block mode; the
    # optional positional accepts a comma-separated runtime list.
    install.add_argument(
        "--global",
        dest="global_mode",
        action="store_true",
        help=(
            "Install/upgrade the global bootstrap block into every configured "
            "runtime's user-global instruction file (contracts/cli-surface.md)."
        ),
    )
    install.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="With --global: print target updates but do not write.",
    )
    install.add_argument(
        "--check",
        dest="check_only",
        action="store_true",
        help=(
            "With --global: exit 0 if every runtime target carries the current "
            "block version, non-zero otherwise (CI provisioning check)."
        ),
    )
    install.add_argument(
        "global_runtimes",
        nargs="?",
        default=None,
        help=(
            "With --global: comma-separated runtime names (claude, codex, "
            "gemini); default is all three."
        ),
    )

    from spaex.cli import add as add_cli

    add_parser = subparsers.add_parser(
        "add",
        help="adopt one or more molecules from a source repository (Spec 013)",
    )
    add_cli.add_arguments(add_parser)

    from spaex.cli import remove as remove_cli

    remove_parser = subparsers.add_parser(
        "remove",
        help="retract one or more molecules from .spaex.json (Spec 013)",
    )
    remove_cli.add_arguments(remove_parser)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, dispatch a command, and render typed refusals."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        _check_min_version(args.repo_root)
    except HaexError as exc:
        emit_refuse(exc)
        return exc.exit_code

    try:
        if args.command == "migrate":
            from spaex.cli import migrate as migrate_cli

            return migrate_cli.run(args)
        if args.command == "constitution":
            from spaex.cli import constitution as constitution_cli

            if args.constitution_command == "show":
                return constitution_cli.run_show(args)
        if args.command == "install":
            if getattr(args, "global_mode", False):
                from spaex.cli import behavior_commands

                return behavior_commands.run_install_global(args)
            from spaex.cli import install as install_cli

            return install_cli.run(args)
        if args.command == "add":
            from spaex.cli import add as add_cli

            return add_cli.run(args)
        if args.command == "remove":
            from spaex.cli import remove as remove_cli

            return remove_cli.run(args)
    except HaexError as exc:
        emit_refuse(exc)
        return exc.exit_code

    parser.error(f"unknown command: {args.command}")
    return exit_codes.USAGE
