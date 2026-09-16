"""Composer invocation (Spec 023 T019, CLI-only in 4.2.0).

The Composer shells out to a locally installed agent CLI (`claude`, `codex`,
`gemini`) in a fixed priority order. Runtime selection is stable so the
composed constitution stays byte-reproducible (SC-003).

Direct-API mode via `litellm` is deliberately out of scope for 4.2.0: the
project's own workflow always invokes `spaex install` from an already-open
agent CLI session, so shelling out to that CLI is the natural composition
path and avoids pulling a large LLM adapter (litellm + openai + anthropic +
google + tokenizers) into every `pip install spaex`. Reintroducing a
direct-API path later means adding roughly thirty lines here plus an
optional extra dep; the `stub_caller` hook in `InvokeOptions` already gives
tests a seam for exercising alternative code paths.

Every failure surfaces via `spaex.behavior.composer.failure.raise_for`,
which maps to exit codes 30-34. Silent degradation is forbidden (FR-012a).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spaex.behavior.composer.clarifications import Clarification
from spaex.behavior.composer.failure import (
    QUOTA_FAILURE_SIGNALS,
    ComposerFailureCategory,
    raise_for,
)
from spaex.behavior.composer.prompt import (
    COMPOSER_PROMPT_VERSION,
    load_effective_prompt,
)
from spaex.behavior.fragment import BehaviorFragment
from spaex.util.errors import HaexError

COMPOSER_LOG_ENV = "SPAEX_COMPOSER_LOG"
DEFAULT_COMPOSER_LOG = ".spaex/composer.log"
TIMEOUT_ENV = "SPAEX_COMPOSER_TIMEOUT"
DEFAULT_TIMEOUT_SECONDS = 300

SENTINEL_BEGIN = "<<<SPAEX-COMPOSER-BEGIN>>>"
SENTINEL_END = "<<<SPAEX-COMPOSER-END>>>"
_SENTINEL_RE = re.compile(
    r"<<<SPAEX-COMPOSER-BEGIN>>>\s*(?P<json>.*?)\s*<<<SPAEX-COMPOSER-END>>>",
    re.DOTALL,
)

_CLI_RUNTIMES: tuple[str, ...] = ("claude", "codex", "gemini")


@dataclass(frozen=True)
class ComposerInput:
    """Structured input to the Composer.

    `expected_source_hash` and `expected_build_input_hash` are computed by
    spaex outside the LLM (research.md §5). The prompt tells the LLM to echo
    them verbatim in the `.spaex/constitution.md` header; spaex verifies the echo before
    accepting Shape A.
    """

    fragments: tuple[BehaviorFragment, ...]
    clarifications: tuple[Clarification, ...] = ()
    expected_source_hash: str = ""
    expected_build_input_hash: str = ""
    spaex_version: str = "4.2.0"

    def to_json(self) -> str:
        """Serialize per contracts/composer-interface.md §Composer input."""
        payload: dict[str, Any] = {
            "spaex_version": self.spaex_version,
            "composer_prompt_version": COMPOSER_PROMPT_VERSION,
            "expected_source_hash": self.expected_source_hash,
            "expected_build_input_hash": self.expected_build_input_hash,
            "fragments": [_fragment_to_dict(f) for f in _sort_fragments(self.fragments)],
            "clarifications": [_clarification_to_dict(c) for c in self.clarifications],
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class ComposedShape:
    """Shape A parse result: composed constitution ready for emit.py."""

    body: str


@dataclass(frozen=True)
class QuestionsShape:
    """Shape B parse result: clarification questions to present to operator."""

    questions: tuple[ClarificationQuestion, ...]


@dataclass(frozen=True)
class ClarificationQuestion:
    kind: str
    cited_fragments: tuple[dict[str, str], ...]
    question: str


ComposerResult = ComposedShape | QuestionsShape


@dataclass(frozen=True)
class RuntimeDescriptor:
    """Which runtime was actually used to produce a ComposerResult."""

    kind: str
    identifier: str


@dataclass(frozen=True)
class InvokeOutcome:
    """Return type of `invoke_composer`: parsed result + runtime + raw text."""

    result: ComposerResult
    runtime: RuntimeDescriptor
    raw_output: str


@dataclass(frozen=True)
class ComposerLogEntry:
    """One JSON-lines record in `$SPAEX_COMPOSER_LOG` (Spec 026 research.md §5).

    `(step, invocation)` is unique within one attempt. `step` is
    `"single"` for the legacy/degenerate one-call path, `"batch-1"`,
    `"batch-2"`, ... for a map-reduce batch call, or `"merge"`-prefixed for a
    merge node. `invocation` is `1` for a step's initial call and `2` for
    its one bounded clarification-resolved re-invocation.
    """

    step: str
    invocation: int
    phase: str
    raw_output: str
    outcome: str

    def to_json(self) -> str:
        """Serialize the log entry as one JSON-lines-compatible record."""
        return json.dumps(
            {
                "step": self.step,
                "invocation": self.invocation,
                "phase": self.phase,
                "raw_output": self.raw_output,
                "outcome": self.outcome,
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class InvokeOptions:
    """Overrides for testing; production callers use defaults.

    `stub_caller`, when set, receives `(runtime_name, system_prompt, payload,
    timeout)` and returns the raw Composer output as a string, or raises an
    exception the classifier maps to a failure category. Fault-injection
    tests use this to avoid shelling out to a real CLI. `forced_cli_runtimes`
    lets a test constrain the CLI priority list (pass `()` to force the
    no-runtime failure).
    """

    forced_cli_runtimes: tuple[str, ...] | None = None
    timeout_seconds: float | None = None
    composer_log_path: Path | None = None
    stub_caller: Callable[[str, str, str, float], str] | None = None


def invoke_composer(
    composer_input: ComposerInput,
    *,
    repo_root: Path,
    options: InvokeOptions | None = None,
    step: str = "single",
    invocation: int = 1,
    phase: str = "initial",
) -> InvokeOutcome:
    """Run the Composer and return its parsed output.

    Thin wrapper over `invoke_step` for the canonical/project-override
    compose prompt and a `ComposerInput` payload — the legacy single-call
    shape, and the shape a map-reduce batch call also uses (Spec 026
    research.md §1: batch calls reuse this unchanged machinery). `step`,
    `invocation`, and `phase` label the JSON-lines log entry (data-model.md
    `ComposerLogEntry`); callers outside a multi-step build never need to
    pass them.
    """
    return invoke_step(
        prompt_text=load_effective_prompt(repo_root),
        payload_json=composer_input.to_json(),
        repo_root=repo_root,
        options=options,
        step=step,
        invocation=invocation,
        phase=phase,
    )


def invoke_step(
    *,
    prompt_text: str,
    payload_json: str,
    repo_root: Path,
    options: InvokeOptions | None = None,
    step: str = "single",
    invocation: int = 1,
    phase: str = "initial",
) -> InvokeOutcome:
    """Generic runtime-resolution + call + parse + per-invocation log primitive.

    `invoke_composer` is a thin wrapper around this for the canonical compose
    prompt. `spaex.behavior.composer.reduce` calls this directly for a merge
    step, which needs a different prompt (`prompt.MERGE_PROMPT`) and payload
    shape (`MergeNodeInput`, not `ComposerInput`) but the exact same runtime
    resolution, stub-caller test seam, and log lifecycle (Spec 026
    research.md §1, §5).

    Runtime selection order (research.md §2, 4.2.0 CLI-only variant):

    1. If `options.stub_caller` is set, hand the call to it. Testing only.
    2. Iterate `_CLI_RUNTIMES` (or `options.forced_cli_runtimes` when set) in
       order; use the first one on PATH.
    3. `no-runtime` failure (exit 34) when no CLI is found.
    """
    options = options or InvokeOptions()

    timeout = _resolve_timeout(options)
    log_path = resolve_composer_log_path(options, repo_root)

    cli_runtimes = (
        options.forced_cli_runtimes
        if options.forced_cli_runtimes is not None
        else _CLI_RUNTIMES
    )

    if options.stub_caller is not None:
        # Tests skip PATH-detection: the stub answers for whichever runtime
        # was picked first (or a synthetic "stub" identifier when none was
        # requested), so scenarios like "no-runtime" stay reachable by
        # passing `forced_cli_runtimes=()` and leaving stub_caller unset.
        name = cli_runtimes[0] if cli_runtimes else "stub"
        raw = _call_stub(options.stub_caller, name, prompt_text, payload_json, timeout)
        result = _parse_and_log(
            raw, log_path=log_path, step=step, invocation=invocation, phase=phase
        )
        return InvokeOutcome(
            result=result,
            runtime=RuntimeDescriptor(kind="stub", identifier=name),
            raw_output=raw,
        )

    for name in cli_runtimes:
        if shutil.which(name) is not None:
            raw = _call_cli(name, prompt_text, payload_json, timeout)
            result = _parse_and_log(
                raw, log_path=log_path, step=step, invocation=invocation, phase=phase
            )
            return InvokeOutcome(
                result=result,
                runtime=RuntimeDescriptor(kind="cli", identifier=name),
                raw_output=raw,
            )

    raise_for(
        ComposerFailureCategory.NO_RUNTIME,
        "no LLM runtime available for the Composer",
    )
    raise AssertionError("raise_for did not raise")  # unreachable; makes mypy happy


def _resolve_timeout(options: InvokeOptions) -> float:
    if options.timeout_seconds is not None:
        return options.timeout_seconds
    raw = os.environ.get(TIMEOUT_ENV)
    if not raw:
        return float(DEFAULT_TIMEOUT_SECONDS)
    try:
        value = float(raw)
    except ValueError:
        return float(DEFAULT_TIMEOUT_SECONDS)
    if value <= 0:
        return float(DEFAULT_TIMEOUT_SECONDS)
    return value


def resolve_composer_log_path(options: InvokeOptions, repo_root: Path) -> Path:
    """Resolve the configured path used for Composer diagnostic output."""
    if options.composer_log_path is not None:
        return options.composer_log_path
    raw = os.environ.get(COMPOSER_LOG_ENV)
    if raw:
        return Path(raw)
    return repo_root / DEFAULT_COMPOSER_LOG


def _call_stub(
    stub: Callable[[str, str, str, float], str],
    name: str,
    system_prompt: str,
    payload: str,
    timeout: float,
) -> str:
    """Route a stubbed invocation through the same failure classifier as CLI."""
    try:
        return stub(name, system_prompt, payload, timeout)
    except Exception as exc:  # noqa: BLE001
        category = _classify_stub_exception(exc)
        raise_for(category, f"{type(exc).__name__}: {exc}")
        raise AssertionError("unreachable") from exc


def _call_cli(
    name: str,
    system_prompt: str,
    payload: str,
    timeout: float,
) -> str:
    """Shell out to a locally installed agent CLI runtime."""
    argv = _cli_argv(name)
    stdin_input = _cli_stdin(system_prompt, payload)
    sys.stdout.write(
        f"composer: invoking {name} (payload {len(stdin_input)} chars, "
        f"timeout {timeout:.0f}s)...\n"
    )
    sys.stdout.flush()
    start = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603
            argv,
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise_for(
            ComposerFailureCategory.TIMEOUT,
            f"{name} timed out after {timeout}s{_load_avg_suffix()}",
        )
        raise AssertionError("unreachable") from exc
    except (OSError, ValueError) as exc:
        raise_for(
            ComposerFailureCategory.RUNTIME_ERROR,
            f"could not launch {name}: {exc}",
        )
        raise AssertionError("unreachable") from exc
    elapsed = time.monotonic() - start
    sys.stdout.write(f"composer: {name} responded in {elapsed:.1f}s\n")
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        if _is_quota_failure(stderr):
            raise_for(
                ComposerFailureCategory.QUOTA,
                f"{name} exited {completed.returncode}: {stderr}",
            )
        raise_for(
            ComposerFailureCategory.RUNTIME_ERROR,
            f"{name} exited {completed.returncode}: {stderr}",
        )
    return completed.stdout


def _load_avg_suffix() -> str:
    """Append host load averages to a timeout diagnostic, when available.

    A composer timeout on an otherwise-working runtime is frequently host
    contention (other concurrent CLI sessions/processes), not a genuinely
    stuck call — `os.getloadavg()` is the cheapest signal that distinguishes
    the two without a second manual investigation. Unix-only; absent on
    Windows, where this silently contributes nothing.
    """
    getloadavg = getattr(os, "getloadavg", None)
    if getloadavg is None:
        return ""
    try:
        load1, load5, load15 = getloadavg()
    except OSError:
        return ""
    return f" (host load avg 1/5/15m: {load1:.2f}/{load5:.2f}/{load15:.2f})"


def _cli_argv(name: str) -> list[str]:
    """Runtime-specific argv for a one-shot non-interactive session.

    Kept minimal; each runtime's non-interactive contract is documented in
    research.md §1 (updated to reflect the CLI-only decision).
    """
    if name == "claude":
        return ["claude", "--print"]
    if name == "codex":
        return ["codex", "exec"]
    if name == "gemini":
        return ["gemini", "--prompt", "-"]
    return [name]


def _cli_stdin(system_prompt: str, payload: str) -> str:
    """Fold system prompt and payload into a single stdin message.

    CLI runtimes lack a stable non-interactive system-prompt slot, so we
    prepend the prompt with an explicit boundary. Parsers in `_parse` react
    only to the sentinel-wrapped block, so extra framing is tolerated.
    """
    return f"{system_prompt}\n---\nCOMPOSER INPUT\n---\n{payload}\n"


def _parse_and_log(
    raw: str, *, log_path: Path, step: str, invocation: int, phase: str
) -> ComposerResult:
    """Parse a Composer response, then append exactly one log entry for it.

    Every completed invocation (successful or not) gets one JSON-lines
    record, appended immediately and flushed (research.md §5) — this
    replaces `_parse`'s old behavior of overwriting the whole log file only
    on a parse failure.
    """
    try:
        result = _parse(raw)
    except HaexError:
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
        raise
    outcome = "composed" if isinstance(result, ComposedShape) else "questions"
    append_composer_log_entry(
        log_path,
        ComposerLogEntry(
            step=step,
            invocation=invocation,
            phase=phase,
            raw_output=raw,
            outcome=outcome,
        ),
    )
    return result


def _parse(raw: str) -> ComposerResult:
    """Parse a Composer response into Shape A or Shape B."""
    match = _SENTINEL_RE.search(raw)
    if match is None:
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            "Composer output missing SPAEX-COMPOSER sentinel block",
        )
        raise AssertionError("unreachable")
    try:
        envelope = json.loads(match.group("json"))
    except json.JSONDecodeError as exc:
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            f"Composer sentinel JSON invalid: {exc}",
        )
        raise AssertionError("unreachable") from exc
    if not isinstance(envelope, dict):
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            f"Composer sentinel JSON must be an object; got {type(envelope).__name__}",
        )
        raise AssertionError("unreachable")

    shape_kind = envelope.get("type")
    if shape_kind == "composed":
        body = raw[match.end():].lstrip("\n\r ")
        if not body:
            raise_for(
                ComposerFailureCategory.INVALID_OUTPUT,
                "Shape A response missing composed constitution body",
            )
            raise AssertionError("unreachable")
        return ComposedShape(body=body)
    if shape_kind == "questions":
        questions_raw = envelope.get("questions") or ()
        if not isinstance(questions_raw, list) or not questions_raw:
            raise_for(
                ComposerFailureCategory.INVALID_OUTPUT,
                "Shape B response has no questions",
            )
            raise AssertionError("unreachable")
        parsed = tuple(_parse_question(q) for q in questions_raw)
        return QuestionsShape(questions=parsed)

    raise_for(
        ComposerFailureCategory.INVALID_OUTPUT,
        f"Composer sentinel type {shape_kind!r} is not 'composed' or 'questions'",
    )
    raise AssertionError("unreachable")


def _parse_question(raw: Any) -> ClarificationQuestion:
    """Validate and convert one raw Shape-B clarification question."""
    if not isinstance(raw, dict):
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            f"Shape B question must be an object; got {type(raw).__name__}",
        )
        raise AssertionError("unreachable")
    kind = raw.get("kind")
    if kind not in ("overlap", "contradiction"):
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            f"Shape B question kind {kind!r} not in overlap|contradiction",
        )
        raise AssertionError("unreachable")
    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            "Shape B question text must be a non-empty string",
        )
        raise AssertionError("unreachable")
    cited_raw = raw.get("cited_fragments") or ()
    cited: list[dict[str, str]] = []
    if not isinstance(cited_raw, list):
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            "Shape B cited_fragments must be a list",
        )
        raise AssertionError("unreachable")
    for entry in cited_raw:
        if not isinstance(entry, dict):
            continue
        molecule_id = entry.get("molecule_id")
        fragment_id = entry.get("fragment_id")
        if isinstance(molecule_id, str) and isinstance(fragment_id, str):
            cited.append(
                {"molecule_id": molecule_id, "fragment_id": fragment_id}
            )
    return ClarificationQuestion(
        kind=kind,
        cited_fragments=tuple(cited),
        question=question,
    )


def truncate_composer_log(path: Path) -> None:
    """Truncate `$SPAEX_COMPOSER_LOG` exactly once, at the start of a fresh
    build attempt (research.md §5). Every invocation within the attempt then
    appends via `append_composer_log_entry`/`write_composer_log`, so a later
    step's failure (including one that never returns) can't erase evidence
    of earlier steps.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except OSError:
        pass


