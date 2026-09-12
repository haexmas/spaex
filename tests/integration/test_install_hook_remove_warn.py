"""T043-T044 — integration tests for Spec 016 Phase 8 (FR-029 remove WARN).

Verifies that `spaex remove` emits a WARN to stderr when the retracted
molecule's install.lock record carries a hook_status (evidence it declared
install_hook), and does NOT emit that WARN for a molecule that never had one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import add as add_cli
from spaex.cli import remove as remove_cli
from spaex.git.cache import clone_dir

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_HOOK_MOLECULE_ID = "com.example.publisher.hookcarrier"
_HOOK_CANONICAL = "https://example.invalid/example/hook-publisher"

_HOOK_SCRIPT = '''#!/usr/bin/env python3
"""No-op install-hook fixture for FR-029 remove-WARN tests."""
import sys

sys.exit(0)
'''


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_hook_molecule(tmp_path: Path) -> tuple[str, str, Path]:
    """Create a bare publisher clone with one molecule that declares install_hook."""
    working = tmp_path / "hook-publisher-working"
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
                    _HOOK_MOLECULE_ID: {"path": "hookcarrier", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )

    mol_dir = working / "hookcarrier"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _HOOK_MOLECULE_ID,
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
        "# Principle: hookcarrier fixture (Spec 016 Phase 8)\n"
    )
    (mol_dir / "install.py").write_text(_HOOK_SCRIPT)

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "hookcarrier 1.0.0 with install_hook")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _HOOK_CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _HOOK_CANONICAL, head, state_root


def _make_consumer(tmp_path: Path) -> Path:
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


# --- T043 -----------------------------------------------------------------


def test_remove_hook_carrying_molecule_emits_warn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """After installing a hook-carrying molecule, `spaex remove` emits the
    FR-029 WARN naming the molecule id on stderr; exit code stays 0.
    """
    canonical, head, state_root = _publish_hook_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    add_rc = add_cli.run(
        SimpleNamespace(
            repo_root=str(consumer),
            source_url=canonical,
            molecule_ids=_HOOK_MOLECULE_ID,
            revision=head,
            all=False,
            lock_timeout=5.0,
        )
    )
    assert add_rc == 0
    capfd.readouterr()  # drain add-time output so the WARN check sees only remove.

    remove_rc = remove_cli.run(
        SimpleNamespace(
            repo_root=str(consumer),
            molecule_ids=_HOOK_MOLECULE_ID,
            lock_timeout=5.0,
        )
    )
    assert remove_rc == 0

    captured = capfd.readouterr()
    expected_warn = (
        f"WARN: molecule {_HOOK_MOLECULE_ID} had an install_hook; side effects "
        "(git hooks, gitignore entries, provisioned tools, "
        "agent-harness registrations) may remain. Consult the "
        "molecule's README for reverse steps."
    )
    assert expected_warn in captured.err, (
        f"expected FR-029 WARN on stderr, got:\n{captured.err}"
    )


def test_remove_duplicate_hook_carrying_molecule_emits_one_warn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Repeated molecule IDs remove once and emit one FR-029 WARN."""
    canonical, head, state_root = _publish_hook_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    add_rc = add_cli.run(
        SimpleNamespace(
            repo_root=str(consumer),
            source_url=canonical,
            molecule_ids=_HOOK_MOLECULE_ID,
            revision=head,
            all=False,
            lock_timeout=5.0,
        )
    )
    assert add_rc == 0
    capfd.readouterr()

    remove_rc = remove_cli.run(
        SimpleNamespace(
            repo_root=str(consumer),
            molecule_ids=f"{_HOOK_MOLECULE_ID},{_HOOK_MOLECULE_ID}",
            lock_timeout=5.0,
        )
    )
    assert remove_rc == 0

    captured = capfd.readouterr()
    expected_warn = f"WARN: molecule {_HOOK_MOLECULE_ID} had an install_hook;"
    assert captured.err.count(expected_warn) == 1, (
        f"expected one FR-029 WARN on stderr, got:\n{captured.err}"
    )
    assert captured.out.count(f"  {_HOOK_MOLECULE_ID}\n") == 1


# --- T044 -----------------------------------------------------------------


def test_remove_hook_less_molecule_no_warn(
    tmp_path: Path,
    haex_add_helpers,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A molecule that never declared install_hook must NOT trigger the
    FR-029 WARN on removal. Verifies WARN specificity.
    """
    plain_id = "com.example.publisher.plain"
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            plain_id: {
                "path": "plain",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    add_rc = haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=plain_id,
        revision=head,
    )
    assert add_rc == 0
    capfd.readouterr()

    remove_rc = haex_add_helpers["run_remove"](
        consumer, state_root, monkeypatch, molecule_ids=plain_id
    )
    assert remove_rc == 0

    captured = capfd.readouterr()
    for line in captured.err.splitlines():
        assert "install_hook" not in line, (
            f"hook-less removal must not mention install_hook, got: {line!r}"
        )
