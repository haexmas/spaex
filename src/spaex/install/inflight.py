"""Stale-sibling cleanup before install (Spec 008, simplified §R7).

The 2026-09-02 detect+retry simplification retired the 8-state recovery
dispatcher. Under the current contract the rename-swap primitive gives
readers atomic visibility for free (they see either the pre-install
generation, no live directory, or the post-install generation — never a
mixed state), and `haex install` is deterministic and idempotent, so a
crashed install converges to a valid generation on the next invocation.

The only durable state we now inspect is: are there leftover
`<root>.next/` or `<root>.prev/` siblings from a prior crashed install?
Under the exclusive install lock, stale `.next/` is discarded. If the
live root is absent, the retained `.prev/` is restored before the regular
pipeline reads inputs or resolves contributions. This makes the prior
generation available while a retry may fail and matches the pip/npm
"detect + retry" model without a journal-style recovery-forward design.
"""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import suppress
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"


def clean_stale_siblings(
    live: Path, *, remove_prev: bool = False
) -> tuple[bool, bool]:
    """Remove a stale `<live>.next/` while retaining `<live>.prev/`.

    Returns `(next_removed, prev_present)` so callers may log whether a prior
    invocation crashed mid-transaction. The previous generation is retained
    until the replacement has passed staging and post-write validation. Set
    `remove_prev` only after the live generation has been validated as the
    replacement. Safe to call unconditionally under the exclusive install
    lock; a no-op when neither sibling exists.
    """
    next_dir = live.with_name(f"{live.name}.next")
    prev_dir = live.with_name(f"{live.name}.prev")

    next_removed = next_dir.exists()
    prev_present = prev_dir.exists()
    prev_removed = remove_prev and prev_present

    if next_removed:
        _rmtree(next_dir)
    if prev_removed:
        _rmtree(prev_dir)
    if next_removed or prev_removed:
        _fsync_dir(live.parent)

    return next_removed, prev_present


def restore_previous_generation(live: Path) -> bool:
    """Restore `<live>.prev/` when a mid-swap crash left `live` absent.

    The restore happens before a retry reads inputs or resolves contributions,
    so a failed retry leaves the last published generation available. The
    rename is same-filesystem and is followed by a parent-directory fsync.
    Returns ``True`` when a previous generation was restored.
    """
    prev_dir = live.with_name(f"{live.name}.prev")
    if live.exists() or not prev_dir.exists():
        return False
    os.rename(str(prev_dir), str(live))
    _fsync_dir(live.parent)
    return True


def _rmtree(path: Path) -> None:
    with suppress(FileNotFoundError):
        shutil.rmtree(str(path))


def _fsync_dir(path: Path) -> None:
    if _IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        flush_buffers = kernel32.FlushFileBuffers
        flush_buffers.argtypes = [wintypes.HANDLE]
        flush_buffers.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        handle = create_file(
            str(path),
            0xC0000000,  # GENERIC_READ | GENERIC_WRITE
            0x00000001 | 0x00000002 | 0x00000004,  # share read/write/delete
            None,
            3,  # OPEN_EXISTING
            0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS (directory handle)
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not flush_buffers(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            close_handle(handle)
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
