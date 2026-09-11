"""Composer quota fault-injection (Spec 023 T025, SC-011, exit 33)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior.composer import invoke as invoke_module
from spaex.behavior.composer.failure import ComposerQuotaError, ComposerRuntimeError
from spaex.behavior.composer.invoke import ComposerInput, InvokeOptions
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


def test_cli_quota_signal_raises_quota_error(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(invoke_module.shutil, "which", lambda _name: "/bin/runtime")
    monkeypatch.setattr(
        invoke_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="429 Resource Exhausted: quota exceeded"
        ),
    )

    with pytest.raises(ComposerQuotaError):
        invoke_module.invoke_composer(
            ComposerInput(fragments=()),
            repo_root=repo_root,
            options=InvokeOptions(forced_cli_runtimes=("claude",)),
        )


def test_cli_non_quota_failure_remains_runtime_error(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(invoke_module.shutil, "which", lambda _name: "/bin/runtime")
    monkeypatch.setattr(
        invoke_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="invalid command line"
        ),
    )

    with pytest.raises(ComposerRuntimeError):
        invoke_module.invoke_composer(
            ComposerInput(fragments=()),
            repo_root=repo_root,
            options=InvokeOptions(forced_cli_runtimes=("claude",)),
        )
