"""`spaex skills install` / `spaex skills configure` (Spec 018 US3).

Normal `spaex install` never invokes an external skill adapter (FR-011); it
only reports `external_skills` references as pending (see
`spaex.cli.install`). These two commands are the sole way a consumer
activates installation, choosing and persisting a `skill_installation`
policy in `.spaex/manifest.json` (contracts/consumer-manifest-skill-installation.v1.md).
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from spaex.cli.install import _load_consumer_manifest
from spaex.constitution.resolve import ResolvedMolecule, resolve_install_inputs
from spaex.install.manifest_lock import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    ManifestLockContext,
    active_manifest_lock_path,
)
from spaex.io import atomic
from spaex.io.state import default_state_root
from spaex.model.consumer_manifest import ConsumerManifest, SkillInstallationPolicy
from spaex.paths import manifest_path
from spaex.skills import installer as skills_installer
from spaex.util import exit_codes
from spaex.util.errors import (
    InteractiveSelectionUnavailableError,
    SkillInstallationCancelledError,
    SkillInstallationPersistError,
    UsageError,
)

_MODES = ("prompt", "managed", "disabled")
_SCOPES = ("project", "global")


def _read_line(prompt: str) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    return sys.stdin.readline().strip()


def _require_line(prompt: str) -> str:
    """Read one line; blank input (including EOF) cancels the operation."""
    raw = _read_line(prompt)
    if not raw:
        raise SkillInstallationCancelledError(
            message="no input received; skill installation configuration cancelled"
        )
    return raw


def _prompt_policy() -> SkillInstallationPolicy:
    mode = _require_line(f"Skill installation mode [{'/'.join(_MODES)}]: ").lower()
    if mode not in _MODES:
        raise UsageError(message=f"invalid skill installation mode: {mode!r}")
    if mode == "disabled":
        return SkillInstallationPolicy(mode="disabled")

    adapter = _require_line(
        "Adapter identifier (e.g. skillsmd, vercel-cli, manual): "
    )
    scope = _require_line(f"Installation scope [{'/'.join(_SCOPES)}]: ").lower()
    if scope not in _SCOPES:
        raise UsageError(message=f"invalid installation scope: {scope!r}")
    agents_raw = _require_line("Target agent id(s), comma-separated: ")
    agents: list[str] = []
    for token in agents_raw.split(","):
        token = token.strip()
        if token and token not in agents:
            agents.append(token)
    if not agents:
        raise SkillInstallationCancelledError(
            message="no target agent id given; skill installation configuration cancelled"
        )
    return SkillInstallationPolicy(mode=mode, adapter=adapter, scope=scope, agents=tuple(agents))


def _persist_policy(
    repo_root: Path, manifest: ConsumerManifest, policy: SkillInstallationPolicy
) -> None:
    """Write the accepted policy before any adapter runs (FR-014)."""
    updated = dataclasses.replace(manifest, skill_installation=policy)
    try:
        atomic.write_replace(manifest_path(repo_root), updated.to_json_bytes())
    except OSError as exc:
        raise SkillInstallationPersistError(
            message=f"failed to persist skill_installation policy: {exc}"
        ) from exc


def _report_invocations(
    policy: SkillInstallationPolicy, invocations: tuple[skills_installer.AdapterInvocation, ...]
) -> None:
    if not invocations:
        return
    if policy.adapter == skills_installer.MANUAL_ADAPTER:
        for invocation in invocations:
            sys.stdout.write(
                f"pending external skill for {invocation.molecule_id}; install manually\n"
            )
        return
    for invocation in invocations:
        sys.stdout.write(
            f"installed external skill for {invocation.molecule_id} via {policy.adapter}\n"
        )


def run_install(args: argparse.Namespace) -> int:
    """`spaex skills install` — activate the consumer's skill_installation policy."""
    repo_root = Path(args.repo_root).resolve()
    state_root = default_state_root()
    lock = ManifestLockContext(
        active_manifest_lock_path(repo_root), timeout_seconds=DEFAULT_LOCK_TIMEOUT_SECONDS
    )
    with lock:
        manifest = _load_consumer_manifest(repo_root)
        _, resolved = resolve_install_inputs(manifest, state_root)
        pending: tuple[ResolvedMolecule, ...] = skills_installer.pending_external_skill_molecules(
            resolved
        )
        if not pending:
            sys.stdout.write("no external skill references are pending\n")
            return exit_codes.SUCCESS

        policy = manifest.skill_installation
        if policy is not None and policy.mode == "disabled":
            sys.stdout.write(
                "skill installation is disabled; run `spaex skills configure` to change it\n"
            )
            return exit_codes.SUCCESS

        if policy is None or policy.mode == "prompt":
            if not sys.stdin.isatty():
                raise InteractiveSelectionUnavailableError(
                    message=(
                        "no managed skill_installation policy is persisted and "
                        "stdin is not a TTY; cannot prompt interactively"
                    ),
                    hint="Run `spaex skills configure` in an interactive session first.",
                )
            policy = _prompt_policy()
            _persist_policy(repo_root, manifest, policy)
            if policy.mode == "disabled":
                sys.stdout.write("skill installation is disabled\n")
                return exit_codes.SUCCESS

        invocations = skills_installer.invoke_adapter(policy, pending, repo_root=repo_root)
        _report_invocations(policy, invocations)
        return exit_codes.SUCCESS


def run_configure(args: argparse.Namespace) -> int:
    """`spaex skills configure` — change the persisted policy; never installs."""
    repo_root = Path(args.repo_root).resolve()
    with ManifestLockContext(
        active_manifest_lock_path(repo_root), timeout_seconds=DEFAULT_LOCK_TIMEOUT_SECONDS
    ):
        manifest = _load_consumer_manifest(repo_root)
        if not sys.stdin.isatty():
            raise InteractiveSelectionUnavailableError(
                message="stdin is not a TTY; cannot prompt interactively",
                hint="Run `spaex skills configure` in an interactive session.",
            )
        policy = _prompt_policy()
        _persist_policy(repo_root, manifest, policy)
        sys.stdout.write(f"skill_installation policy saved (mode={policy.mode})\n")
        return exit_codes.SUCCESS
