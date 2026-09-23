"""Consumer-selected external skill adapter boundary (Spec 018 US3).

`external_skills` references are provider metadata; the installer choice
belongs to the consumer's `skill_installation` policy
(`spaex.model.consumer_manifest.SkillInstallationPolicy`), never to the
provider molecule manifest. This module never hardcodes behavior for a
specific real-world tool (`skillsmd`, the Vercel `skills` CLI, ...): the
`adapter` field names an executable spaex resolves on `PATH`, exactly like
`spaex.install.hook_runner` resolves a hook's interpreter. The one
recognized sentinel is `"manual"`, meaning the consumer installs the
referenced skills by hand and no subprocess is launched.

Each adapter invocation gets exactly one resolved molecule's pinned
`manifest.json` path via `SPAEX_MOLECULE_MANIFEST` (FR-010): spaex creates
no second serialized copy of `external_skills`. The adapter runs with
`cwd` set to the consumer repo root, so it can also read the persisted
`skill_installation` policy from `.spaex/manifest.json` directly; spaex
does not synthesize adapter-specific argv from `scope`/`agents` (FR-006).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from spaex.constitution.resolve import ResolvedMolecule
from spaex.model.consumer_manifest import SkillInstallationPolicy
from spaex.util.errors import SkillAdapterFailedError, SkillAdapterUnavailableError

MANUAL_ADAPTER = "manual"
MOLECULE_MANIFEST_ENV = "SPAEX_MOLECULE_MANIFEST"


def pending_external_skill_molecules(
    resolved: Sequence[ResolvedMolecule],
) -> tuple[ResolvedMolecule, ...]:
    """Return every resolved molecule declaring at least one external skill."""
    return tuple(
        record
        for record in resolved
        if record.molecule_manifest is not None and record.molecule_manifest.external_skills
    )


@dataclass(frozen=True)
class AdapterInvocation:
    """One completed adapter invocation for one pending molecule."""

    molecule_id: str
    manual: bool


def invoke_adapter(
    policy: SkillInstallationPolicy,
    pending: Sequence[ResolvedMolecule],
    *,
    repo_root: Path,
) -> tuple[AdapterInvocation, ...]:
    """Run the consumer-selected adapter once per pending molecule.

    Raises before launching anything if the adapter is not `"manual"` and
    is not resolvable on `PATH` (FR-006: no fallback to another installer).
    Stops at the first non-zero adapter exit (no built-in retry/rollback;
    external side effects from a failed adapter are not spaex's to undo).
    """
    assert policy.adapter is not None, "invoke_adapter requires a resolved adapter"

    if policy.adapter == MANUAL_ADAPTER:
        return tuple(
            AdapterInvocation(molecule_id=record.molecule_id, manual=True)
            for record in pending
        )

    adapter_path = shutil.which(policy.adapter)
    if adapter_path is None:
        raise SkillAdapterUnavailableError(
            message=f"adapter {policy.adapter!r} is not on PATH",
            context={"adapter": policy.adapter},
        )

    invocations: list[AdapterInvocation] = []
    for record in pending:
        assert record.cache_dir is not None, "resolved molecule is missing its cache_dir"
        manifest_path = record.cache_dir / "manifest.json"
        env = {**os.environ, MOLECULE_MANIFEST_ENV: str(manifest_path)}
        try:
            completed = subprocess.run(
                [adapter_path], cwd=repo_root, env=env, check=False
            )
        except OSError as exc:
            raise SkillAdapterFailedError(
                message=f"adapter {policy.adapter!r} failed to launch: {exc}",
                context={"adapter": policy.adapter, "molecule_id": record.molecule_id},
            ) from exc
        if completed.returncode != 0:
            raise SkillAdapterFailedError(
                message=(
                    f"adapter {policy.adapter!r} exited {completed.returncode} "
                    f"for molecule {record.molecule_id!r}"
                ),
                context={
                    "adapter": policy.adapter,
                    "molecule_id": record.molecule_id,
                    "exit_code": str(completed.returncode),
                },
            )
        invocations.append(AdapterInvocation(molecule_id=record.molecule_id, manual=False))
    return tuple(invocations)
