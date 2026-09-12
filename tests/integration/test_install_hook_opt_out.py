"""T032-T034 - integration tests for Spec 016 User Story 3 (`--no-install-hooks`)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import add as add_cli
from spaex.cli import install as install_cli
from spaex.cli.main import _build_parser
from spaex.git.cache import clone_dir
from spaex.model.install_lock import InstallLock

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_MOLECULE_ID = "com.example.publisher.markerhook"
_CANONICAL = "https://example.invalid/example/publisher"
_MARKER_NAME = "hook-marker.txt"

# The hook writes a single marker file into the consumer repo. When the
# opt-out flag skips execution, the marker MUST NOT appear; when the flag
# is absent, the marker MUST appear exactly once.
_HOOK_SCRIPT = f'''#!/usr/bin/env python3
"""Marker-writing install-hook (Spec 016 US3 fixture)."""
from pathlib import Path
import sys

marker = Path.cwd() / {_MARKER_NAME!r}
marker.write_text("ran\\n", encoding="utf-8")
sys.exit(0)
'''


def _git(cwd: Path, *args: str) -> str:
    """Run a git command in ``cwd`` and return its trimmed stdout."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_marker_molecule(tmp_path: Path) -> tuple[str, str, Path]:
    """Create a bare publisher clone whose one molecule writes a marker file."""
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
                    _MOLECULE_ID: {"path": "marker-hook", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )

    mol_dir = working / "marker-hook"
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
                    "interpreter": sys.executable,
                    "script": "install.py",
                    "on_failure": "abort",
                },
            },
            indent=2,
        )
    )
    (mol_dir / "constitution.md").write_text(
        "# Principle: marker-hook opt-out demo\n\nSpec 016 US3.\n"
    )
    (mol_dir / "install.py").write_text(_HOOK_SCRIPT)

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "marker-hook 1.0.0 with install_hook")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head, state_root


def _make_consumer(tmp_path: Path) -> Path:
    """Create a minimal v4 consumer project for the integration scenario."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex").mkdir()
    (consumer / ".spaex/manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [],
            }
        )
    )
    (consumer / ".harness-id").write_text("com.example.project-consumer")
    return consumer


def _run_add(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_url: str,
    revision: str,
    skip_hooks: bool = False,
    molecule_ids: str = _MOLECULE_ID,
) -> int:
    """Run ``spaex add`` in-process with the requested hook policy."""
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(
        repo_root=str(consumer),
        source_url=source_url,
        molecule_ids=molecule_ids,
        revision=revision,
        all=False,
        lock_timeout=5.0,
        skip_hooks=skip_hooks,
    )
    return add_cli.run(ns)


def _run_install(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    skip_hooks: bool = False,
) -> int:
    """Run ``spaex install`` in-process with the requested hook policy."""
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(
        repo_root=str(consumer),
        lock_timeout=5.0,
        skip_hooks=skip_hooks,
    )
    return install_cli.run(ns)


def _read_lock(consumer: Path) -> InstallLock:
    """Read the consumer's published install lock."""
    return InstallLock.from_json(
        (consumer / ".spaex" / "install.lock").read_bytes()
    )


def test_no_install_hooks_is_exposed_by_cli_parser() -> None:
    """Both public commands expose the documented opt-out flag."""
    parser = _build_parser()

    install_args = parser.parse_args(["install", "--no-install-hooks"])
    assert install_args.skip_hooks is True

    add_args = parser.parse_args(
        ["add", _CANONICAL, _MOLECULE_ID, "--no-install-hooks"]
    )
    assert add_args.skip_hooks is True


# --- T032 AS1 -------------------------------------------------------------


def test_no_install_hooks_skips_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS1: hook is not launched; atoms and lock still land; hook_status=skipped."""
    canonical, head, state_root = _publish_marker_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    rc = _run_add(
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        revision=head,
        skip_hooks=True,
    )
    assert rc == 0

    assert not (consumer / _MARKER_NAME).exists()

    constitution = (consumer / ".spaex" / "constitution.md").read_text(
        encoding="utf-8"
    )
    assert "marker-hook opt-out demo" in constitution

    lock = _read_lock(consumer)
    assert len(lock.molecules) == 1
    entry = lock.molecules[0]
    assert entry.id == _MOLECULE_ID
    assert entry.hook_status == "skipped"


# --- T033 AS2 -------------------------------------------------------------


def test_no_install_hooks_is_per_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS2: opt-out applies only to the flagged invocation; a later install runs the hook."""
    canonical, head, state_root = _publish_marker_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    assert (
        _run_add(
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            revision=head,
            skip_hooks=True,
        )
        == 0
    )
    assert not (consumer / _MARKER_NAME).exists()
    assert _read_lock(consumer).molecules[0].hook_status == "skipped"

    assert _run_install(consumer, state_root, monkeypatch) == 0

    marker = consumer / _MARKER_NAME
    assert marker.exists()
    assert marker.read_text(encoding="utf-8") == "ran\n"
    assert _read_lock(consumer).molecules[0].hook_status == "ok"


# --- T034 FR-027 propagation --------------------------------------------


def test_no_install_hooks_via_spaex_add_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-027: `spaex add --no-install-hooks` propagates skip through the internal install."""
    canonical, head, state_root = _publish_marker_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    rc = _run_add(
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        revision=head,
        skip_hooks=True,
    )
    assert rc == 0

    assert not (consumer / _MARKER_NAME).exists()
    assert _read_lock(consumer).molecules[0].hook_status == "skipped"


def test_no_install_hooks_direct_install_is_per_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS2: direct install accepts the opt-out and later runs the hook again."""
    canonical, head, state_root = _publish_marker_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    assert (
        _run_add(
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            revision=head,
        )
        == 0
    )
    marker = consumer / _MARKER_NAME
    assert marker.exists()
    marker.unlink()

    assert _run_install(consumer, state_root, monkeypatch, skip_hooks=True) == 0
    assert not marker.exists()
    assert _read_lock(consumer).molecules[0].hook_status == "skipped"

    assert _run_install(consumer, state_root, monkeypatch) == 0
    assert marker.read_text(encoding="utf-8") == "ran\n"
    assert _read_lock(consumer).molecules[0].hook_status == "ok"
