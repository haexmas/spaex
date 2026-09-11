"""Composer invocation (Spec 023 T019).

Two invocation paths per research.md §1, §2:

1. Direct API via `litellm` when an LLM API key or explicit `SPAEX_LLM_MODEL`
   is set. Preferred; deterministic (temperature=0) and structured.
2. CLI shell-out to `claude`, `codex`, or `gemini` binaries in that priority
   order. Fallback when no API key is available.

The runtime selection order is stable across runs so the composed
constitution stays reproducible (SC-003).

Every failure surfaces via `spaex.behavior.composer.failure.raise_for`, which
maps to exit codes 30-34. Silent degradation is forbidden (FR-012a).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from spaex.behavior.composer.clarifications import Clarification
from spaex.behavior.composer.failure import (
    ComposerFailureCategory,
    raise_for,
)
from spaex.behavior.composer.prompt import (
    COMPOSER_PROMPT_VERSION,
    load_effective_prompt,
)
from spaex.behavior.fragment import BehaviorFragment


COMPOSER_LOG_ENV = "SPAEX_COMPOSER_LOG"
DEFAULT_COMPOSER_LOG = ".spaex/composer.log"
TIMEOUT_ENV = "SPAEX_COMPOSER_TIMEOUT"
DEFAULT_TIMEOUT_SECONDS = 30
MODEL_OVERRIDE_ENV = "SPAEX_LLM_MODEL"

SENTINEL_BEGIN = "<<<SPAEX-COMPOSER-BEGIN>>>"
SENTINEL_END = "<<<SPAEX-COMPOSER-END>>>"
_SENTINEL_RE = re.compile(
    r"<<<SPAEX-COMPOSER-BEGIN>>>\s*(?P<json>.*?)\s*<<<SPAEX-COMPOSER-END>>>",
    re.DOTALL,
)

_DEFAULT_MODELS = {
    "ANTHROPIC_API_KEY": "anthropic/claude-sonnet-4-5",
    "OPENAI_API_KEY": "openai/gpt-4o-mini",
    "GEMINI_API_KEY": "gemini/gemini-1.5-pro",
}

_CLI_RUNTIMES: tuple[str, ...] = ("claude", "codex", "gemini")


@dataclass(frozen=True)
class ComposerInput:
    """Structured input to the Composer.

    `expected_source_hash` and `expected_build_input_hash` are computed by
    spaex outside the LLM (research.md §5). The prompt tells the LLM to echo
    them verbatim in the `.spaex.md` header; spaex verifies the echo before
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

    questions: tuple["ClarificationQuestion", ...]


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
class InvokeOptions:
    """Overrides for testing; production callers use defaults."""

    api_keys_env: dict[str, str] = field(default_factory=dict)
    forced_model: str | None = None
    forced_cli_runtimes: tuple[str, ...] | None = None
    timeout_seconds: float | None = None
    composer_log_path: Path | None = None
    api_caller: Callable[[str, str, str, float], str] | None = None
    cli_caller: Callable[[str, str, str, float], str] | None = None


def invoke_composer(
    composer_input: ComposerInput,
    *,
    repo_root: Path,
    options: InvokeOptions | None = None,
) -> InvokeOutcome:
    """Run the Composer and return its parsed output.

    The selection order (research.md §2):

    1. Direct API via litellm when a key or `SPAEX_LLM_MODEL` is set.
    2. CLI shell-out to `claude`, `codex`, `gemini` in that priority order.
    3. `no-runtime` failure (exit 34) when neither path is available.
    """
    options = options or InvokeOptions()

    env = _resolve_env(options)
    prompt = load_effective_prompt(repo_root)
    payload = composer_input.to_json()
    timeout = _resolve_timeout(options)
    log_path = _resolve_log_path(options, repo_root)

    api_model = _pick_api_model(env, options)
    if api_model is not None:
        raw = _call_api(api_model, prompt, payload, timeout, options)
        result = _parse(raw, log_path=log_path)
        return InvokeOutcome(
            result=result,
            runtime=RuntimeDescriptor(kind="api", identifier=api_model),
            raw_output=raw,
        )

    cli_runtimes = (
        options.forced_cli_runtimes
        if options.forced_cli_runtimes is not None
        else _CLI_RUNTIMES
    )
    for name in cli_runtimes:
        if _cli_available(name, options):
            raw = _call_cli(name, prompt, payload, timeout, options)
            result = _parse(raw, log_path=log_path)
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


