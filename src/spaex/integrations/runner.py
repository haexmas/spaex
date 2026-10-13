"""Shell-free command construction for external integration runners."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from spaex.model.molecule_manifest import SpeckitDeclaration
from spaex.model.version_constraint import VersionConstraint

CliExecutable = str | Sequence[str]


def build_install_argv(
    executable: CliExecutable,
    key: str,
    options: str,
    *,
    force: bool = False,
) -> list[str]:
    """Build a shell-free official install invocation."""
    argv = [executable] if isinstance(executable, str) else list(executable)
    argv.extend(("integration", "install"))
    if force:
        argv.append("--force")
    argv.append(key)
    if options:
        argv.append(f"--integration-options={options}")
    return argv


def build_upgrade_argv(executable: CliExecutable, key: str, options: str) -> list[str]:
    """Build a shell-free official refresh of an installed integration.

    Without ``--force`` the CLI refuses to overwrite locally modified managed
    files, so only missing ones are restored.
    """
    argv = [executable] if isinstance(executable, str) else list(executable)
    argv.extend(("integration", "upgrade", key))
    if options:
        argv.append(f"--integration-options={options}")
    return argv


def build_init_argv(executable: CliExecutable, key: str, options: str) -> list[str]:
    """Build a shell-free official project bootstrap invocation.

    ``--here --force`` merges into the existing, non-empty consumer repo;
    ``--non-interactive`` makes the CLI fail instead of hanging on a prompt.
    """
    argv = [executable] if isinstance(executable, str) else list(executable)
    argv.extend(
        ("init", "--here", "--force", "--non-interactive", "--ignore-agent-tools")
    )
    argv.extend(("--integration", key))
    if options:
        argv.append(f"--integration-options={options}")
    return argv


def resolve_cli_executable(
    declaration: SpeckitDeclaration,
    executable: CliExecutable | None = None,
) -> list[str]:
    """Resolve an override or provision the pinned official CLI through uv."""
    if executable is not None:
        return [executable] if isinstance(executable, str) else list(executable)
    if declaration.cli is None:
        return ["specify"]
    return [
        sys.executable,
        "-m",
        "uv",
        "tool",
        "run",
        "--from",
        f"{declaration.cli.package}=={_version_text(declaration.cli.version)}",
        "specify",
    ]


def _version_text(version: VersionConstraint) -> str:
    major, minor, patch = version.version
    return f"{major}.{minor}.{patch}"
