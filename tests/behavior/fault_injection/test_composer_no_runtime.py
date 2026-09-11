"""Composer no-runtime fault-injection (Spec 023 T026, SC-011, exit 34)."""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.behavior.composer.failure import ComposerNoRuntimeError
from spaex.util import exit_codes


def test_no_runtime_raises_typed_error_with_exit_34(
    mock_composer, repo_root: Path
) -> None:
    composer = mock_composer("no-runtime")

    with pytest.raises(ComposerNoRuntimeError) as exc:
        composer.invoke(repo_root)

    assert exc.value.exit_code == exit_codes.BEHAVIOR_COMPOSER_NO_RUNTIME
    assert exc.value.diagnostic_key == "behavior-composer-no-runtime"
    assert exit_codes.BEHAVIOR_COMPOSER_NO_RUNTIME == 34


def test_no_runtime_hint_mentions_all_three_env_vars(
    mock_composer, repo_root: Path
) -> None:
    composer = mock_composer("no-runtime")
    with pytest.raises(ComposerNoRuntimeError) as exc:
        composer.invoke(repo_root)
    hint = exc.value.hint
    for token in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        assert token in hint
    for runtime in ("claude", "codex", "gemini"):
        assert runtime in hint
