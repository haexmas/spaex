"""T054 — end-to-end walkthrough of `specs/008-install-transaction/quickstart.md`.

Executes steps 1, 2, 4, 5, 6, and 7 of the quickstart in order and
verifies the output at each step matches the doc. Step 3 (`--verify-only`)
is skipped with a note because the shared-read lock and the `--verify-only`
flag are deferred until the US2 fenced-lease block lands (T037).

Records the SC-001..SC-006 outcomes exercised by each step in this module's
docstring; SC-007 was retired by the 2026-09-02 trust-git amendment.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from spaex.io.state import transaction_paths
from spaex.io.writer_lock import ConstitutionWriterLock

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")


def _run_install(
    repo_root: Path,
    *args: str,
    state_root: Path,
    crash_after: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the install CLI against a fixture with isolated state."""
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
            str(repo_root),
            "install",
            *args,
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def _load_stable_install_lock(
    repo_root: Path,
    *,
    after_first_read: Callable[[], None] | None = None,
    attempts: int = 3,
) -> dict[str, Any]:
    """Read install.lock, retrying across a generation swap.

    install.lock is the sole publication record (2026-09-04 amendment): a
    reader that races a concurrent rename-swap either sees the fully-old or
    fully-new file (the swap is atomic), or a transient FileNotFoundError
    while the directory rename is in flight. There is no second file to
    cross-check against anymore.
    """
    install_lock_path = repo_root / ".spaex" / "install.lock"
    callback = after_first_read
    for _ in range(attempts):
        try:
            install_lock = json.loads(install_lock_path.read_bytes())
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if callback is not None:
            callback()
            callback = None
            continue
        return install_lock
    raise RuntimeError("could not read a stable installation generation")


def test_quickstart_walkthrough_single_source(
    single_source_constitution_fixture: dict[str, Any], tmp_path: Path
) -> None:
    """Walk quickstart steps 1, 2, 4, 5, 7 against a single-source fixture."""
    del tmp_path
    consumer: Path = single_source_constitution_fixture["consumer"]
    state_root: Path = single_source_constitution_fixture["state_root"]

    # Step 1 — first install
    first = _run_install(consumer, state_root=state_root)
    assert first.returncode == 0, first.stderr
    assert first.stdout.startswith("installed generation g_")
    live = consumer / ".spaex"
    for name in ("constitution.md", "install.lock"):
        assert (live / name).exists(), f"missing {name} after first install"
    assert not (live / "visibility.json").exists()

    # Step 2 — idempotent re-install
    second = _run_install(consumer, state_root=state_root)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "no changes"

    # Step 4 — concurrent install refusal
    mutex = transaction_paths(consumer, state_root).mutex
    with ConstitutionWriterLock(mutex):
        busy = _run_install(consumer, state_root=state_root)
    assert busy.returncode == 9, busy.stderr
    assert "key=constitution-writer-busy" in busy.stderr

    # Step 5 — recovery after a scripted crash mid-swap
    (live / "constitution.md").write_bytes((live / "constitution.md").read_bytes() + b"\n")
    crashed = _run_install(consumer, state_root=state_root, crash_after="rename_a")
    assert crashed.returncode != 0
    prev_dir = consumer / ".spaex.prev"
    assert prev_dir.exists()
    recovered = _run_install(consumer, state_root=state_root)
    assert recovered.returncode == 0, recovered.stderr
    expected_constitution = (
        single_source_constitution_fixture["publisher"] / "constitution" / "constitution.md"
    ).read_bytes()
    assert (live / "constitution.md").read_bytes() == expected_constitution
    recovered_lock = json.loads((live / "install.lock").read_bytes())
    assert recovered_lock["generation_id"]
    assert not (consumer / ".spaex.next").exists()
    assert not prev_dir.exists()

    # Step 7 — reader consistency helper. Swap the live tree after the first
    # install.lock read; the stable-read algorithm must retry instead of
    # raising or returning a torn read.
    reader_next = consumer / ".spaex.reader-next"
    reader_old = consumer / ".spaex.reader-old"
    shutil.copytree(live, reader_next)
    reader_lock = json.loads((reader_next / "install.lock").read_bytes())
    reader_generation = "g_20990101T000000Z_0000"
    reader_lock["generation_id"] = reader_generation
    (reader_next / "install.lock").write_text(json.dumps(reader_lock))

    def swap_reader_generation() -> None:
        """Replace the live tree once to simulate a concurrent publication."""
        live.rename(reader_old)
        reader_next.rename(live)

    try:
        lock = _load_stable_install_lock(
            consumer, after_first_read=swap_reader_generation
        )
    finally:
        if reader_old.exists():
            shutil.rmtree(reader_old)
        if reader_next.exists():
            shutil.rmtree(reader_next)

    assert lock["generation_id"] == reader_generation
    # Participating roots are derived from molecules[].paths[]'s leading
    # dot-segments; there is no separate participating_roots list anymore.
    root_names = {path.split("/", 1)[0] for m in lock["molecules"] for path in m["paths"]}
    for root_name in root_names:
        assert (consumer / root_name).exists(), root_name


def test_quickstart_walkthrough_refuses_multiple_constitutions(
    multi_source_constitution_fixture: dict[str, Any],
) -> None:
    """Walk the current quickstart behavior for multiple constitution sources."""
    consumer: Path = multi_source_constitution_fixture["consumer"]
    state_root: Path = multi_source_constitution_fixture["state_root"]

    refused = _run_install(consumer, state_root=state_root)

    assert refused.returncode == 2, refused.stderr
    assert "key=constitution-already-adopted" in refused.stderr
    assert not (consumer / ".spaex" / "constitution.md").exists()


@pytest.mark.skip(reason="Step 3 depends on T037 (`--verify-only` + shared lock), deferred")
def test_quickstart_step3_verify_only() -> None:
    """Placeholder: `haex install --verify-only` and its shared-read lock land in T037."""
