"""Progress/timing visibility for the Composer's real-CLI subprocess call.

A composer invocation that runs long gave no signal at all until either
success or the bare timeout diagnostic — indistinguishable from a genuinely
stuck call. `_call_cli` now reports when it starts and how long a response
took, and a timeout's diagnostic carries host load averages so a
contention-caused timeout is recognizable without a separate investigation.
"""

from __future__ import annotations

import subprocess

import pytest

from spaex.behavior.composer import invoke as invoke_mod
from spaex.behavior.composer.failure import ComposerTimeoutError


def _fake_completed(stdout: str = "ok", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["claude", "--print"], returncode=returncode, stdout=stdout, stderr=""
    )


def test_call_cli_reports_invocation_and_elapsed_time(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        invoke_mod.subprocess, "run", lambda *a, **k: _fake_completed()
    )

    result = invoke_mod._call_cli("claude", "system prompt", "payload", timeout=30.0)

    assert result == "ok"
    out = capsys.readouterr().out
    assert "composer: invoking claude" in out
    assert "timeout 30s" in out
    assert "composer: claude responded in" in out


def test_call_cli_timeout_message_includes_host_load(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["claude", "--print"], timeout=30.0)

    monkeypatch.setattr(invoke_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(invoke_mod.os, "getloadavg", lambda: (1.5, 2.25, 3.125))

    with pytest.raises(ComposerTimeoutError) as excinfo:
        invoke_mod._call_cli("claude", "system prompt", "payload", timeout=30.0)

    assert "timed out after 30.0s" in excinfo.value.message
    assert "host load avg 1/5/15m: 1.50/2.25/3.12" in excinfo.value.message


def test_call_cli_timeout_message_omits_load_when_unavailable(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["claude", "--print"], timeout=30.0)

    def fake_getloadavg():
        raise OSError("not supported on this platform")

    monkeypatch.setattr(invoke_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(invoke_mod.os, "getloadavg", fake_getloadavg)

    with pytest.raises(ComposerTimeoutError) as excinfo:
        invoke_mod._call_cli("claude", "system prompt", "payload", timeout=30.0)

    assert excinfo.value.message == "claude timed out after 30.0s"