def _resolve_env(options: InvokeOptions) -> dict[str, str]:
    if options.api_keys_env:
        return dict(options.api_keys_env)
    return dict(os.environ)


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


def _resolve_log_path(options: InvokeOptions, repo_root: Path) -> Path:
    if options.composer_log_path is not None:
        return options.composer_log_path
    raw = os.environ.get(COMPOSER_LOG_ENV)
    if raw:
        return Path(raw)
    return repo_root / DEFAULT_COMPOSER_LOG


def _pick_api_model(env: dict[str, str], options: InvokeOptions) -> str | None:
    if options.forced_model is not None:
        return options.forced_model
    override = env.get(MODEL_OVERRIDE_ENV)
    if override:
        return override
    for key, model in _DEFAULT_MODELS.items():
        if env.get(key):
            return model
    return None


def _cli_available(name: str, options: InvokeOptions) -> bool:
    if options.cli_caller is not None:
        return True
    return shutil.which(name) is not None


def _call_api(
    model: str,
    system_prompt: str,
    payload: str,
    timeout: float,
    options: InvokeOptions,
) -> str:
    """Direct-API invocation via litellm.

    Litellm is imported lazily so consumers whose install path never trips the
    Composer do not pay the import cost.
    """
    if options.api_caller is not None:
        try:
            return options.api_caller(model, system_prompt, payload, timeout)
        except Exception as exc:  # noqa: BLE001
            category = _classify_api_exception(exc)
            raise_for(category, f"{type(exc).__name__}: {exc}")
            raise AssertionError("unreachable") from exc
    try:
        import litellm  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise_for(
            ComposerFailureCategory.NO_RUNTIME,
            f"litellm import failed: {exc}",
        )
        raise AssertionError("unreachable")
    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload},
            ],
            temperature=0.0,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        category = _classify_api_exception(exc)
        raise_for(category, f"{type(exc).__name__}: {exc}")
        raise AssertionError("unreachable") from exc
    try:
        return response["choices"][0]["message"]["content"]  # type: ignore[index,no-any-return]
    except (KeyError, IndexError, TypeError) as exc:
        raise_for(
            ComposerFailureCategory.RUNTIME_ERROR,
            f"litellm response missing expected fields: {exc}",
        )
        raise AssertionError("unreachable") from exc


def _call_cli(
    name: str,
    system_prompt: str,
    payload: str,
    timeout: float,
    options: InvokeOptions,
) -> str:
    """CLI shell-out to a locally installed agent runtime."""
    if options.cli_caller is not None:
        return options.cli_caller(name, system_prompt, payload, timeout)
    argv = _cli_argv(name)
    stdin_input = _cli_stdin(system_prompt, payload)
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
            f"{name} timed out after {timeout}s",
        )
        raise AssertionError("unreachable") from exc
    except (OSError, ValueError) as exc:
        raise_for(
            ComposerFailureCategory.RUNTIME_ERROR,
            f"could not launch {name}: {exc}",
        )
        raise AssertionError("unreachable") from exc
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise_for(
            ComposerFailureCategory.RUNTIME_ERROR,
            f"{name} exited {completed.returncode}: {stderr}",
        )
    return completed.stdout


