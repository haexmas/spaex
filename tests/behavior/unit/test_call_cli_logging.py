"""Progress/timing visibility for the Composer's real-CLI subprocess call.

A composer invocation that runs long gave no signal at all until either
success or the bare timeout diagnostic — indistinguishable from a genuinely
stuck call. `_call_cli` now reports when it starts and how long a response
took, and a timeout's diagnostic carries host load averages so a
contention-caused timeout is recognizable without a separate investigation.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from spaex.behavior.composer import invoke as invoke_mod
from spaex.behavior.composer.failure import ComposerRuntimeError, ComposerTimeoutError
from spaex.behavior.composer.invoke import ComposerInput, InvokeOptions, invoke_composer


def _fake_completed(stdout: str = "ok", returncode: int = 0) -> subprocess.CompletedProcess:
    """Build the minimal completed-process value returned by the CLI stub."""
    return subprocess.CompletedProcess(
        args=["claude", "--print"], returncode=returncode, stdout=stdout, stderr=""
    )


def test_call_cli_reports_invocation_and_elapsed_time(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report invocation and response timing for a successful CLI call."""
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
    """Include formatted load averages when the platform provides them."""
    def fake_run(*args, **kwargs):
        """Force the subprocess call down its timeout path."""
        raise subprocess.TimeoutExpired(cmd=["claude", "--print"], timeout=30.0)

    monkeypatch.setattr(invoke_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        invoke_mod.os, "getloadavg", lambda: (1.5, 2.25, 3.125), raising=False
    )

    with pytest.raises(ComposerTimeoutError) as excinfo:
        invoke_mod._call_cli("claude", "system prompt", "payload", timeout=30.0)

    assert "timed out after 30.0s" in excinfo.value.message
    assert "host load avg 1/5/15m: 1.50/2.25/3.12" in excinfo.value.message


def test_call_cli_timeout_message_omits_load_when_unavailable(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omit load averages when the platform's implementation raises OSError."""
    def fake_run(*args, **kwargs):
        """Force the subprocess call down its timeout path."""
        raise subprocess.TimeoutExpired(cmd=["claude", "--print"], timeout=30.0)

    def fake_getloadavg():
        """Represent a Unix runtime that cannot provide load averages."""
        raise OSError("not supported on this platform")

    monkeypatch.setattr(invoke_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(invoke_mod.os, "getloadavg", fake_getloadavg, raising=False)

    with pytest.raises(ComposerTimeoutError) as excinfo:
        invoke_mod._call_cli("claude", "system prompt", "payload", timeout=30.0)

    assert excinfo.value.message == "claude timed out after 30.0s"


def test_call_cli_timeout_message_omits_load_when_attribute_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omit load averages on platforms such as Windows without getloadavg."""
    def fake_run(*args, **kwargs):
        """Force the subprocess call down its timeout path."""
        raise subprocess.TimeoutExpired(cmd=["claude", "--print"], timeout=30.0)

    monkeypatch.setattr(invoke_mod.subprocess, "run", fake_run)
    monkeypatch.delattr(invoke_mod.os, "getloadavg", raising=False)

    with pytest.raises(ComposerTimeoutError) as excinfo:
        invoke_mod._call_cli("claude", "system prompt", "payload", timeout=30.0)

    assert excinfo.value.message == "claude timed out after 30.0s"


def test_cli_failure_logs_partial_output_and_identifies_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain stdout from a completed failed step and name that step."""
    log_path = tmp_path / ".spaex" / "composer.log"
    monkeypatch.setattr(invoke_mod.shutil, "which", lambda _name: "/bin/runtime")
    monkeypatch.setattr(
        invoke_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: _fake_completed(
            stdout="partial composer output", returncode=1
        ),
    )

    with pytest.raises(ComposerRuntimeError) as excinfo:
        invoke_composer(
            ComposerInput(fragments=()),
            repo_root=tmp_path,
            options=InvokeOptions(
                forced_cli_runtimes=("claude",), composer_log_path=log_path
            ),
            step="batch-2",
        )

    assert excinfo.value.context["step"] == "batch-2"
    entries = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert entries == [
        {
            "step": "batch-2",
            "invocation": 1,
            "phase": "initial",
            "raw_output": "partial composer output",
            "outcome": "runtime-error",
        }
    ]


def test_cli_timeout_logs_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain partial stdout when a CLI process times out."""
    log_path = tmp_path / ".spaex" / "composer.log"
    monkeypatch.setattr(invoke_mod.shutil, "which", lambda _name: "/bin/runtime")

    def timed_out(*_args: object, **_kwargs: object) -> object:
        """Simulate a timed-out CLI that emitted a partial response."""
        raise subprocess.TimeoutExpired(
            cmd=["claude", "--print"], timeout=30.0, output="partial response"
        )

    monkeypatch.setattr(invoke_mod.subprocess, "run", timed_out)

    with pytest.raises(ComposerTimeoutError):
        invoke_composer(
            ComposerInput(fragments=()),
            repo_root=tmp_path,
            options=InvokeOptions(
                forced_cli_runtimes=("claude",), composer_log_path=log_path
            ),
            step="batch-3",
        )

    entries = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert entries[0]["step"] == "batch-3"
    assert entries[0]["raw_output"] == "partial response"
    assert entries[0]["outcome"] == "timeout"


def test_cli_argv_appends_model_flag_per_runtime_when_env_var_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Append --model <value> for every runtime when SPAEX_LLM_MODEL is set
    (contracts/cli-surface.md documents this env var; the CLI-only 4.2.0
    pivot never wired it up until a real dogfood run got stuck on a
    runtime's own default model)."""
    monkeypatch.setenv("SPAEX_LLM_MODEL", "sonnet")
    assert invoke_mod._cli_argv("claude") == ["claude", "--print", "--model", "sonnet"]
    assert invoke_mod._cli_argv("codex") == ["codex", "exec", "--model", "sonnet"]
    assert invoke_mod._cli_argv("gemini") == [
        "gemini",
        "--prompt",
        "-",
        "--model",
        "sonnet",
    ]


def test_cli_argv_omits_model_flag_when_env_var_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default to the runtime's own canonical model when unset."""
    monkeypatch.delenv("SPAEX_LLM_MODEL", raising=False)
    assert invoke_mod._cli_argv("claude") == ["claude", "--print"]
    assert invoke_mod._cli_argv("codex") == ["codex", "exec"]
    assert invoke_mod._cli_argv("gemini") == ["gemini", "--prompt", "-"]
