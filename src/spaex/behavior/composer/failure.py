"""Composer failure categorization (Spec 023 T020).

Five categories per research.md §8, each mapped to a stable exit code from
`spaex.util.exit_codes` and to a `HaexError` subclass so the CLI's
`emit_refuse` renders a typed diagnostic. Silent degradation to raw fragment
concatenation is explicitly forbidden (FR-012a); every abort surfaces a
category.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from spaex.util import exit_codes
from spaex.util.errors import HaexError

QUOTA_FAILURE_SIGNALS: tuple[str, ...] = (
    "429",
    "billing",
    "budget limit",
    "insufficient_quota",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "quota",
    "resource exhausted",
    "resource_exhausted",
    "usage limit",
    "usage_limit",
)


class ComposerFailureCategory(str, enum.Enum):
    """Every failure surface a Composer invocation can produce."""

    TIMEOUT = "timeout"
    RUNTIME_ERROR = "runtime-error"
    INVALID_OUTPUT = "invalid-output"
    QUOTA = "quota"
    NO_RUNTIME = "no-runtime"


CATEGORY_EXIT_CODE: dict[ComposerFailureCategory, int] = {
    ComposerFailureCategory.TIMEOUT: exit_codes.BEHAVIOR_COMPOSER_TIMEOUT,
    ComposerFailureCategory.RUNTIME_ERROR: exit_codes.BEHAVIOR_COMPOSER_RUNTIME_ERROR,
    ComposerFailureCategory.INVALID_OUTPUT: exit_codes.BEHAVIOR_COMPOSER_INVALID_OUTPUT,
    ComposerFailureCategory.QUOTA: exit_codes.BEHAVIOR_COMPOSER_QUOTA,
    ComposerFailureCategory.NO_RUNTIME: exit_codes.BEHAVIOR_COMPOSER_NO_RUNTIME,
}


@dataclass
class ComposerTimeoutError(HaexError):
    diagnostic_key: str = "behavior-composer-timeout"
    exit_code: int = exit_codes.BEHAVIOR_COMPOSER_TIMEOUT
    hint: str = (
        "Composer exceeded SPAEX_COMPOSER_TIMEOUT. Increase the budget, "
        "reduce the fragment set, or switch to a faster runtime."
    )


@dataclass
class ComposerRuntimeError(HaexError):
    diagnostic_key: str = "behavior-composer-runtime-error"
    exit_code: int = exit_codes.BEHAVIOR_COMPOSER_RUNTIME_ERROR
    hint: str = "Check the runtime's own diagnostics; the composer subprocess failed."


@dataclass
class ComposerInvalidOutputError(HaexError):
    diagnostic_key: str = "behavior-composer-invalid-output"
    exit_code: int = exit_codes.BEHAVIOR_COMPOSER_INVALID_OUTPUT
    hint: str = (
        "The Composer's output did not match the response contract. See "
        "$SPAEX_COMPOSER_LOG (default `.spaex/composer.log`) for the raw "
        "response, then adjust the prompt override or file a bug."
    )


@dataclass
class ComposerQuotaError(HaexError):
    diagnostic_key: str = "behavior-composer-quota"
    exit_code: int = exit_codes.BEHAVIOR_COMPOSER_QUOTA
    hint: str = (
        "The Composer runtime returned a quota/billing failure. Check API "
        "billing or switch to another installed CLI runtime."
    )


@dataclass
class ComposerNoRuntimeError(HaexError):
    diagnostic_key: str = "behavior-composer-no-runtime"
    exit_code: int = exit_codes.BEHAVIOR_COMPOSER_NO_RUNTIME
    hint: str = (
        "No LLM runtime available. Install `claude`, `codex`, or `gemini` "
        "on PATH so `spaex install` can shell out to compose `.spaex/constitution.md`."
    )


CATEGORY_ERROR: dict[ComposerFailureCategory, type[HaexError]] = {
    ComposerFailureCategory.TIMEOUT: ComposerTimeoutError,
    ComposerFailureCategory.RUNTIME_ERROR: ComposerRuntimeError,
    ComposerFailureCategory.INVALID_OUTPUT: ComposerInvalidOutputError,
    ComposerFailureCategory.QUOTA: ComposerQuotaError,
    ComposerFailureCategory.NO_RUNTIME: ComposerNoRuntimeError,
}


def raise_for(
    category: ComposerFailureCategory,
    message: str,
    *,
    context: dict[str, str] | None = None,
) -> None:
    """Raise the `HaexError` subclass matching `category` with `message`.

    Every raise runs through this helper so the mapping stays in one place
    and no caller can accidentally raise a bare `HaexError` for a Composer
    failure (which would lose the fail-fast exit-code contract).
    """
    error_cls = CATEGORY_ERROR[category]
    raise error_cls(message=message, context=context or {})


__all__ = [
    "CATEGORY_ERROR",
    "CATEGORY_EXIT_CODE",
    "QUOTA_FAILURE_SIGNALS",
    "ComposerFailureCategory",
    "ComposerInvalidOutputError",
    "ComposerNoRuntimeError",
    "ComposerQuotaError",
    "ComposerRuntimeError",
    "ComposerTimeoutError",
    "raise_for",
]
