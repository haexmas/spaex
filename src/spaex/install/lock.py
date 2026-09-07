"""Exclusive advisory lock and fenced-lease owner token (FR-001, FR-010).

This module currently provides the `OwnerToken` value object per Spec 008
research §R4 and the owner-token v1 contract under
`specs/008-install-transaction/contracts/owner-token.v1.md`. The fenced-
lease heartbeat thread, OS-level lock acquisition, and reclaim protocol
land in T034 (US2) on top of this shape.
"""

from __future__ import annotations

import os
import re
import socket
import time
import uuid
from dataclasses import dataclass

_HOSTNAME_RE = re.compile(r"[A-Za-z0-9.-]+")
_HOSTNAME_SHAPE_RE = re.compile(r"\A[A-Za-z0-9.-]{1,64}\Z")
_UUID4_HEX_RE = re.compile(r"\A[0-9a-f]{32}\Z")
_MAX_TOKEN_BYTES = 128


@dataclass(frozen=True)
class OwnerToken:
    """Runtime shape of the fenced-lease owner token.

    Serialised form is `<pid>:<hostname>:<start_ns>:<uuid4_hex>`, ASCII-safe,
    at most 128 bytes. Hostnames outside `[A-Za-z0-9.-]{1,64}` are refused;
    call `OwnerToken.emit(...)` to construct one from raw system values and
    have the sanitisation applied consistently.
    """

    pid: int
    hostname: str
    start_ns: int
    uuid4_hex: str

    def __post_init__(self) -> None:
        if self.pid < 1 or self.pid > 0xFFFFFFFF:
            raise ValueError(f"pid out of range: {self.pid}")
        if not _HOSTNAME_SHAPE_RE.match(self.hostname):
            raise ValueError(f"hostname does not match [A-Za-z0-9.-]{{1,64}}: {self.hostname!r}")
        if self.start_ns < 0:
            raise ValueError(f"start_ns must be non-negative: {self.start_ns}")
        if not _UUID4_HEX_RE.match(self.uuid4_hex):
            raise ValueError(f"uuid4_hex must be 32 lowercase hex chars: {self.uuid4_hex!r}")

    def serialize(self) -> str:
        token = f"{self.pid}:{self.hostname}:{self.start_ns}:{self.uuid4_hex}"
        if len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
            raise ValueError(f"serialised token exceeds {_MAX_TOKEN_BYTES} bytes: {len(token)}")
        return token

    @classmethod
    def parse(cls, raw: str) -> OwnerToken:
        if len(raw.encode("utf-8")) > _MAX_TOKEN_BYTES:
            raise ValueError(f"token exceeds {_MAX_TOKEN_BYTES} bytes")
        parts = raw.split(":")
        if len(parts) != 4:
            raise ValueError(f"expected 4 colon-separated fields, got {len(parts)}")
        pid_str, hostname, start_ns_str, uuid4_hex = parts
        try:
            pid = int(pid_str)
            start_ns = int(start_ns_str)
        except ValueError as exc:
            raise ValueError(f"pid and start_ns must be decimal integers: {exc}") from None
        return cls(pid=pid, hostname=hostname, start_ns=start_ns, uuid4_hex=uuid4_hex)

    @classmethod
    def emit(
        cls,
        *,
        pid: int | None = None,
        hostname: str | None = None,
        start_ns: int | None = None,
    ) -> OwnerToken:
        """Build a fresh token from live system values or explicit overrides.

        Overrides exist for tests; production callers pass nothing and pick up
        `os.getpid()`, `socket.gethostname()`, `time.monotonic_ns()`, and a
        fresh UUID4. Hostnames are sanitised per contract: non-matching chars
        are dropped, the result truncated to 64 chars, and an empty result
        falls back to the literal `"unknown"`.
        """
        actual_pid = os.getpid() if pid is None else pid
        raw_hostname = socket.gethostname() if hostname is None else hostname
        actual_start_ns = time.monotonic_ns() if start_ns is None else start_ns
        sanitised = "".join(_HOSTNAME_RE.findall(raw_hostname))[:64] or "unknown"
        return cls(
            pid=actual_pid,
            hostname=sanitised,
            start_ns=actual_start_ns,
            uuid4_hex=uuid.uuid4().hex,
        )
