"""Atomic single-file publication with cleanup on error (R6).

POSIX: write-to-same-directory tempfile via `mkstemp`, `fsync`, `os.replace`,
parent-directory `fsync`. Windows: use `MoveFileExW` with the
`MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH` flags plus
`FlushFileBuffers` on the source handle before the move.

Any exception during staging or replacement guarantees that the tempfile is
removed before we re-raise.
"""

from __future__ import annotations

import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"


def _fsync_parent_dir(path: Path) -> None:
    if _IS_WINDOWS:
        return
    fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_replace_posix(target: Path, data: bytes) -> None:
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(parent),
    )
    tmp = Path(tmp_path)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(target))
    except BaseException:
        with suppress(FileNotFoundError):
            tmp.unlink()
        raise
    _fsync_parent_dir(target)


def _write_replace_windows(target: Path, data: bytes) -> None:
    import ctypes
    from ctypes import wintypes

    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(parent),
    )
    tmp = Path(tmp_path)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            handle = ctypes.windll.msvcrt._get_osfhandle(fh.fileno())  # type: ignore[attr-defined]
            ctypes.windll.kernel32.FlushFileBuffers(wintypes.HANDLE(handle))
        MOVEFILE_REPLACE_EXISTING = 0x1
        MOVEFILE_WRITE_THROUGH = 0x8
        result = ctypes.windll.kernel32.MoveFileExW(
            ctypes.c_wchar_p(str(tmp)),
            ctypes.c_wchar_p(str(target)),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
        if not result:
            raise ctypes.WinError()
    except BaseException:
        with suppress(FileNotFoundError):
            tmp.unlink()
        raise


def write_replace(target: Path, data: bytes) -> None:
    """Publish `data` to `target` atomically."""
    if _IS_WINDOWS:
        _write_replace_windows(target, data)
    else:
        _write_replace_posix(target, data)
