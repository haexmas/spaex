"""Composition at scale through `orchestrate.run` (Spec 026 T008/T009, reworked by Spec 030 T017).

The entry point is driven with hand-built `ResolvedMolecule` records whose
`cache_dir`/`molecule_manifest` are populated directly, avoiding a real git
publisher clone. Two scenarios:

- many molecules, one check call (stubbed at `check_fragments`): every fragment
  appears verbatim, in scoped-id order, and the decisions file records the check;
- a set above the single-call ceiling, with the real `check_fragments` and a stub
  *runtime*: it is checked group by group and pair by pair, so a conflict between
  molecules that land in different groups is still found, asked once and applied.
"""

from __future__ import annotations

import json
from pathlib import Path

from spaex.behavior import orchestrate
from spaex.behavior.composer.invoke import InvokeOptions
from spaex.behavior.decisions import Choice
from spaex.behavior.render import parse
from spaex.constitution.resolve import ResolvedMolecule
from spaex.model.molecule_manifest import MoleculeManifest

from ..conftest import Operator, StubCheck


def _resolved_molecule(cache_root: Path, index: int, *, filler_lines: int = 0) -> ResolvedMolecule:
    """One cached resolved molecule holding a single fragment `rule`."""
    mol_id = f"mol-{index:03d}"
    cache_dir = cache_root / mol_id
    (cache_dir / "fragments").mkdir(parents=True)
    body = f"**MUST** follow rule {index}.\n" + "".join(
        f"Filler sentence {n} of rule {index} that only adds weight to the payload.\n"
        for n in range(filler_lines)
    )
    (cache_dir / "fragments" / "rule.md").write_text(
        "---\nid: rule\nkind: constitution_fragment\n"
        f"atom_source: pkg.{mol_id}\nmodality: MUST\n---\n{body}",
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


def _run(tmp_path: Path, resolved: list[ResolvedMolecule], **kwargs) -> orchestrate.BehaviorOutcome:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return orchestrate.run(
        repo_root=repo, state_root=tmp_path / "state", resolved=resolved, **kwargs
    )


def test_many_molecules_are_checked_in_one_call_and_rendered_verbatim(
    tmp_path: Path, stub_check: StubCheck
) -> None:
    resolved = [_resolved_molecule(tmp_path / "cache", i) for i in range(60)]

    outcome = _run(tmp_path, resolved)

    assert outcome.published
    assert outcome.fragment_count == 60
    assert stub_check.calls == 1
    assert len(stub_check.seen[0]) == 60

    spaex_dir = tmp_path / "repo" / ".spaex"
    document = parse((spaex_dir / "constitution.md").read_text(encoding="utf-8"))
    assert [b.scoped_id for b in document.blocks] == [f"mol-{i:03d}/rule" for i in range(60)]
    assert [b.body for b in document.blocks] == [f"**MUST** follow rule {i}.\n" for i in range(60)]
    state = json.loads((spaex_dir / "decisions.json").read_text(encoding="utf-8"))
    assert state["decisions"] == {}
    assert set(state["checked"]) == {"source_hash", "prompt_hash"}


def test_a_single_small_set_makes_exactly_one_check_call_and_a_rerun_makes_none(
    tmp_path: Path, stub_check: StubCheck
) -> None:
    resolved = [_resolved_molecule(tmp_path / "cache", i) for i in range(3)]

    first = _run(tmp_path, resolved)
    second = _run(tmp_path, resolved)

    assert (first.skipped_check, second.skipped_check) == (False, True)
    assert stub_check.calls == 1


def _answer(findings: list[dict]) -> str:
    envelope = {"type": "findings", "findings": findings} if findings else {"type": "no_findings"}
    return f"<<<SPAEX-COMPOSER-BEGIN>>>\n{json.dumps(envelope)}\n<<<SPAEX-COMPOSER-END>>>\n"


def test_a_set_above_the_ceiling_is_checked_group_by_group_and_pair_by_pair(
    tmp_path: Path, operator: Operator
) -> None:
    """~170 KB of fragments exceed the single-call ceiling. The conflict is between the
    first and the last molecule, which cannot share a group: only a pair call sees both."""
    resolved = [_resolved_molecule(tmp_path / "cache", i, filler_lines=25) for i in range(100)]
    first, last = "mol-000/rule", "mol-099/rule"
    payloads: list[set[str]] = []
    runtimes: list[str] = []

    def runtime(name: str, _prompt: str, payload: str, _timeout: float) -> str:
        ids = {f["id"] for f in json.loads(payload)["fragments"]}
        payloads.append(ids)
        runtimes.append(name)
        if first in ids and last in ids:
            return _answer(
                [
                    {
                        "kind": "contradiction",
                        "summary": "first and last disagree",
                        "passages": [
                            {"fragment": first, "start": 1, "end": 1},
                            {"fragment": last, "start": 1, "end": 1},
                        ],
                    }
                ]
            )
        return _answer([])

    operator.default = Choice(kind="keep", kept=0)
    outcome = _run(
        tmp_path,
        resolved,
        invoke_options=InvokeOptions(
            stub_caller=runtime, composer_log_path=tmp_path / "composer.log"
        ),
    )

    assert outcome.published
    assert len(payloads) > 3, "more than one group, so more than one call"
    assert all(len(ids) < 100 for ids in payloads), "no call carries the whole set"
    assert set().union(*payloads) == {f"mol-{i:03d}/rule" for i in range(100)}
    assert len(set(runtimes)) == 1, "one runtime is chosen once for every call"
    assert sum(1 for ids in payloads if first in ids and last in ids) >= 1

    (finding,) = operator.asked
    assert [p.scoped_id for p in finding.passages] == [first, last]
    text = (tmp_path / "repo" / ".spaex" / "constitution.md").read_text(encoding="utf-8")
    assert f'<!-- spaex-excluded kept="{first}:1-1"' in text
    assert "**MUST** follow rule 99.\n-->" in text
    block = next(b for b in parse(text).blocks if b.scoped_id == last)
    assert block.body.startswith("**MUST** follow rule 99.\n")
    assert len(block.exclusions) == 1
