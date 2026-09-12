"""Canonical exit codes for every `spaex` command.

Codes are shared across `spaex install` and `spaex constitution show` so a caller
never has to disambiguate divergent values for the same numeric result.
"""

from __future__ import annotations

SUCCESS = 0

# 2 — resolution / input refuse (zero constitution sources or an unresolvable
# manifest; show: constitution file missing).
INPUT_REFUSE = 2

# 3 — I/O refuse (missing publisher clone, unavailable pinned revision,
# missing contribution file, missing install.lock for show).
IO_REFUSE = 3

# 4 — validation refuse (corrupt install.lock in show).
VALIDATION_REFUSE = 4

# 5 — system refuse (missing `.spaex/manifest.json` or version mismatch).
SYSTEM_REFUSE = 5

# 6 — post-write validation failure (content integrity mismatch).
POST_WRITE_VALIDATION = 6

# 7 — an assembly transaction journal is present; the paired output is
# indeterminate until recovery.
INCOMPLETE_TRANSACTION = 7

# 8 — Principle VIII concealment-instruction refuse.
CONSTITUTION_CONCEALMENT = 8

# 9 — another `spaex install` (writer lock)
# (install lock) owns the exclusive lock. Both surfaces share the code so
# callers do not have to disambiguate; the diagnostic distinguishes them.
WRITER_BUSY = 9
INSTALL_LOCK_BUSY = WRITER_BUSY

# 10 — plaintext secret detected in a source, candidate, pending payload,
# or lock payload.
PLAINTEXT_SECRET = 10

# 13 — terminal-unsafe contribution encountered on the stdio path.
TERMINAL_UNSAFE_CONTRIBUTION = 13

# 20 — Spec 023 mechanical pre-check refuse (intra-molecule id-collision Case A;
# duplicate-id-body-mismatch under matching modality). Diagnostic names every
# offending fragment path and its producer molecule.
BEHAVIOR_PRECHECK_REFUSE = 20

# 21 — Spec 023 Composer refuse (cross-molecule semantic contradiction Case B
# that the operator declined to reconcile).
BEHAVIOR_SEMANTIC_REFUSE = 21

# 22 — Spec 023 project-local additive-only refuse (FR-020): a
# `_project/<fragment-id>` was declared whose bare fragment_id matches an
# atom-provided fragment id in any pinned molecule.
BEHAVIOR_PROJECT_LOCAL_REFUSE = 22

# 30-34 — Spec 023 Composer failure surface (research.md §8, fail-fast per
# FR-012a; no silent degradation to raw concatenation).
BEHAVIOR_COMPOSER_TIMEOUT = 30
BEHAVIOR_COMPOSER_RUNTIME_ERROR = 31
BEHAVIOR_COMPOSER_INVALID_OUTPUT = 32
BEHAVIOR_COMPOSER_QUOTA = 33
BEHAVIOR_COMPOSER_NO_RUNTIME = 34

# 64 — usage error (mutually exclusive flags supplied together).
USAGE = 64
