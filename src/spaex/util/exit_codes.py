"""Canonical exit codes for every `haex` command.

Codes are unified across `haex migrate`, `haex install`, and
`haex constitution show` so a caller never has to disambiguate divergent values
for the same numeric result.
"""

from __future__ import annotations

SUCCESS = 0

# 2 — resolution / input refuse (migrate: v1 shape not migratable; assemble:
# zero constitution sources or an unresolvable manifest; show: constitution
# file missing).
INPUT_REFUSE = 2

# 3 — I/O refuse (missing publisher clone, unavailable pinned revision,
# missing contribution file, missing install.lock for show).
IO_REFUSE = 3

# 4 — validation refuse (post-migration schema failure, corrupt install.lock
# in show).
VALIDATION_REFUSE = 4

# 5 — system refuse (missing `.spaex.json` or version mismatch).
SYSTEM_REFUSE = 5

# 6 — post-write validation failure (content integrity mismatch).
POST_WRITE_VALIDATION = 6

# 7 — an assembly transaction journal is present; the paired output is
# indeterminate until recovery.
INCOMPLETE_TRANSACTION = 7

# 8 — Principle VIII concealment-instruction refuse.
CONSTITUTION_CONCEALMENT = 8

# 9 — another `haex install` (writer lock)
# (install lock) owns the exclusive lock. Both surfaces share the code so
# callers do not have to disambiguate; the diagnostic distinguishes them.
WRITER_BUSY = 9
INSTALL_LOCK_BUSY = WRITER_BUSY

# 10 — plaintext secret detected in a source, candidate, pending payload,
# or lock payload.
PLAINTEXT_SECRET = 10

# 13 — terminal-unsafe contribution encountered on the stdio path.
TERMINAL_UNSAFE_CONTRIBUTION = 13

# 64 — usage error (mutually exclusive flags supplied together).
USAGE = 64
