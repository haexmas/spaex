"""Partial multi-batch failure preserves earlier steps' evidence (Spec 026 T007).

Batch 1 succeeds, every other batch times out: the whole build aborts as
`behavior-composer-timeout` (FR-008), the previously published constitution
stays byte-unchanged (FR-004), and `$SPAEX_COMPOSER_LOG` still contains
batch 1's completed entry even though a sibling batch is the one that
failed. Batches now dispatch concurrently (all of them fire regardless of
a sibling's outcome), so this deliberately fails every batch but the first
rather than pinning "exactly batch 2" — the property under test is that an
already-succeeded batch's evidence survives a sibling's failure, not which
specific batch failed.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from spaex.behavior import orchestrate
from spaex.behavior.composer import batching
from spaex.behavior.composer import reduce as composer_reduce
from spaex.behavior.composer.failure import ComposerTimeoutError
from spaex.behavior.composer.invoke import InvokeOptions
from spaex.behavior.fragment import BehaviorFragment
from spaex.constitution.resolve import ResolvedMolecule
from spaex.model.molecule_manifest import MoleculeManifest

_MOLECULE_COUNT = 150  # exceeds the default 40KB byte ceiling -> multiple batches


class MockTimeout(Exception):
    """Named so `_classify_stub_exception` maps it to `timeout`."""


def _rule_fragment_bytes(mol_id: str, index: int) -> bytes:
    """Raw bytes for one molecule's single rule fragment (shared by the
    on-disk fixture and the in-memory `BehaviorFragment` used to compute the
    real batch split without duplicating `orchestrate.py`'s materialization
    pipeline)."""
    return (
        "---\nid: rule\nkind: constitution_fragment\n"
        f"atom_source: pkg.{mol_id}\nmodality: MUST\n---\n"
        f"**MUST** follow rule {index}.\n"
    ).encode()


def _fragments(resolved: list[ResolvedMolecule]) -> list[BehaviorFragment]:
    """Rebuild the fragments `orchestrate.run()` would materialize for
    `resolved`, so a test can compute the real batch split directly."""
    return [
        BehaviorFragment.from_bytes(
            _rule_fragment_bytes(molecule.molecule_id, i),
            molecule_id=molecule.molecule_id,
            path=f"{molecule.molecule_id}/fragments/rule.md",
        )
        for i, molecule in enumerate(resolved)
    ]


def _resolved_molecule(cache_root: Path, index: int) -> ResolvedMolecule:
    """Create one cached resolved molecule for a multi-batch run."""
    mol_id = f"mol-{index:03d}"
    cache_dir = cache_root / mol_id
    (cache_dir / "fragments").mkdir(parents=True)
    (cache_dir / "fragments" / "rule.md").write_bytes(_rule_fragment_bytes(mol_id, index))
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


def test_sibling_batch_timeout_preserves_batch_1_log_and_leaves_constitution_untouched(
    tmp_path: Path,
) -> None:
    """Preserve prior output and earlier logs when a sibling batch times out."""
    repo = tmp_path / "repo"
    (repo / ".spaex").mkdir(parents=True)
    previously_published = "old composed constitution, must survive untouched\n"
    (repo / ".spaex" / "constitution.md").write_text(previously_published, encoding="utf-8")

    resolved = [_resolved_molecule(tmp_path / "cache", i) for i in range(_MOLECULE_COUNT)]

    dispatched_molecules: set[str] = set()

    def stub(runtime: str, prompt: str, payload: str, timeout: float) -> str:
        """Succeed only for the batch holding mol-000; every sibling times
        out. Decided by content (which molecule a batch actually holds),
        not call-arrival order, since batches dispatch concurrently and
        arrival order isn't deterministic."""
        data = json.loads(payload)
        dispatched_molecules.update(
            fragment["molecule_id"] for fragment in data["fragments"]
        )
        if data["fragments"][0]["molecule_id"] == "mol-000":
            return _shape_a_response(payload)
        raise MockTimeout("simulated sibling-batch timeout")

    log_path = repo / ".spaex" / "composer.log"

    with pytest.raises(ComposerTimeoutError) as excinfo:
        orchestrate.run(
            repo_root=repo,
            state_root=tmp_path / "state",
            resolved=resolved,
            invoke_options=InvokeOptions(stub_caller=stub, composer_log_path=log_path),
        )

    # Concurrent dispatch means every batch fires regardless of a sibling's
    # outcome - unlike sequential dispatch, a later batch is not skipped
    # just because an earlier one already failed.
    assert dispatched_molecules == {f"mol-{i:03d}" for i in range(_MOLECULE_COUNT)}
    assert excinfo.value.context["step"] == "batch-2"
    assert (
        repo / ".spaex" / "constitution.md"
    ).read_text(encoding="utf-8") == previously_published

    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    assert entries[0]["step"] == "batch-1"
    assert entries[0]["outcome"] == "composed"


def test_first_batch_failure_does_not_cancel_not_yet_started_sibling_batches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test for a real bug found via 2026-09-17 real dogfooding.

    `ThreadPoolExecutor.map()`'s result iterator cancels every future it
    has not yet yielded once an earlier one raises (cpython
    `concurrent.futures._base.Executor.map`'s `result_iterator`: `finally:
    for future in fs: future.cancel()`). A future still queued - not yet
    started - *can* be cancelled this way, so it never runs at all,
    silently contradicting `compose()`'s own documented guarantee (ADR
    0023) that "every batch fires regardless of a sibling's outcome".
    Constrains the pool to one worker so batch-2 and batch-3 are still
    queued, not yet started, at the moment batch-1's failure surfaces on
    the main thread - exactly the state `.map()`'s cancellation targets.
    """

    def _single_worker_pool(*_args: object, **_kwargs: object) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(max_workers=1)

    monkeypatch.setattr(composer_reduce, "ThreadPoolExecutor", _single_worker_pool)

    repo = tmp_path / "repo"
    (repo / ".spaex").mkdir(parents=True)
    resolved = [_resolved_molecule(tmp_path / "cache", i) for i in range(_MOLECULE_COUNT)]

    dispatched_molecules: set[str] = set()

    def stub(runtime: str, prompt: str, payload: str, timeout: float) -> str:
        """Fail the first batch immediately; every sibling must still run."""
        data = json.loads(payload)
        if data["fragments"][0]["molecule_id"] == "mol-000":
            raise MockTimeout("batch-1 fails immediately")
        dispatched_molecules.update(
            fragment["molecule_id"] for fragment in data["fragments"]
        )
        return _shape_a_response(payload)

    with pytest.raises(ComposerTimeoutError):
        orchestrate.run(
            repo_root=repo,
            state_root=tmp_path / "state",
            resolved=resolved,
            invoke_options=InvokeOptions(stub_caller=stub),
        )

    # batch-1 (holding mol-000) never reaches the `dispatched_molecules.update`
    # line, since it raises first; every sibling batch must still have run.
    all_molecules = {f"mol-{i:03d}" for i in range(_MOLECULE_COUNT)}
    batches = batching.partition(_fragments(resolved)).batches
    batch_1_molecules = next(
        {f.molecule_id for f in b.fragments}
        for b in batches
        if "mol-000" in {f.molecule_id for f in b.fragments}
    )
    assert len(batches) >= 3, "need a third, not-yet-started batch to prove the fix"
    assert dispatched_molecules == all_molecules - batch_1_molecules
