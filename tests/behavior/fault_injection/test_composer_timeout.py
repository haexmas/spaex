"""Composer timeout fault-injection (Spec 023 T022, SC-011, exit 30)."""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.behavior.composer.failure import ComposerTimeoutError
from spaex.util import exit_codes


def test_timeout_scenario_raises_typed_error_with_exit_30(
    mock_composer, repo_root: Path
) -> None:
    composer = mock_composer("timeout")

    with pytest.raises(ComposerTimeoutError) as exc:
        composer.invoke(repo_root)

    assert exc.value.exit_code == exit_codes.BEHAVIOR_COMPOSER_TIMEOUT
    assert exc.value.diagnostic_key == "behavior-composer-timeout"
    assert exit_codes.BEHAVIOR_COMPOSER_TIMEOUT == 30
    assert composer.calls, "api caller must have been invoked at least once"


def test_timeout_diagnostic_hint_mentions_budget(
    mock_composer, repo_root: Path
) -> None:
    composer = mock_composer("timeout")
    with pytest.raises(ComposerTimeoutError) as exc:
        composer.invoke(repo_root)
    assert "SPAEX_COMPOSER_TIMEOUT" in exc.value.hint
