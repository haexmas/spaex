"""`check_fragments`: one call, or every group and every pair of groups (Spec 030 T017, R6)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from spaex.behavior.composer import check as check_mod
from spaex.behavior.composer.check import CheckInput, check_fragments
from spaex.behavior.composer.invoke import InvokeOptions
from spaex.behavior.fragment import BehaviorFragment

from ._fragments import make_fragment

F = {
    "m1/a": make_fragment("m1", "a", "rule a1\n"),
    "m1/a2": make_fragment("m1", "a2", "rule a2\n"),
    "m2/b": make_fragment("m2", "b", "rule b1\n"),
    "m3/c": make_fragment("m3", "c", "rule c1\n"),
}
FRAGMENTS = tuple(F.values())

#: Findings the stubbed model reports whenever both fragments are in the payload.
PAIRS = [
    ("m1/a", "m1/a2", "duplicate"),
    ("m1/a", "m2/b", "contradiction"),
    ("m1/a", "m3/c", "duplicate"),
]


class _Model:
    """Stub caller that answers per payload and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.lock = threading.Lock()

    def __call__(self, runtime: str, prompt: str, payload: str, timeout: float) -> str:
        ids = tuple(f["id"] for f in json.loads(payload)["fragments"])
        with self.lock:
            self.calls.append((runtime, ids))
        findings = [
            {
                "kind": kind,
                "summary": f"{first} vs {second}",
                "passages": [
                    {"fragment": first, "start": 1, "end": 1},
                    {"fragment": second, "start": 1, "end": 1},
                ],
            }
            for first, second, kind in PAIRS
            if first in ids and second in ids
        ]
        body = (
            {"type": "findings", "findings": findings} if findings else {"type": "no_findings"}
        )
        return f"<<<SPAEX-COMPOSER-BEGIN>>>\n{json.dumps(body)}\n<<<SPAEX-COMPOSER-END>>>\n"


def _options(model: _Model, tmp_path: Path) -> InvokeOptions:
    return InvokeOptions(stub_caller=model, composer_log_path=tmp_path / "composer.log")


def _size(*fragments: BehaviorFragment) -> int:
    return len(CheckInput(fragments=tuple(fragments)).to_json().encode("utf-8"))


def _steps(tmp_path: Path) -> list[str]:
    log = tmp_path / "composer.log"
    return sorted(json.loads(line)["step"] for line in log.read_text().splitlines())


def test_a_set_under_the_ceiling_is_one_call(tmp_path: Path) -> None:
    model = _Model()

    findings = check_fragments(FRAGMENTS, repo_root=tmp_path, options=_options(model, tmp_path))

    assert len(model.calls) == 1
    assert sorted(model.calls[0][1]) == sorted(F)
    assert _steps(tmp_path) == ["check"]
    assert [f.kind for f in findings] == ["duplicate", "contradiction", "duplicate"]


def test_a_set_over_the_ceiling_checks_every_group_and_every_pair(tmp_path: Path) -> None:
    model = _Model()
    one_molecule = _size(F["m2/b"])
    max_bytes = 2 * one_molecule + 10  # less than the whole set, each molecule its own group

    findings = check_fragments(
        FRAGMENTS, repo_root=tmp_path, options=_options(model, tmp_path), max_bytes=max_bytes
    )

    # m1 holds two fragments, so it is the largest group; m2 and m3 are alone or joined.
    steps = _steps(tmp_path)
    assert len(model.calls) == len(steps) >= 4
    assert all(step.startswith("check-g") for step in steps)
    pair_steps = [step for step in steps if step.count("-g") == 2]
    group_steps = [step for step in steps if step.count("-g") == 1]
    n = len(group_steps)
    assert len(pair_steps) == n * (n - 1) // 2
    # Every pair of fragments was seen together by at least one call (so no conflict is missed).
    seen = {frozenset(ids) for _runtime, ids in model.calls}
    for first, second, _kind in PAIRS:
        assert any({first, second} <= ids for ids in seen)
    assert {f.summary for f in findings} == {f"{a} vs {b}" for a, b, _k in PAIRS}


def test_findings_are_merged_by_key_and_sorted_by_first_passage(tmp_path: Path) -> None:
    model = _Model()
    max_bytes = 2 * _size(F["m2/b"]) + 10

    findings = check_fragments(
        FRAGMENTS, repo_root=tmp_path, options=_options(model, tmp_path), max_bytes=max_bytes
    )

    keys = [f.key for f in findings]
    assert len(keys) == len(set(keys)) == len(PAIRS)
    assert [f.passages[0].scoped_id for f in findings] == sorted(
        f.passages[0].scoped_id for f in findings
    )
    # The m1/a vs m1/a2 duplicate is reported by several calls but returned once.
    assert sum(1 for f in findings if f.summary == "m1/a vs m1/a2") == 1


def test_one_runtime_is_resolved_once_and_used_for_every_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _Model()
    resolved: list[str] = []
    real = check_mod.resolve_runtime_name

    def counting(options: InvokeOptions | None = None) -> str:
        name = real(options)
        resolved.append(name)
        return name

    monkeypatch.setattr(check_mod, "resolve_runtime_name", counting)
    options = InvokeOptions(
        stub_caller=model,
        composer_log_path=tmp_path / "composer.log",
        forced_cli_runtimes=("codex", "claude"),
    )

    check_fragments(
        FRAGMENTS, repo_root=tmp_path, options=options, max_bytes=2 * _size(F["m2/b"]) + 10
    )

    assert resolved == ["codex"]
    assert {runtime for runtime, _ids in model.calls} == {"codex"}


def test_a_failing_group_call_fails_the_whole_check(tmp_path: Path) -> None:
    def failing(runtime: str, prompt: str, payload: str, timeout: float) -> str:
        raise RuntimeError("simulated runtime failure")

    options = InvokeOptions(stub_caller=failing, composer_log_path=tmp_path / "composer.log")

    with pytest.raises(Exception, match="simulated runtime failure"):
        check_fragments(
            FRAGMENTS, repo_root=tmp_path, options=options, max_bytes=2 * _size(F["m2/b"]) + 10
        )


def test_groups_and_group_pairs_stay_within_the_payload_limit() -> None:
    max_bytes = _size(*FRAGMENTS) - 1
    groups = check_mod._group_fragments(FRAGMENTS, max_bytes)

    flattened = [f.scoped_id for group in groups for f in group]
    assert sorted(flattened) == sorted(F)
    assert all(_size(*group) <= max_bytes for group in groups)
    assert all(
        _size(*(groups[left] + groups[right])) <= max_bytes
        for left in range(len(groups))
        for right in range(left + 1, len(groups))
    )
