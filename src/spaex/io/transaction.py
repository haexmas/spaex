"""Directory rename-swap publication for `.spaex/` (Spec 008 R1).

`publish_generation` writes a caller-supplied set of `(relative_path, bytes)`
files into `<root>.next/`, then performs the two atomic renames — `<root>` →
`<root>.prev` (skipped
when `<root>/` does not exist), then `<root>.next` → `<root>` — with a
parent-directory fsync after each rename. An optional `post_write_verify`
callback runs after the swap. `<root>.prev/` is removed as the transaction's
final step.

Stale-sibling cleanup lives in `spaex.install.inflight.clean_stale_siblings`;
callers must invoke it under the exclusive install lock BEFORE calling
`publish_generation` so any `<root>.next/` left over from a prior crashed install
is removed. A leftover `<root>.prev/` is retained until the replacement has
been staged, validated, and published successfully. Under the 2026-09-02
detect+retry simplification the recovery model is "reinstall converges" —
there is no mid-swap recovery-forward logic.

If `post_write_verify` raises after the swap, the swap is rolled back —
`<root>` is renamed back to `<root>.next` and, when `<root>.prev/` existed
before this transaction, `<root>.prev` is renamed back to `<root>`. The
caller's exception is re-raised.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from spaex.io.state import transaction_paths, write_identity_record

_IS_WINDOWS = sys.platform == "win32"

CONSTITUTION_NAME = "constitution.md"
INSTALL_LOCK_NAME = "install.lock"
INSTALL_MUTEX_NAME = "install.mutex"
SPAEX_DIR = ".spaex"


@dataclass(frozen=True)
class StagedFile:
    """One file to write into the staged `<root>.next/` directory."""

    relative_path: str
    data: bytes


def _crash_after(point: str) -> None:
    """Test seam — abruptly terminate the process at a named boundary."""
    if os.environ.get("SPAEX_CRASH_AFTER") != point:
        return
    os.kill(os.getpid(), signal.SIGTERM if _IS_WINDOWS else signal.SIGKILL)


def _fsync_dir(path: Path) -> None:
    if _IS_WINDOWS:
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_file(path: Path) -> None:
    if _IS_WINDOWS:
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _rmtree(path: Path) -> None:
    with suppress(FileNotFoundError):
        shutil.rmtree(str(path))


def _next_dir(live: Path) -> Path:
    return live.parent / f"{live.name}.next"


def _prev_dir(live: Path) -> Path:
    return live.parent / f"{live.name}.prev"


def _write_staging(next_dir: Path, files: Sequence[StagedFile]) -> None:
    """Write every staged file under `next_dir`, fsync each file and the dir."""
    for staged in files:
        target = next_dir / staged.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(staged.data)
            fh.flush()
            os.fsync(fh.fileno())
    _fsync_dir(next_dir)


def _rollback_swap(
    live: Path,
    next_dir: Path,
    prev_dir: Path,
    *,
    live_existed_before: bool,
) -> None:
    """Best-effort rollback: undo rename B (and rename A if it ran)."""
    parent = live.parent
    if live.exists():
        os.rename(str(live), str(next_dir))
        _fsync_dir(parent)
    if live_existed_before and prev_dir.exists():
        os.rename(str(prev_dir), str(live))
        _fsync_dir(parent)


@contextmanager
def stage_generation(
    live: Path,
    files: Iterable[StagedFile],
    *,
    state_root: Path | None = None,
    repo_root: Path | None = None,
) -> Iterator[None]:
    """Stage and temporarily activate a generation for pre-publication work.

    The candidate is fully written before it replaces ``live``. If the body
    of the context raises, the previous generation is restored; otherwise the
    candidate remains live and its previous generation is discarded. This is
    used for install hooks that must inspect the new atom content before the
    final lock, including hook status, is published.
    """
    files_list = list(files)
    parent = live.parent
    next_dir = _next_dir(live)
    prev_dir = _prev_dir(live)

    _rmtree(next_dir)
    next_dir.mkdir(parents=True, exist_ok=False)
    _fsync_dir(parent)
    live_existed_before = live.exists()
    rename_a_done = False

    try:
        _write_staging(next_dir, files_list)
        if state_root is not None:
            paths = transaction_paths(
                repo_root if repo_root is not None else parent,
                state_root,
            )
            write_identity_record(paths)

        if live_existed_before:
            if prev_dir.exists():
                _rmtree(prev_dir)
                _fsync_dir(parent)
            os.rename(str(live), str(prev_dir))
            _fsync_dir(parent)
            rename_a_done = True
        try:
            os.rename(str(next_dir), str(live))
        except BaseException:
            if rename_a_done:
                os.rename(str(prev_dir), str(live))
                _fsync_dir(parent)
                rename_a_done = False
            raise
        _fsync_dir(parent)

        try:
            yield
        except BaseException:
            _rollback_swap(
                live,
                next_dir,
                prev_dir,
                live_existed_before=live_existed_before,
            )
            rename_a_done = False
            raise

        if prev_dir.exists():
            _rmtree(prev_dir)
            _fsync_dir(parent)
    except BaseException:
        if not rename_a_done:
            _rmtree(next_dir)
        raise


def publish_generation(
    live: Path,
    files: Iterable[StagedFile],
    *,
    post_write_verify: Callable[[], None] | None = None,
    state_root: Path | None = None,
    repo_root: Path | None = None,
) -> None:
    """Publish a fresh generation of `live` via the R1 rename-swap contract.

    Args:
        live: The live output-root directory, e.g. `<repo_root>/.spaex`.
        files: Ordered iterable of `StagedFile` — writer discipline says
            `install.lock` last, the sole publication record, but the swap
            itself is agnostic to ordering.
        post_write_verify: Optional callback invoked after the swap completes;
            if it raises, the swap is rolled back and the exception re-raised.
        state_root: Device-local state root. When supplied, the identity
            record is refreshed for diagnostic purposes; callers still
            must have invoked
            `install.inflight.clean_stale_siblings(live)` under the
            exclusive lock before this call.
        repo_root: The repository root — used with `state_root` to derive the
            identity record. Defaults to `live.parent` when omitted.
    """
    files_list = list(files)
    parent = live.parent
    next_dir = _next_dir(live)
    prev_dir = _prev_dir(live)

    _rmtree(next_dir)
    next_dir.mkdir(parents=True, exist_ok=False)
    _fsync_dir(parent)

    live_existed_before = live.exists()
    rename_a_done = False

    try:
        _write_staging(next_dir, files_list)

        if state_root is not None:
            paths = transaction_paths(
                repo_root if repo_root is not None else parent,
                state_root,
            )
            write_identity_record(paths)

        _crash_after("pre_swap")
        if live_existed_before:
            # A previous crash after rename B may have left an old `.prev/`.
            # Staging and validation are complete now, so replace that stale
            # pre-image immediately before creating the new one. If we crash
            # before rename A, the live generation is still untouched.
            if prev_dir.exists():
                _rmtree(prev_dir)
                _fsync_dir(parent)
            os.rename(str(live), str(prev_dir))
            _fsync_dir(parent)
            rename_a_done = True
        _crash_after("rename_a")

        try:
            os.rename(str(next_dir), str(live))
        except BaseException:
            if rename_a_done:
                os.rename(str(prev_dir), str(live))
                _fsync_dir(parent)
                rename_a_done = False
                _rmtree(next_dir)
                _fsync_dir(parent)
            raise
        _fsync_dir(parent)
        _crash_after("rename_b")

        if post_write_verify is not None:
            try:
                post_write_verify()
            except BaseException:
                _rollback_swap(
                    live,
                    next_dir,
                    prev_dir,
                    live_existed_before=live_existed_before,
                )
                rename_a_done = False
                raise

        if prev_dir.exists():
            _rmtree(prev_dir)
            _fsync_dir(parent)
    except BaseException:
        # Pre-swap failure: staging is transient; if the swap did not run,
        # remove staging so a rerun starts clean. Post-swap failure branches
        # already ran rollback_swap; leave prev_dir alone in that case.
        if not rename_a_done and (
            not live.exists() or (next_dir.exists() and not prev_dir.exists())
        ):
            _rmtree(next_dir)
        raise