def append_composer_log_entry(path: Path, entry: ComposerLogEntry) -> None:
    """Best-effort append of one JSON-lines record, flushed immediately."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(entry.to_json())
            handle.write("\n")
            handle.flush()
    except OSError:
        pass


def write_composer_log(
    path: Path,
    raw: str,
    *,
    step: str = "final",
    invocation: int = 1,
    phase: str = "initial",
    outcome: str = ComposerFailureCategory.INVALID_OUTPUT.value,
) -> None:
    """Append one log entry for a single raw blob outside the normal
    invoke/parse dispatch loop (e.g. `orchestrate._verify_completeness`
    logging a composed body that parsed fine but silently dropped a
    fragment). `step` defaults to `"final"`: the fully-composed document,
    whether produced by the legacy single call or the map-reduce root merge.
    """
    append_composer_log_entry(
        path,
        ComposerLogEntry(
            step=step, invocation=invocation, phase=phase, raw_output=raw, outcome=outcome
        ),
    )


def _classify_stub_exception(exc: Exception) -> ComposerFailureCategory:
    """Map a stubbed exception class name into a Composer failure category.

    Fault-injection tests craft exception classes whose names include
    "timeout", "ratelimit", "quota", etc. so this classifier remains a thin
    string match. Real CLI-path failures never reach this function.
    """
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return ComposerFailureCategory.TIMEOUT
    if "ratelimit" in name or "quota" in name or "insufficient" in name:
        return ComposerFailureCategory.QUOTA
    return ComposerFailureCategory.RUNTIME_ERROR


def _is_quota_failure(stderr: str) -> bool:
    """Return whether CLI stderr contains a supported quota signal."""
    normalized = stderr.casefold()
    return any(signal in normalized for signal in QUOTA_FAILURE_SIGNALS)


def _sort_fragments(
    fragments: Sequence[BehaviorFragment],
) -> tuple[BehaviorFragment, ...]:
    return tuple(sorted(fragments, key=lambda f: f.scoped_id))


def _fragment_to_dict(fragment: BehaviorFragment) -> dict[str, Any]:
    return {
        "molecule_id": fragment.molecule_id,
        "fragment_id": fragment.id,
        "atom_source": fragment.atom_source,
        "modality": fragment.modality.value if fragment.modality else None,
        "tags": list(fragment.tags),
        "body": fragment.body,
        "body_sha256": fragment.body_hash,
    }


def _clarification_to_dict(c: Clarification) -> dict[str, Any]:
    return {
        "key": c.key,
        "question": c.question,
        "cited_fragments": [entry.as_json() for entry in c.cited_fragments],
        "answer": c.answer,
    }


__all__ = [
    "COMPOSER_LOG_ENV",
    "DEFAULT_COMPOSER_LOG",
    "DEFAULT_TIMEOUT_SECONDS",
    "SENTINEL_BEGIN",
    "SENTINEL_END",
    "TIMEOUT_ENV",
    "ClarificationQuestion",
    "ComposedShape",
    "ComposerInput",
    "ComposerLogEntry",
    "ComposerResult",
    "InvokeOptions",
    "InvokeOutcome",
    "QuestionsShape",
    "RuntimeDescriptor",
    "append_composer_log_entry",
    "invoke_composer",
    "invoke_step",
    "resolve_composer_log_path",
    "truncate_composer_log",
    "write_composer_log",
]
