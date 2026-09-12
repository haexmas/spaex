"""Exclusive install-transaction writer lock (Spec 008 T019, research §R4).

Combines an OS-level non-blocking advisory lock with an on-disk mutex file
that carries owner metadata (`install.mutex`, layout in data-model.md
§InstallMutexFile). One lock handle protects both concerns: the OS lock
enforces mutual exclusion, and the same locked handle is used for in-place
heartbeat updates so the pathname and inode remain stable while the lease
is held.

POSIX: `fcntl.flock(LOCK_EX | LOCK_NB)`.
Windows: `LockFileEx(LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY)`.

On contention, `ConstitutionWriterBusyError` is raised. The background
heartbeat thread + revalidation-before-reclaim protocol land in T034 on
top of the `heartbeat()` primitive this module exposes.
"""

from __future__ import annotations

import errno
import os
import sys
import time
from pathlib import Path
from types import TracebackType

from spaex.install.lock import OwnerToken
from spaex.io import json_deterministic
from spaex.util.errors import ConstitutionWriterBusyError

_IS_WINDOWS = sys.platform == "win32"
_ERROR_LOCK_VIOLATION = 33
# Windows byte-range locks are mandatory, unlike POSIX advisory locks. Keep the
# coordination byte beyond the payload so readers can inspect install.mutex
# while its owner still holds the exclusive lock.
_WINDOWS_LOCK_OFFSET = 0x7FFF_FFFF
_WINDOWS_LOCK_LENGTH = 1

HEARTBEAT_INTERVAL_NS = 5_000_000_000        # 5 seconds
TTL_NS = 60_000_000_000                      # 60 seconds
SAFETY_MARGIN_NS = 5_000_000_000             # 5 seconds


def _isoformat_ns(wallclock_ns: int) -> str:
    """Return an ISO 8601 UTC string for `time.time_ns()` nanoseconds."""
    seconds, ns_remainder = divmod(wallclock_ns, 1_000_000_000)
    micros = ns_remainder // 1000
    from datetime import datetime, timezone
    ts = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return f"{ts.strftime('%Y-%m-%dT%H:%M:%S')}.{micros:06d}Z"


def _mutex_payload(
    owner_token: OwnerToken,
    *,
    acquired_at_ns: int,
    heartbeat_at_ns: int,
) -> bytes:
    """Serialise the `install.mutex` JSON payload per data-model.md."""
    obj = {
        "owner_token": owner_token.serialize(),
        "acquired_at": _isoformat_ns(acquired_at_ns),
        "heartbeat_at": _isoformat_ns(heartbeat_at_ns),
        "heartbeat_at_ns_wallclock": heartbeat_at_ns,
        "heartbeat_interval_ns": HEARTBEAT_INTERVAL_NS,
        "ttl_ns": TTL_NS,
        "safety_margin_ns": SAFETY_MARGIN_NS,
    }
    return json_deterministic.dumps(obj)


