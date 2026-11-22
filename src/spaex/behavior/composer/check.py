"""The check: contradictions and duplicates between fragment passages (Spec 030).

The only step that still uses a language model. It receives the fragments as
numbered lines and returns findings (passages named by fragment and line range)
or nothing. It cannot write constitution text; spaex verifies every named
passage and the operator decides what happens with each finding.
Interface: contracts/check-interface.md.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
                    "lines": [
                        {"n": number, "text": text}
                        for number, text in enumerate(canonical_lines(fragment.body), start=1)
                    ],
                }
                for fragment in sorted(self.fragments, key=lambda f: f.scoped_id)
            ],
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)


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


__all__ = [
    "CheckInput",
    "Finding",
    "parse_check_result",
    "run_check",
]
