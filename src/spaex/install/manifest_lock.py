"""Permanent advisory manifest lock (`.spaex/manifest.json.lock`).

Bounded-wait exclusive file lock serialising `haex add`, `haex remove`, and
`spaex` reads/writes of `.spaex/manifest.json`. Modeled on
`io/writer_lock.py` (Spec 008) but polls until a deadline instead of failing
immediately, per FR-028.

The lock file itself is created once and NEVER renamed or deleted by the
tool. Its byte content is irrelevant; only the OS advisory lock on the
descriptor matters. Kernel-level release on process exit is the sole
automatic recovery path — the tool never force-breaks a lock held by a
living process.

Nested acquisition in the same process reuses the held descriptor via a
per-instance reference count so higher-level flows (e.g. `haex add`
delegating to `haex install`) can pass the context down without a re-lock.
"""

from __future__ import annotations

import argparse
import errno
import math
import os
import sys
import time
from pathlib import Path
from types import TracebackType

from spaex.paths import (
    MANIFEST_LOCK_FILENAME,
    manifest_lock_path,
)
from spaex.util.errors import ManifestLockContendedError

_IS_WINDOWS = sys.platform == "win32"
_ERROR_LOCK_VIOLATION = 33
_WINDOWS_LOCK_OFFSET = 0x7FFF_FFFF
_WINDOWS_LOCK_LENGTH = 1
_POLL_INTERVAL_SECONDS = 0.05

DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0


def parse_lock_timeout(raw: str) -> float:
    """Parse a finite, non-negative manifest-lock timeout for argparse."""
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("lock timeout must be a number") from exc
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(
            "lock timeout must be a finite number greater than or equal to zero"
        )
    return value

def active_manifest_lock_path(repo_root: Path) -> Path:
    """Return the canonical lock, including an in-flight recovery tree."""
    canonical = manifest_lock_path(repo_root)
    if canonical.exists():
        return canonical
    recovery = repo_root / ".spaex.prev" / MANIFEST_LOCK_FILENAME
    if recovery.exists():
        return recovery
    return canonical


class ManifestLockContext:
    """Bounded-wait exclusive advisory lock on the active manifest lock."""

    def __init__(
        self,
        lock_path: Path,
        timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self._lock_path = lock_path
        self._timeout_seconds = timeout_seconds
        self._fd: int | None = None
        self._handle: int | None = None
        self._depth = 0

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    def __enter__(self) -> ManifestLockContext:
        if self._depth > 0:
            self._depth += 1
            return self
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(self._timeout_seconds, 0.0)
        if _IS_WINDOWS:
            self._acquire_windows(deadline)
        else:
            self._acquire_posix(deadline)
        self._depth = 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._depth > 1:
            self._depth -= 1
            return
        try:
            if _IS_WINDOWS:
                self._release_windows()
            else:
                self._release_posix()
        finally:
            self._depth = 0

    def _acquire_posix(self, deadline: float) -> None:
        import fcntl
        from typing import Any, cast

        fcntl_api = cast(Any, fcntl)

        fd = os.open(str(self._lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            while True:
                try:
                    fcntl_api.flock(fd, fcntl_api.LOCK_EX | fcntl_api.LOCK_NB)
                    self._fd = fd
                    return
                except OSError as e:
                    if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                        raise
                    if time.monotonic() >= deadline:
                        raise ManifestLockContendedError(
                            message=(
                                "manifest lock at "
                                f"{self._lock_path} is held by another process"
                            ),
                            context={
                                "lock_path": str(self._lock_path),
                                "timeout_seconds": f"{self._timeout_seconds:g}",
                            },
                        ) from None
                    time.sleep(_POLL_INTERVAL_SECONDS)
        except BaseException:
            os.close(fd)
            raise

    def _release_posix(self) -> None:
        import fcntl
        from typing import Any, cast

        fcntl_api = cast(Any, fcntl)

        if self._fd is not None:
            try:
                fcntl_api.flock(self._fd, fcntl_api.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def _acquire_windows(self, deadline: float) -> None:
        import ctypes
        from ctypes import wintypes
        from typing import Any, cast

        ctypes_api = cast(Any, ctypes)
        kernel32 = ctypes_api.windll.kernel32
        kernel32.CreateFileW.restype = wintypes.HANDLE
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x1
        FILE_SHARE_WRITE = 0x2
        FILE_SHARE_DELETE = 0x4
        OPEN_ALWAYS = 4
        FILE_ATTRIBUTE_NORMAL = 0x80

        handle = kernel32.CreateFileW(
            ctypes.c_wchar_p(str(self._lock_path)),
            wintypes.DWORD(GENERIC_READ | GENERIC_WRITE),
            # The lock file lives inside the `.spaex/` directory, which is
            # atomically renamed while this handle remains open. Delete
            # sharing permits that directory swap without releasing the
            # advisory lock on Windows.
            wintypes.DWORD(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE),
            None,
            wintypes.DWORD(OPEN_ALWAYS),
            wintypes.DWORD(FILE_ATTRIBUTE_NORMAL),
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes_api.WinError()

        LOCKFILE_EXCLUSIVE_LOCK = 0x2
        LOCKFILE_FAIL_IMMEDIATELY = 0x1

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [
                ("Internal", ctypes.c_void_p),
                ("InternalHigh", ctypes.c_void_p),
                ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE),
            ]

        overlapped = OVERLAPPED()
        overlapped.Offset = _WINDOWS_LOCK_OFFSET
        overlapped.OffsetHigh = 0
        try:
            while True:
                result = kernel32.LockFileEx(
                    wintypes.HANDLE(handle),
                    wintypes.DWORD(LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY),
                    wintypes.DWORD(0),
                    wintypes.DWORD(_WINDOWS_LOCK_LENGTH),
                    wintypes.DWORD(0),
                    ctypes.byref(overlapped),
                )
                if result:
                    self._handle = handle
                    return
                last_error = ctypes_api.GetLastError()
                if last_error != _ERROR_LOCK_VIOLATION:
                    raise ctypes_api.WinError(last_error)
                if time.monotonic() >= deadline:
                    raise ManifestLockContendedError(
                        message=(
                            "manifest lock at "
                            f"{self._lock_path} is held by another process"
                        ),
                        context={
                            "lock_path": str(self._lock_path),
                            "timeout_seconds": f"{self._timeout_seconds:g}",
                        },
                    )
                time.sleep(_POLL_INTERVAL_SECONDS)
        except BaseException:
            kernel32.CloseHandle(wintypes.HANDLE(handle))
            raise

    def _release_windows(self) -> None:
        import ctypes
        from ctypes import wintypes
        from typing import Any, cast

        if self._handle is not None:
            ctypes_api = cast(Any, ctypes)
            kernel32 = ctypes_api.windll.kernel32
            kernel32.CloseHandle(wintypes.HANDLE(self._handle))
            self._handle = None