class ConstitutionWriterLock:
    """Non-blocking exclusive writer lock with in-place owner metadata.

    Accepts an optional `OwnerToken`. When present, the lock file (`install.mutex`)
    is populated with the R4 owner-metadata JSON immediately after the OS
    lock is acquired; when absent, the existing pre-Spec-008 no-metadata
    behaviour is preserved so pre-T034 callsites keep working.

    `heartbeat()` updates `heartbeat_at` and `heartbeat_at_ns_wallclock`
    in place through the already-locked handle and fsyncs the result. The
    pathname and inode remain stable — the heartbeat MUST NOT be
    implemented via `os.replace()`.
    """

    def __init__(
        self,
        lock_path: Path,
        owner_token: OwnerToken | None = None,
    ) -> None:
        self._lock_path = lock_path
        self._owner_token = owner_token
        self._fd: int | None = None
        self._handle = None
        self._acquired_at_ns: int | None = None

    def __enter__(self) -> ConstitutionWriterLock:
        """Acquire the OS lock and publish owner metadata when requested."""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        if _IS_WINDOWS:
            self._acquire_windows()
        else:
            self._acquire_posix()
        if self._owner_token is not None:
            try:
                self._write_initial_payload()
            except BaseException:
                try:
                    if _IS_WINDOWS:
                        self._release_windows()
                    else:
                        self._release_posix()
                finally:
                    raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release the OS lock and close its underlying handle."""
        if _IS_WINDOWS:
            self._release_windows()
        else:
            self._release_posix()

    def heartbeat(self) -> None:
        """Update the heartbeat timestamps in place through the locked handle."""
        if self._owner_token is None:
            raise RuntimeError("heartbeat requires an OwnerToken at acquisition")
        now_ns = time.time_ns()
        payload = _mutex_payload(
            self._owner_token,
            acquired_at_ns=self._acquired_at_ns or now_ns,
            heartbeat_at_ns=now_ns,
        )
        self._rewrite_locked_bytes(payload)

    def _write_initial_payload(self) -> None:
        """Write the first owner-metadata snapshot through the locked handle."""
        now_ns = time.time_ns()
        self._acquired_at_ns = now_ns
        assert self._owner_token is not None
        payload = _mutex_payload(
            self._owner_token,
            acquired_at_ns=now_ns,
            heartbeat_at_ns=now_ns,
        )
        self._rewrite_locked_bytes(payload)

    def _rewrite_locked_bytes(self, payload: bytes) -> None:
        """Truncate + write the payload through the locked handle and fsync."""
        if _IS_WINDOWS:
            self._rewrite_windows(payload)
        else:
            self._rewrite_posix(payload)

    def _rewrite_posix(self, payload: bytes) -> None:
        """Replace the payload in place and flush it durably on POSIX."""
        assert self._fd is not None
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.ftruncate(self._fd, 0)
        remaining = memoryview(payload)
        while remaining:
            written = os.write(self._fd, remaining)
            remaining = remaining[written:]
        os.fsync(self._fd)

    def _rewrite_windows(self, payload: bytes) -> None:
        """Replace the payload in place and flush it durably on Windows."""
        import ctypes
        from ctypes import wintypes

        assert self._handle is not None
        kernel32 = ctypes.windll.kernel32
        FILE_BEGIN = 0
        if not kernel32.SetFilePointerEx(
            wintypes.HANDLE(self._handle),
            ctypes.c_longlong(0),
            None,
            wintypes.DWORD(FILE_BEGIN),
        ):
            raise ctypes.WinError()
        if not kernel32.SetEndOfFile(wintypes.HANDLE(self._handle)):
            raise ctypes.WinError()
        written = wintypes.DWORD(0)
        buf = (ctypes.c_char * len(payload)).from_buffer_copy(payload)
        if not kernel32.WriteFile(
            wintypes.HANDLE(self._handle),
            buf,
            wintypes.DWORD(len(payload)),
            ctypes.byref(written),
            None,
        ):
            raise ctypes.WinError()
        if not kernel32.FlushFileBuffers(wintypes.HANDLE(self._handle)):
            raise ctypes.WinError()

    def _acquire_posix(self) -> None:
        """Open the mutex and acquire a non-blocking POSIX advisory lock."""
        import fcntl

        fd = os.open(str(self._lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise ConstitutionWriterBusyError(
                    message="another `haex install` is running"
                ) from None
            raise
        self._fd = fd

    def _release_posix(self) -> None:
        """Release and close the POSIX mutex descriptor, if acquired."""
        import fcntl

        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def _acquire_windows(self) -> None:
        """Open the mutex and acquire its non-blocking Windows lock byte."""
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
        OPEN_ALWAYS = 4
        FILE_ATTRIBUTE_NORMAL = 0x80

        handle = kernel32.CreateFileW(
            ctypes.c_wchar_p(str(self._lock_path)),
            wintypes.DWORD(GENERIC_READ | GENERIC_WRITE),
            wintypes.DWORD(FILE_SHARE_READ | FILE_SHARE_WRITE),
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
        result = kernel32.LockFileEx(
            wintypes.HANDLE(handle),
            wintypes.DWORD(LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY),
            wintypes.DWORD(0),
            wintypes.DWORD(_WINDOWS_LOCK_LENGTH),
            wintypes.DWORD(0),
            ctypes.byref(overlapped),
        )
        if not result:
            last_error = ctypes_api.GetLastError()
            kernel32.CloseHandle(wintypes.HANDLE(handle))
            if last_error == _ERROR_LOCK_VIOLATION:
                raise ConstitutionWriterBusyError(
                    message="another `haex install` is running"
                )
            raise ctypes_api.WinError(last_error)
        self._handle = handle

    def _release_windows(self) -> None:
        """Close the Windows mutex handle, releasing its byte-range lock."""
        import ctypes
        from ctypes import wintypes
        from typing import Any, cast

        if self._handle is not None:
            ctypes_api = cast(Any, ctypes)
            kernel32 = ctypes_api.windll.kernel32
            kernel32.CloseHandle(wintypes.HANDLE(self._handle))
            self._handle = None
