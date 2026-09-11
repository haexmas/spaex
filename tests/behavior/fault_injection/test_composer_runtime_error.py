"""Composer runtime-error fault-injection (Spec 023 T024, SC-011, exit 31)."""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.behavior.composer.failure import ComposerRuntimeError
from spaex.util import exit_codes


def test_runtime_error_raises_typed_error_with_exit_31(
    mock_composer, repo_root: Path
) -> None:
    composer = mock_composer("runtime-error")

    with pytest.raises(ComposerRuntimeError) as exc:
        composer.invoke(repo_root)

    assert exc.value.exit_code == exit_codes.BEHAVIOR_COMPOSER_RUNTIME_ERROR
    assert exc.value.diagnostic_key == "behavior-composer-runtime-error"
    assert exit_codes.BEHAVIOR_COMPOSER_RUNTIME_ERROR == 31


def test_runtime_error_message_carries_original_exception(
    mock_composer, repo_root: Path
) -> None:
    composer = mock_composer("runtime-error")
    with pytest.raises(ComposerRuntimeError) as exc:
        composer.invoke(repo_root)
    assert "mock composer runtime error" in str(exc.value)
