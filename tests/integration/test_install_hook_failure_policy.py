"""T025-T028 - integration tests for Spec 016 User Story 2 failure policy."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import add as add_cli
from spaex.migrate.transform import clone_dir
from spaex.model.install_lock import InstallLock
from spaex.util.errors import HaexError, InstallTransactionFailedError

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_MOLECULE_ID = "com.example.publisher.failhook"
_CANONICAL = "https://example.invalid/example/failhook-publisher"

_FAILING_HOOK = '''#!/usr/bin/env python3
"""Non-zero-exit hook that leaves no side effect (Spec 016 US2 fixture)."""
import sys

sys.exit(1)
'''

_STDERR_NOISY_FAILING_HOOK = '''#!/usr/bin/env python3
"""Hook that writes distinctive stderr lines and then exits non-zero."""
import sys

print("HOOK_STDERR_LINE_ONE", file=sys.stderr)
print("HOOK_STDERR_LINE_TWO", file=sys.stderr)
sys.stderr.flush()
sys.exit(1)
'''


def _git(cwd: Path, *args: str) -> str:
    """Run Git in the fixture and return its stripped stdout."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_hook_molecule(
    tmp_path: Path,
    *,
    on_failure: str,
    hook_body: str = _FAILING_HOOK,
    interpreter: str | None = None,
) -> tuple[str, str, Path]:
    """Create a bare publisher whose sole molecule declares a hook and returns its SHA."""
    working = tmp_path / "publisher-working"
    working.mkdir()
    _git(working, "init", "-q", "-b", "main")
    _git(working, "config", "user.email", "author@example.com")
    _git(working, "config", "user.name", "author")
    _git(working, "config", "commit.gpgsign", "false")

    (working / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "publisher": "com.example.publisher",
                "molecules": {
                    _MOLECULE_ID: {"path": "failhook", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )

    mol_dir = working / "failhook"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOLECULE_ID,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"constitution": ["constitution.md"]},
                "install_hook": {
                    "interpreter": interpreter if interpreter is not None else sys.executable,
                    "script": "install.py",
                    "on_failure": on_failure,
                },
            },
            indent=2,
        )
    )
    (mol_dir / "constitution.md").write_text(
        "# Principle: failhook demo\n\nGoverned by Spec 016 US2.\n"
    )
    (mol_dir / "install.py").write_text(hook_body)

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "failhook 1.0.0")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head, state_root


def _make_consumer(tmp_path: Path) -> tuple[Path, bytes]:
    """Create a minimal consumer repository and snapshot its .spaex.json bytes."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    manifest_bytes = json.dumps(
        {
            "spaex_version": "4",
            "identity": "com.example.project-consumer",
            "compounds": [],
        }
    ).encode("utf-8")
    (consumer / ".spaex.json").write_bytes(manifest_bytes)
    (consumer / ".harness-id").write_text("com.example.project-consumer")
    return consumer, manifest_bytes


def _run_add(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_url: str,
    revision: str,
) -> int:
    """Invoke the add command against the fixture consumer and publisher."""
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(
        repo_root=str(consumer),
        source_url=source_url,
        molecule_ids=_MOLECULE_ID,
        revision=revision,
        all=False,
        lock_timeout=5.0,
    )
    return add_cli.run(ns)


def _read_lock(consumer: Path) -> InstallLock:
    """Read and parse the consumer's generated install lock."""
    return InstallLock.from_json(
        (consumer / ".spaex" / "install.lock").read_bytes()
    )


# --- T025 abort rollback --------------------------------------------------


