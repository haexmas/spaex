"""SC-001 crash-safety sweep across rename-swap boundaries.

Each child is terminated at a real in-flight boundary, then a subsequent
`haex install` cleans any leftover `<root>.next/` / `<root>.prev/` siblings
and either reinstalls from scratch (pre-rename-B crash) or takes the
idempotent no-op path (post-rename-B crash) — the 2026-09-02 detect+retry
model that replaced the earlier 8-state recovery-forward dispatcher.

Uses the `SPAEX_CRASH_AFTER` test seam in `spaex.io.transaction` to
terminate the child process (SIGKILL on POSIX, TerminateProcess-equivalent on
Windows) at each rename-swap boundary rather than racing an external timer
against the write.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from spaex.io import json_deterministic

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("git") is None, reason="git binary required"),
]

_CRASH_CASES = [
    ("pre_swap", False),
    ("pre_swap", True),
    ("rename_a", False),
    ("rename_a", True),
    ("rename_b", False),
    ("rename_b", True),
]


def _run(
    consumer: Path, state_root: Path, *, crash_after: str | None = None
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SPAEX_STATE"] = str(state_root)
    if crash_after is not None:
        env["SPAEX_CRASH_AFTER"] = crash_after
    else:
        env.pop("SPAEX_CRASH_AFTER", None)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "spaex",
            "--repo-root",
            str(consumer),
            "install",
        ],
        capture_output=True,
        env=env,
    )


@pytest.mark.parametrize(
    "crash_point,preexisting",
    _CRASH_CASES,
    ids=[f"{point}-{'existing' if existing else 'absent'}" for point, existing in _CRASH_CASES],
)
def test_crash_at_boundary_converges_on_retry(
    single_source_constitution_fixture: dict, crash_point: str, preexisting: bool
) -> None:
    """Recover each rename boundary and preserve the prior generation on failure."""
    consumer = single_source_constitution_fixture["consumer"]
    state_root = single_source_constitution_fixture["state_root"]

    if preexisting:
        clean = _run(consumer, state_root)
        assert clean.returncode == 0, clean.stderr.decode()
        # Make the next install publish a generation instead of taking the
        # single-source idempotence fast path.
        constitution_path = consumer / ".spaex" / "constitution.md"
        constitution_path.write_bytes(constitution_path.read_bytes() + b"\n")

    crashed = _run(consumer, state_root, crash_after=crash_point)
    assert crashed.returncode != 0, "the child process must not exit cleanly when killed"

    live = consumer / ".spaex"
    next_dir = consumer / ".spaex.next"
    prev_dir = consumer / ".spaex.prev"
    if crash_point == "pre_swap":
        assert live.exists() is preexisting
        assert next_dir.exists()
        assert not prev_dir.exists()
    elif crash_point == "rename_a":
        assert next_dir.exists()
        assert not live.exists()
        assert prev_dir.exists() is preexisting
    else:
        assert live.exists()
        if preexisting:
            assert prev_dir.exists()
        else:
            assert not prev_dir.exists()
        assert not next_dir.exists()

    if crash_point == "rename_a" and preexisting:
        previous_generation = (prev_dir / "constitution.md").read_bytes()
        manifest_path = consumer / ".spaex/manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        manifest["compounds"][0]["revision"] = "deadbeef" * 5
        manifest_path.write_bytes(json_deterministic.dumps(manifest))

        failed_retry = _run(consumer, state_root)

        assert failed_retry.returncode != 0
        assert live.exists()
        assert not next_dir.exists()
        assert not prev_dir.exists()
        assert (live / "constitution.md").read_bytes() == previous_generation

        manifest_path.write_bytes(manifest_bytes)

    recovered = _run(consumer, state_root)
    assert recovered.returncode == 0, recovered.stderr.decode()
    assert not next_dir.exists()
    assert not prev_dir.exists()

    constitution = (consumer / ".spaex" / "constitution.md").read_bytes()
    lock_data_1 = json.loads((consumer / ".spaex" / "install.lock").read_bytes())
    again = _run(consumer, state_root)
    assert again.returncode == 0, again.stderr.decode()
    assert (consumer / ".spaex" / "constitution.md").read_bytes() == constitution
    lock_data_2 = json.loads((consumer / ".spaex" / "install.lock").read_bytes())
    assert lock_data_1["generation_id"] == lock_data_2["generation_id"]
    lock_data_1["generation_id"] = None
    lock_data_2["generation_id"] = None
    assert lock_data_1 == lock_data_2


def test_rename_a_crash_restores_previous_before_retry_resolution(
    single_source_constitution_fixture: dict,
) -> None:
    """A failed retry restores P before a later retry may publish C2."""
    consumer = single_source_constitution_fixture["consumer"]
    state_root = single_source_constitution_fixture["state_root"]

    initial = _run(consumer, state_root)
    assert initial.returncode == 0, initial.stderr.decode()
    constitution_path = consumer / ".spaex" / "constitution.md"
    constitution_path.write_bytes(constitution_path.read_bytes() + b"\n")

    crashed = _run(consumer, state_root, crash_after="rename_a")
    assert crashed.returncode != 0

    live = consumer / ".spaex"
    next_dir = consumer / ".spaex.next"
    prev_dir = consumer / ".spaex.prev"
    prior_lock = json.loads((prev_dir / "install.lock").read_bytes())
    candidate_lock = json.loads((next_dir / "install.lock").read_bytes())
    assert prior_lock["generation_id"] != candidate_lock["generation_id"]

    manifest_path = consumer / ".spaex/manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    manifest["compounds"][0]["revision"] = "deadbeef" * 5
    manifest_path.write_bytes(json_deterministic.dumps(manifest))

    failed_retry = _run(consumer, state_root)
    assert failed_retry.returncode != 0
    assert live.exists()
    assert not next_dir.exists()
    assert not prev_dir.exists()
    assert json.loads((live / "install.lock").read_bytes()) == prior_lock

    manifest_path.write_bytes(manifest_bytes)
    recovered = _run(consumer, state_root)
    assert recovered.returncode == 0, recovered.stderr.decode()
    assert not next_dir.exists()
    assert not prev_dir.exists()
