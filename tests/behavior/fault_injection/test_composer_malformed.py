"""Composer invalid-output fault-injection (Spec 023 T023, SC-011, exit 32)."""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.behavior.composer.failure import ComposerInvalidOutputError
from spaex.util import exit_codes


def test_invalid_output_raises_typed_error_with_exit_32(
    mock_composer, repo_root: Path
) -> None:
    composer = mock_composer("invalid-output")

    with pytest.raises(ComposerInvalidOutputError) as exc:
        composer.invoke(repo_root)

    assert exc.value.exit_code == exit_codes.BEHAVIOR_COMPOSER_INVALID_OUTPUT
    assert exc.value.diagnostic_key == "behavior-composer-invalid-output"
    assert exit_codes.BEHAVIOR_COMPOSER_INVALID_OUTPUT == 32


def test_invalid_output_writes_raw_response_to_log(
    mock_composer, repo_root: Path
) -> None:
    composer = mock_composer("invalid-output")
    with pytest.raises(ComposerInvalidOutputError):
        composer.invoke(repo_root)

    log = repo_root / ".spaex" / "composer.log"
    assert log.exists(), "invalid-output must write the raw response to the composer log"
    assert "this is not a sentinel-wrapped response" in log.read_text(encoding="utf-8")


def test_shape_a_without_body_is_invalid_output(
    mock_composer, repo_root: Path
) -> None:
    empty_shape_a = (
        "<<<SPAEX-COMPOSER-BEGIN>>>\n"
        '{"type": "composed", "questions": []}\n'
        "<<<SPAEX-COMPOSER-END>>>\n"
    )
    composer = mock_composer("shape-a", shape_a_body=empty_shape_a)
    with pytest.raises(ComposerInvalidOutputError):
        composer.invoke(repo_root)


def test_unknown_sentinel_type_is_invalid_output(
    mock_composer, repo_root: Path
) -> None:
    weird = (
        "<<<SPAEX-COMPOSER-BEGIN>>>\n"
        '{"type": "verified", "questions": []}\n'
        "<<<SPAEX-COMPOSER-END>>>\n"
        "extra body\n"
    )
    composer = mock_composer("shape-a", shape_a_body=weird)
    with pytest.raises(ComposerInvalidOutputError):
        composer.invoke(repo_root)