def test_abort_rolls_back_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS1: on_failure=abort with exit 1 rolls back .spaex/ and .spaex.json."""
    canonical, head, state_root = _publish_hook_molecule(tmp_path, on_failure="abort")
    consumer, manifest_before = _make_consumer(tmp_path)
    spaex_dir = consumer / ".spaex"

    assert not spaex_dir.exists()

    with pytest.raises(InstallTransactionFailedError) as exc_info:
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)

    assert exc_info.value.context["install_key"] == "install-failed"
    cause = exc_info.value.__cause__
    assert isinstance(cause, HaexError)
    assert cause.diagnostic_key == "install-failed"
    assert cause.context.get("molecule_id") == _MOLECULE_ID
    assert cause.context.get("hook_failure") == "exit_1"

    assert (consumer / ".spaex.json").read_bytes() == manifest_before
    assert not spaex_dir.exists()


def test_abort_preserves_prior_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second, failing add at a new SHA leaves the first published state intact."""
    ok_hook = '''#!/usr/bin/env python3
import sys

sys.exit(0)
'''
    canonical, head_ok, state_root = _publish_hook_molecule(
        tmp_path, on_failure="abort", hook_body=ok_hook
    )
    consumer, _ = _make_consumer(tmp_path)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head_ok)
        == 0
    )
    lock_before = (consumer / ".spaex" / "install.lock").read_bytes()
    constitution_before = (consumer / ".spaex" / "constitution.md").read_bytes()
    manifest_before = (consumer / ".spaex.json").read_bytes()

    # Add a new failing commit on top and repin to it.
    working = tmp_path / "publisher-working"
    (working / "failhook" / "install.py").write_text(_FAILING_HOOK)
    _git(working, "add", "failhook/install.py")
    _git(working, "commit", "-q", "-m", "break the hook")
    head_fail = _git(working, "rev-parse", "HEAD")
    subprocess.run(
        ["git", "-C", str(clone_dir(state_root, canonical)), "fetch", "--quiet", "origin"],
        check=True,
    )

    with pytest.raises(InstallTransactionFailedError):
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head_fail)

    assert (consumer / ".spaex.json").read_bytes() == manifest_before
    assert (consumer / ".spaex" / "install.lock").read_bytes() == lock_before
    assert (consumer / ".spaex" / "constitution.md").read_bytes() == constitution_before


# --- T026 warn continues --------------------------------------------------


def test_warn_continues_with_hook_status_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """AS2: on_failure=warn writes install.lock with hook_status=failed and exits 0."""
    canonical, head, state_root = _publish_hook_molecule(tmp_path, on_failure="warn")
    consumer, _ = _make_consumer(tmp_path)

    rc = _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
    assert rc == 0

    assert (consumer / ".spaex" / "constitution.md").exists()

    lock = _read_lock(consumer)
    assert len(lock.molecules) == 1
    assert lock.molecules[0].hook_status == "failed"

    captured = capfd.readouterr()
    warn_lines = [
        line for line in captured.err.splitlines() if line.startswith("WARN:")
    ]
    assert warn_lines == [
        f"WARN: molecule {_MOLECULE_ID} install_hook failed (exit_1)"
    ]


# --- T027 missing interpreter treated per on_failure ----------------------


def test_missing_interpreter_abort_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing interpreter under abort triggers the same rollback path."""
    canonical, head, state_root = _publish_hook_molecule(
        tmp_path,
        on_failure="abort",
        interpreter="spaex-nonexistent-interpreter-xyz",
    )
    consumer, manifest_before = _make_consumer(tmp_path)

    with pytest.raises(InstallTransactionFailedError) as exc_info:
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)

    cause = exc_info.value.__cause__
    assert isinstance(cause, HaexError)
    assert cause.context.get("hook_failure") == "interpreter_not_on_path"

    assert (consumer / ".spaex.json").read_bytes() == manifest_before
    assert not (consumer / ".spaex").exists()


def test_missing_interpreter_warn_records_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Missing interpreter under warn records hook_status=failed and exits 0."""
    canonical, head, state_root = _publish_hook_molecule(
        tmp_path,
        on_failure="warn",
        interpreter="spaex-nonexistent-interpreter-xyz",
    )
    consumer, _ = _make_consumer(tmp_path)

    rc = _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
    assert rc == 0

    lock = _read_lock(consumer)
    assert lock.molecules[0].hook_status == "failed"

    captured = capfd.readouterr()
    warn_lines = [
        line for line in captured.err.splitlines() if line.startswith("WARN:")
    ]
    assert warn_lines == [
        f"WARN: molecule {_MOLECULE_ID} install_hook failed "
        "(interpreter_not_on_path)"
    ]


# --- T028 stderr not prefixed with WARN -----------------------------------


def test_stderr_not_prefixed_with_warn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Hook's inherited stderr lines pass through verbatim; ONE post-exit WARN summary."""
    canonical, head, state_root = _publish_hook_molecule(
        tmp_path, on_failure="warn", hook_body=_STDERR_NOISY_FAILING_HOOK
    )
    consumer, _ = _make_consumer(tmp_path)

    rc = _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
    assert rc == 0

    captured = capfd.readouterr()
    stderr_lines = captured.err.splitlines()

    assert "HOOK_STDERR_LINE_ONE" in stderr_lines
    assert "HOOK_STDERR_LINE_TWO" in stderr_lines
    for hook_line in ("HOOK_STDERR_LINE_ONE", "HOOK_STDERR_LINE_TWO"):
        assert not any(
            line.startswith("WARN:") and hook_line in line for line in stderr_lines
        ), f"{hook_line} was prefixed with WARN:"

    warn_lines = [line for line in stderr_lines if line.startswith("WARN:")]
    assert warn_lines == [
        f"WARN: molecule {_MOLECULE_ID} install_hook failed (exit_1)"
    ]
