"""T040-T041 - Spec 016 Phase 7 FR-025 hook-only transaction idempotency.

Verifies the two idempotency invariants that FR-025 requires spaex to
enforce AFTER hooks have run:

* T040: atom bytes unchanged, but a molecule's ``hook_status`` flips
  (e.g. ok to failed under ``on_failure=warn``) publishes a new
  install.lock generation carrying only the hook-status delta. The
  pinned molecule cache is NEVER mutated to steer the outcome; only a
  consumer-side environment variable toggles the hook's exit code.
* T041: atom bytes unchanged AND hook_status map unchanged is a clean
  no-op: the second run must reuse the existing generation id (no new
  ``.spaex/install.lock`` written).
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
from spaex.cli import install as install_cli
from spaex.migrate.transform import clone_dir
from spaex.model.install_lock import InstallLock

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_MOLECULE_ID = "com.example.publisher.togglehook"
_CANONICAL = "https://example.invalid/example/publisher"
_HOOK_FAIL_ENV = "SPAEX_TEST_TOGGLEHOOK_FAIL"

# Hook whose exit code is toggled by a consumer-side env var. The pinned
# molecule cache (script bytes) never changes across runs — FR-025's
# "atom bytes unchanged" precondition is preserved.
_TOGGLE_HOOK_SCRIPT = f'''#!/usr/bin/env python3
"""Toggle-hook fixture (Spec 016 T040): fails iff {_HOOK_FAIL_ENV}=1."""
import os
import sys

sys.exit(1 if os.environ.get({_HOOK_FAIL_ENV!r}) == "1" else 0)
'''


def _git(cwd: Path, *args: str) -> str:
    """Run Git in a fixture repository and return its stripped standard output."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_toggle_hook_molecule(tmp_path: Path) -> tuple[str, str, Path]:
    """Create a bare publisher clone whose molecule declares a warn-hook.

    ``on_failure=warn`` so a hook failure records ``hook_status=failed``
    without aborting the install: the whole point of T040 is a completed
    install that publishes a lock generation with a changed hook_status.
    """
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
                    _MOLECULE_ID: {"path": "toggle-hook", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )

    mol_dir = working / "toggle-hook"
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
                    "on_failure": "warn",
                },
            },
            indent=2,
        )
    )
    (mol_dir / "constitution.md").write_text(
        "# Principle: toggle-hook demo\n\nGoverned by Spec 016 FR-025.\n"
    )
    (mol_dir / "install.py").write_text(_TOGGLE_HOOK_SCRIPT)

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "toggle-hook 1.0.0")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head, state_root


def _make_consumer(tmp_path: Path) -> Path:
    """Create a minimal consumer repository for idempotency tests."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
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


def _run_install(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    """Invoke the install command against the fixture consumer."""
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0)
    return install_cli.run(ns)


def _read_lock(consumer: Path) -> InstallLock:
    """Read and parse the consumer's generated install lock."""
    return InstallLock.from_json(
        (consumer / ".spaex" / "install.lock").read_bytes()
    )


def _pinned_hook_script_bytes(state_root: Path, revision: str) -> bytes:
    """Return the install.py source pinned at ``revision`` in the bare cache.

    Reading the tracked file straight out of the bare git repository at
    the pinned SHA proves the molecule cache would produce the SAME
    hook bytes on both runs: any mutation of the pinned revision would
    surface here as changed bytes.
    """
    target = clone_dir(state_root, _CANONICAL)
    return subprocess.check_output(
        ["git", "-C", str(target), "show", f"{revision}:toggle-hook/install.py"]
    )


# --- T040 FR-025 hook-only transaction ------------------------------------


def test_hook_only_transaction_publishes_new_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-025: hook_status flip with unchanged atom bytes publishes a new lock generation."""
    canonical, head, state_root = _publish_toggle_hook_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    # First install: env var absent, hook exits 0, hook_status=ok.
    monkeypatch.delenv(_HOOK_FAIL_ENV, raising=False)
    assert (
        _run_add(
            consumer, state_root, monkeypatch, source_url=canonical, revision=head
        )
        == 0
    )
    first_lock = _read_lock(consumer)
    assert len(first_lock.molecules) == 1
    assert first_lock.molecules[0].hook_status == "ok"
    first_generation_id = first_lock.generation_id
    constitution_bytes = (
        consumer / ".spaex" / "constitution.md"
    ).read_bytes()
    hook_script_before = _pinned_hook_script_bytes(state_root, head)

    # Flip the switch: hook now exits 1 under on_failure=warn.
    monkeypatch.setenv(_HOOK_FAIL_ENV, "1")
    assert _run_install(consumer, state_root, monkeypatch) == 0

    second_lock = _read_lock(consumer)
    assert second_lock.generation_id != first_generation_id
    assert len(second_lock.molecules) == 1
    entry = second_lock.molecules[0]
    assert entry.id == _MOLECULE_ID
    assert entry.hook_status == "failed"
    assert entry.revision == head

    # Atom bytes and the pinned hook script stay untouched — the new
    # generation carries only the hook_status delta.
    assert (
        consumer / ".spaex" / "constitution.md"
    ).read_bytes() == constitution_bytes
    assert _pinned_hook_script_bytes(state_root, head) == hook_script_before


# --- T041 FR-025 clean no-op ---------------------------------------------


def test_full_no_op_when_atoms_and_hook_status_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-025: identical inputs and identical hook outcome do NOT publish a new generation."""
    canonical, head, state_root = _publish_toggle_hook_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    monkeypatch.delenv(_HOOK_FAIL_ENV, raising=False)
    assert (
        _run_add(
            consumer, state_root, monkeypatch, source_url=canonical, revision=head
        )
        == 0
    )
    first_lock_path = consumer / ".spaex" / "install.lock"
    first_generation_id = _read_lock(consumer).generation_id
    first_mtime_ns = first_lock_path.stat().st_mtime_ns

    # Second install with everything identical.
    assert _run_install(consumer, state_root, monkeypatch) == 0

    second_lock = _read_lock(consumer)
    # generation_id is the strongest guarantee, mtime is a defense in
    # depth against generation_id being stable while the file was
    # nevertheless rewritten.
    assert second_lock.generation_id == first_generation_id
    assert first_lock_path.stat().st_mtime_ns == first_mtime_ns
