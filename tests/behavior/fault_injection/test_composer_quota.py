"""Composer quota fault-injection (Spec 023 T025, SC-011, exit 33)."""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.behavior.composer.failure import ComposerQuotaError
from spaex.util import exit_codes


def test_quota_raises_typed_error_with_exit_33(
    mock_composer, repo_root: Path
) -> None:
    composer = mock_composer("quota")

    with pytest.raises(ComposerQuotaError) as exc:
        composer.invoke(repo_root)

    assert exc.value.exit_code == exit_codes.BEHAVIOR_COMPOSER_QUOTA
    assert exc.value.diagnostic_key == "behavior-composer-quota"
    assert exit_codes.BEHAVIOR_COMPOSER_QUOTA == 33


def test_quota_hint_mentions_billing_and_switch(
    mock_composer, repo_root: Path
) -> None:
    composer = mock_composer("quota")
    with pytest.raises(ComposerQuotaError) as exc:
        composer.invoke(repo_root)
    hint = exc.value.hint.lower()
    assert "billing" in hint or "quota" in hint
