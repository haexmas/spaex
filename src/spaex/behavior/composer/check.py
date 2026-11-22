"""The check: contradictions and duplicates between fragment passages (Spec 030).

The only step that still uses a language model. It receives the fragments as
numbered lines and returns findings (passages named by fragment and line range)
or nothing. It cannot write constitution text; spaex verifies every named
passage and the operator decides what happens with each finding.
Interface: contracts/check-interface.md.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from spaex.behavior.composer.failure import ComposerFailureCategory, raise_for
from spaex.behavior.composer.invoke import (
    ComposerLogEntry,
    InvokeOptions,
    append_composer_log_entry,
    invoke_raw,
    parse_envelope,
    resolve_composer_log_path,
    resolve_runtime_name,
)
from spaex.behavior.composer.prompt import CHECK_PROMPT_VERSION, load_effective_check_prompt
from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.passages import (
    Passage,
    PassageError,
    canonical_lines,
    finding_key,
    fragment_index,
    validate_range,
)
from spaex.util.errors import HaexError

SPAEX_VERSION = "5"

#: Serialized-size ceiling of one check call. The old composer needed ~20KB
#: calls because it had to write the whole document back; the check answers
#: with a few findings, so its input can be far larger (spec 030, research R6).
DEFAULT_MAX_BYTES = 150_000
KINDS = ("contradiction", "duplicate")


@dataclass(frozen=True)
class Finding:
    """A contradiction or duplicate between passages of different fragments."""

    kind: str
    summary: str
    passages: tuple[Passage, ...]

    @property
    def key(self) -> str:
        return finding_key(self.passages)


@dataclass(frozen=True)
class CheckInput:
    """Payload of one check call: the fragments to compare, as numbered lines."""

    fragments: tuple[BehaviorFragment, ...]

    def to_json(self) -> str:
        payload: dict[str, Any] = {
            "spaex_version": SPAEX_VERSION,
            "check_prompt_version": CHECK_PROMPT_VERSION,
            "fragments": [
                {
                    "id": fragment.scoped_id,
                    "modality": fragment.modality.value if fragment.modality else None,
                    "body": "\n".join(
                        f"{number}: {text}"
                        for number, text in enumerate(canonical_lines(fragment.body), start=1)
                    ),
                }
                for fragment in sorted(self.fragments, key=lambda f: f.scoped_id)
            ],
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _invalid(message: str) -> HaexError:
    try:
        raise_for(ComposerFailureCategory.INVALID_OUTPUT, message)
    except HaexError as exc:
        return exc
    raise AssertionError("unreachable")


def parse_check_result(
    raw: str, fragments: Sequence[BehaviorFragment]
) -> tuple[Finding, ...]:
    """Parse and verify a check answer; raise `invalid-output` if unusable.

    A finding is unusable when its kind is unknown, its summary is empty, it
    names fewer than two passages, two passages of the same fragment, or a
    passage that does not exist (data-model.md, "Passage").
    """
    envelope, _rest = parse_envelope(raw)
    shape = envelope.get("type")
    if shape == "no_findings":
        return ()
    if shape != "findings":
        raise _invalid(f"check sentinel type {shape!r} is not 'findings' or 'no_findings'")
    entries = envelope.get("findings")
    if not isinstance(entries, list) or not entries:
        raise _invalid("check response of type 'findings' has no findings")
    index = fragment_index(fragments)
    findings: list[Finding] = []
    for position, entry in enumerate(entries, start=1):
        findings.append(_parse_finding(entry, position, index))
    return tuple(findings)


def _parse_finding(
    entry: Any, position: int, index: Mapping[str, BehaviorFragment]
) -> Finding:
    label = f"finding {position}"
    if not isinstance(entry, dict):
        raise _invalid(f"{label} must be an object")
    kind = entry.get("kind")
    if kind not in KINDS:
        raise _invalid(f"{label}: kind {kind!r} is not one of {KINDS}")
    summary = entry.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise _invalid(f"{label}: summary must be a non-empty string")
    raw_passages = entry.get("passages")
    if not isinstance(raw_passages, list) or len(raw_passages) < 2:
        raise _invalid(f"{label}: needs at least two passages")
    passages: list[Passage] = []
    for raw in raw_passages:
        if not isinstance(raw, dict):
            raise _invalid(f"{label}: a passage must be an object")
        fragment_id = raw.get("fragment")
        start, end = raw.get("start"), raw.get("end")
        if (
            not isinstance(fragment_id, str)
            or isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
        ):
            raise _invalid(f"{label}: a passage needs fragment, start and end")
        fragment = index.get(fragment_id)
        if fragment is None:
            raise _invalid(f"{label}: unknown fragment {fragment_id!r}")
        try:
            passages.append(validate_range(fragment, start, end))
        except PassageError as exc:
            raise _invalid(f"{label}: {exc}") from exc
    if len({passage.scoped_id for passage in passages}) != len(passages):
        raise _invalid(f"{label}: passages must come from different fragments")
    return Finding(kind=str(kind), summary=summary.strip(), passages=tuple(passages))


def run_check(
    check_input: CheckInput,
    *,
    repo_root: Path,
    options: InvokeOptions | None = None,
    step: str = "check",
    invocation: int = 1,
    phase: str = "initial",
) -> tuple[Finding, ...]:
    """One check call: invoke the runtime, log the answer, return verified findings."""
    options = options or InvokeOptions()
    raw, _runtime = invoke_raw(
        prompt_text=load_effective_check_prompt(repo_root),
        payload_json=check_input.to_json(),
        repo_root=repo_root,
        options=options,
        step=step,
        invocation=invocation,
        phase=phase,
    )
    log_path = resolve_composer_log_path(options, repo_root)
    try:
        findings = parse_check_result(raw, check_input.fragments)
    except HaexError as exc:
        append_composer_log_entry(
            log_path,
            ComposerLogEntry(
                step=step,
                invocation=invocation,
                phase=phase,
                raw_output=raw,
                outcome=ComposerFailureCategory.INVALID_OUTPUT.value,
            ),
        )
        exc.context.setdefault("step", step)
        raise
    append_composer_log_entry(
        log_path,
        ComposerLogEntry(
            step=step,
            invocation=invocation,
            phase=phase,
            raw_output=raw,
            outcome="findings" if findings else "no_findings",
        ),
    )
    return findings


def check_fragments(
    fragments: Sequence[BehaviorFragment],
    *,
    repo_root: Path,
    options: InvokeOptions | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_workers: int = 4,
) -> tuple[Finding, ...]:
    """Check all fragments: one call, or every group and every pair of groups.

    A set that fits `max_bytes` is one call. A larger set is split by molecule
    into groups of at most half the ceiling; every group and every pair of
    groups is checked, so a conflict between any two molecules is seen by some
    call. One runtime is chosen once and used for every call (spec 026 FR-011).
    Findings are merged by key and sorted by first passage.
    """
    options = options or InvokeOptions()
    ordered = tuple(sorted(fragments, key=lambda f: f.scoped_id))
    if len(CheckInput(fragments=ordered).to_json().encode("utf-8")) <= max_bytes:
        return run_check(CheckInput(fragments=ordered), repo_root=repo_root, options=options)

    groups = _group_by_molecule(ordered, max_bytes // 2)
    runtime = resolve_runtime_name(options)
    pinned = replace(options, resolved_runtime_name=runtime)
    jobs: list[tuple[str, tuple[BehaviorFragment, ...]]] = [
        (f"check-g{i + 1}", group) for i, group in enumerate(groups)
    ]
    jobs += [
        (f"check-g{i + 1}-g{j + 1}", groups[i] + groups[j])
        for i in range(len(groups))
        for j in range(i + 1, len(groups))
    ]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                run_check,
                CheckInput(fragments=group),
                repo_root=repo_root,
                options=pinned,
                step=step,
            )
            for step, group in jobs
        ]
        results = [future.result() for future in futures]
    merged: dict[str, Finding] = {}
    for found in results:
        for finding in found:
            merged.setdefault(finding.key, finding)
    return tuple(
        sorted(
            merged.values(),
            key=lambda f: (f.passages[0].scoped_id, f.passages[0].start, f.key),
        )
    )


def _group_by_molecule(
    fragments: Sequence[BehaviorFragment], budget: int
) -> list[tuple[BehaviorFragment, ...]]:
    by_molecule: dict[str, list[BehaviorFragment]] = defaultdict(list)
    for fragment in fragments:
        by_molecule[fragment.molecule_id].append(fragment)
    groups: list[tuple[BehaviorFragment, ...]] = []
    current: list[BehaviorFragment] = []
    for molecule_id in sorted(by_molecule):
        candidate = current + by_molecule[molecule_id]
        size = len(CheckInput(fragments=tuple(candidate)).to_json().encode("utf-8"))
        if current and size > budget:
            groups.append(tuple(current))
            current = list(by_molecule[molecule_id])
        else:
            current = candidate
    if current:
        groups.append(tuple(current))
    return groups


__all__ = [
    "DEFAULT_MAX_BYTES",
    "CheckInput",
    "Finding",
    "check_fragments",
    "parse_check_result",
    "run_check",
]
