"""Partial multi-batch failure preserves earlier steps' evidence (Spec 026 T007).

Batch 1 of 3 succeeds, batch 2 times out: the whole build aborts as
`behavior-composer-timeout` (FR-008), the previously published constitution
stays byte-unchanged (FR-004), and `$SPAEX_COMPOSER_LOG` still contains
batch 1's completed entry even though batch 2 is the one that failed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spaex.behavior import orchestrate
from spaex.behavior.composer.failure import ComposerTimeoutError
from spaex.behavior.composer.invoke import InvokeOptions
from spaex.constitution.resolve import ResolvedMolecule
from spaex.model.molecule_manifest import MoleculeManifest

_MOLECULE_COUNT = 150  # exceeds the default 40KB byte ceiling -> multiple batches


class MockTimeout(Exception):
    """Named so `_classify_stub_exception` maps it to `timeout`."""


def _resolved_molecule(cache_root: Path, index: int) -> ResolvedMolecule:
    """Create one cached resolved molecule for a multi-batch run."""
    mol_id = f"mol-{index:03d}"
    cache_dir = cache_root / mol_id
    (cache_dir / "fragments").mkdir(parents=True)
    (cache_dir / "fragments" / "rule.md").write_text(
        "---\nid: rule\nkind: constitution_fragment\n"
        f"atom_source: pkg.{mol_id}\nmodality: MUST\n---\n"
        f"**MUST** follow rule {index}.\n",
        encoding="utf-8",
    )
    manifest = MoleculeManifest(
        spaex_version="4",
        id=mol_id,
        version="1.0.0",
        priority=20,
        atoms={"behavior": ("fragments/rule.md",)},
    )
    return ResolvedMolecule(
        molecule_id=mol_id,
        source_url="https://example.invalid/fixture",
        revision="0" * 40,
        repo_dir=cache_root,
        molecule_path=mol_id,
        install_hook=None,
        effective_priority=20,
        molecule_manifest=manifest,
        cache_dir=cache_dir,
    )


def _shape_a_response(payload: str) -> str:
    """Compose every fragment in a batch payload into Shape A."""
    data = json.loads(payload)
    bullets = "\n".join(
        f"- {f['body'].strip()} _[from `{f['molecule_id']}/{f['fragment_id']}`]_"
        for f in data["fragments"]
    )
    body = f"## MUST\n\n{bullets}\n"
    return (
        "<<<SPAEX-COMPOSER-BEGIN>>>\n"
        '{"type": "composed", "questions": []}\n'
        "<<<SPAEX-COMPOSER-END>>>\n\n" + body
    )


def test_batch_2_of_3_timeout_preserves_batch_1_log_and_leaves_constitution_untouched(
    tmp_path: Path,
) -> None:
    """Preserve prior output and earlier logs when the second batch times out."""
    repo = tmp_path / "repo"
    (repo / ".spaex").mkdir(parents=True)
    previously_published = "old composed constitution, must survive untouched\n"
    (repo / ".spaex" / "constitution.md").write_text(previously_published, encoding="utf-8")

    resolved = [_resolved_molecule(tmp_path / "cache", i) for i in range(_MOLECULE_COUNT)]

    calls = {"n": 0}

    def stub(runtime: str, prompt: str, payload: str, timeout: float) -> str:
        """Succeed once, then simulate the second batch timing out."""
        calls["n"] += 1
        if calls["n"] == 1:
            return _shape_a_response(payload)
        raise MockTimeout("simulated batch-2 timeout")

    log_path = repo / ".spaex" / "composer.log"

    with pytest.raises(ComposerTimeoutError):
        orchestrate.run(
            repo_root=repo,
            state_root=tmp_path / "state",
            resolved=resolved,
            invoke_options=InvokeOptions(stub_caller=stub, composer_log_path=log_path),
        )

    assert calls["n"] == 2, "batch-3 must never be dispatched once batch-2 fails"
    assert (
        repo / ".spaex" / "constitution.md"
    ).read_text(encoding="utf-8") == previously_published

    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    assert entries[0]["step"] == "batch-1"
    assert entries[0]["outcome"] == "composed"