def _cli_argv(name: str) -> list[str]:
    """Runtime-specific argv for a one-shot non-interactive session.

    Kept minimal; each runtime's non-interactive contract is documented in
    research.md §1. Consumers may set SPAEX_LLM_MODEL and use the API path
    for full determinism.
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


def _parse(raw: str, *, log_path: Path) -> ComposerResult:
    """Parse a Composer response into Shape A or Shape B."""
    match = _SENTINEL_RE.search(raw)
    if match is None:
        _write_composer_log(log_path, raw)
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            "Composer output missing SPAEX-COMPOSER sentinel block",
        )
        raise AssertionError("unreachable")
    try:
        envelope = json.loads(match.group("json"))
    except json.JSONDecodeError as exc:
        _write_composer_log(log_path, raw)
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            f"Composer sentinel JSON invalid: {exc}",
        )
        raise AssertionError("unreachable")
    if not isinstance(envelope, dict):
        _write_composer_log(log_path, raw)
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            f"Composer sentinel JSON must be an object; got {type(envelope).__name__}",
        )
        raise AssertionError("unreachable")

    shape_kind = envelope.get("type")
    if shape_kind == "composed":
        body = raw[match.end():].lstrip("\n\r ")
        if not body:
            _write_composer_log(log_path, raw)
            raise_for(
                ComposerFailureCategory.INVALID_OUTPUT,
                "Shape A response missing composed constitution body",
            )
            raise AssertionError("unreachable")
        return ComposedShape(body=body)
    if shape_kind == "questions":
        questions_raw = envelope.get("questions") or ()
        if not isinstance(questions_raw, list) or not questions_raw:
            _write_composer_log(log_path, raw)
            raise_for(
                ComposerFailureCategory.INVALID_OUTPUT,
                "Shape B response has no questions",
            )
            raise AssertionError("unreachable")
        parsed = tuple(_parse_question(q, log_path=log_path, raw=raw) for q in questions_raw)
        return QuestionsShape(questions=parsed)

    _write_composer_log(log_path, raw)
    raise_for(
        ComposerFailureCategory.INVALID_OUTPUT,
        f"Composer sentinel type {shape_kind!r} is not 'composed' or 'questions'",
    )
    raise AssertionError("unreachable")


def _parse_question(
    raw: Any, *, log_path: Path, raw_output: str = ""
) -> ClarificationQuestion:
    if not isinstance(raw, dict):
        _write_composer_log(log_path, raw_output or json.dumps(raw))
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            f"Shape B question must be an object; got {type(raw).__name__}",
        )
        raise AssertionError("unreachable")
    kind = raw.get("kind")
    if kind not in ("overlap", "contradiction"):
        _write_composer_log(log_path, raw_output or json.dumps(raw))
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            f"Shape B question kind {kind!r} not in overlap|contradiction",
        )
        raise AssertionError("unreachable")
    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        _write_composer_log(log_path, raw_output or json.dumps(raw))
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            "Shape B question text must be a non-empty string",
        )
        raise AssertionError("unreachable")
    cited_raw = raw.get("cited_fragments") or ()
    cited: list[dict[str, str]] = []
    if not isinstance(cited_raw, list):
        _write_composer_log(log_path, raw_output or json.dumps(raw))
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


def _write_composer_log(path: Path, raw: str) -> None:
    """Best-effort write of raw Composer output for invalid-output diagnostics."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
    except OSError:
        pass


def _classify_api_exception(exc: Exception) -> ComposerFailureCategory:
    """Map a litellm exception class name into a Composer failure category.

    Kept string-based to avoid a hard import on litellm's exception hierarchy
    (which changes across versions). Falls back to `runtime-error`.
    """
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return ComposerFailureCategory.TIMEOUT
    if "ratelimit" in name or "quota" in name or "insufficient" in name:
        return ComposerFailureCategory.QUOTA
    if "auth" in name or "permission" in name:
        return ComposerFailureCategory.RUNTIME_ERROR
    return ComposerFailureCategory.RUNTIME_ERROR


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
    "MODEL_OVERRIDE_ENV",
    "SENTINEL_BEGIN",
    "SENTINEL_END",
    "TIMEOUT_ENV",
    "ClarificationQuestion",
    "ComposedShape",
    "ComposerInput",
    "ComposerResult",
    "InvokeOptions",
    "InvokeOutcome",
    "QuestionsShape",
    "RuntimeDescriptor",
    "invoke_composer",
]
