# Spec 009 — Hook Boundary Contract

**Status**: Deferred, never specced (2026-09-21; no `specs/009-*` exists). The [Scope Realignment](2026-09-03-scope-realignment-design.md) (Decision 11) recalibrated the trust model, and hook execution shipped instead as [Spec 016](2026-09-08-spec-016-molecule-install-hooks-design.md) (subprocess hooks under the operator's own permissions, no sandbox), which deliberately does not depend on this contract. Kept as a reference for a hardening pass if a hostile-publisher scenario arises. Original status: Draft (extracted from [Spec 007 design doc](2026-08-28-spec-007-unified-manifest-design.md) 2026-08-29 to keep the Spec 007 doc focused on the manifest-v2 architecture)
**Author**: haex-hive constitution v1.3.0 process
**Related**: [Spec 007 — Unified Manifest & harness_sources v2 design](2026-08-28-spec-007-unified-manifest-design.md);
[Constitution §Principle I, VI](../../.specify/memory/constitution.md)

## Purpose

Spec 009 delivers `haex hook run <trigger>` — the sole consumer-side
execution surface for publisher-authored code — and is therefore
load-bearing for the operator's trust model. The requirements captured here
are non-negotiable for the Spec 009 landing. When Spec 009 is drafted via
`/speckit-specify`, this document is its authoritative source for the hook
boundary contract; Spec 009's plan/tasks reference this file rather than
restating.

## Hook-boundary requirements

`haex hook run` is the sole consumer-side execution surface for
publisher-authored code and is therefore load-bearing for the operator's
trust model:

- **Filesystem cwd + advisory allowlist**. The subprocess cwd is the consumer
  repo root. The dispatcher contract enumerates a hook's readable and writable
  paths; at minimum, dispatcher-mediated reads are limited to the consumer
  repo tree and `.haex-hive/generated/`, and dispatcher-mediated writes go to
  a per-invocation scratch directory. The dispatcher refuses requests through
  its own file APIs that fall outside this allowlist. Because hooks run under
  the consumer's user account and Spec 007 provides no OS-level sandbox,
  direct filesystem syscalls outside the allowlist cannot be technically
  prevented; this requirement MUST NOT claim kernel-enforced confinement.
- **Environment isolation**. The subprocess starts from an explicit
  allow-list of environment variables (`PATH`, `HOME`, `LANG`, plus a
  named `HAEX_HOOK_*` set); the caller's other environment does not
  leak in, and the hook cannot read the operator's shell state.
- **Process-group reaping**. On Windows, the dispatcher assigns the hook and
  all inherited descendants to a Job Object configured with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; timeout or failure closes the job,
  waits for termination, and reaps every process. On Linux, it uses a
  dedicated cgroup v2 subtree and kills the subtree, which also contains
  descendants that create new sessions. On other POSIX platforms, process
  groups alone are explicitly insufficient: the dispatcher MUST use an
  equivalent OS-level descendant container or refuse to run the hook until
  one is available. Tests MUST spawn a descendant that creates a new session
  and prove that timeout and failure terminate and reap it, with no stray
  process remaining.
- **No-follow reads of hook outputs**. The dispatcher establishes a handle to
  the permitted output root and resolves the declared relative path beneath
  that boundary, without following symlinks or reparse points in any parent
  component. On Linux this uses an `openat2`-style beneath/no-symlink resolve;
  POSIX fallbacks open and validate each component relative to a directory
  handle, and Windows uses a constrained directory handle with reparse-point
  rejection. It reads from the opened handle rather than reopening the path,
  verifies the handle's device+inode identity (or Windows volume serial/file
  ID) before and after reading, and rejects any identity change. Tests MUST
  replace a parent directory or output during a read and prove the result is
  rejected. This is the TOCTOU-closure rule.
- **Timeout contract**. Every trigger declares a max wall-clock
  duration; exceeding it marks the invocation as failed and cleans up through
  the platform containment object above: it closes the Windows Job Object,
  kills the Linux cgroup v2 subtree, or uses the required equivalent POSIX
  descendant container. The dispatcher then waits for termination and reaps
  every contained process. No hook can hang the dispatcher indefinitely.

## Runtime secret access

Blueprints that need runtime secrets (API tokens, passwords, private keys)
obtain them out-of-band via the OS keychain at hook-runtime. There is **no
structured secret surface anywhere in haex-hive**: no publisher-manifest
field for secret aliases, no consumer-config field for secret references,
no dispatcher wiring for populating secret environment variables from the
keychain. Secrets live entirely outside the manifest+config+lockfile chain.

The convention:

- **Publisher documents in prose**, in the atom's README/documentation,
  the exact, case-sensitive keychain `service` and `alias` pair for every
  required secret (for example, `service: haex-hive/graphify`,
  `alias: neo4j-password`). A bare alias is not sufficient: the publisher
  chooses and documents both strings, and a change to either is a hook
  compatibility change.
- **Operator sets those aliases up device-locally** using their OS-native
  keychain manager (Keychain Access on macOS, secret-service on Linux,
  Credential Manager on Windows) or a future `haex secret set <alias>`
  device-local subcommand. This setup is orthogonal to `haex install`
  and never touches committed content.
- **Hooks read secrets at runtime directly** through the Python `keyring`
  package, a non-stdlib hook-runtime dependency with an OS-native backend;
  the supported call is `keyring.get_password("<service>", "<alias>")` using
  exactly the documented pair. A hook environment without a usable `keyring`
  backend is unsupported and the hook fails closed. The dispatcher passes no
  secret-related state in the JSON context or the environment. A hook that
  cannot obtain its required secret fails within its own error handling; the
  dispatcher treats the outcome as a normal hook failure without
  secret-specific diagnostics.

Consequence for the hook boundary contract above: the `HAEX_HOOK_*`
environment allow-list does NOT include any `HAEX_HOOK_SECRET_*` variables.
Secrets never enter committed configuration, logs, command lines,
lockfiles, or hook context JSON by any haex-hive-managed mechanism.

## Non-Goals

- Kernel-enforced sandboxing (seccomp/AppArmor/gVisor). See Spec 007
  Non-Goals; this is intentionally out of scope for Spec 009.
- Cross-platform native containment beyond the process-group-reaping
  contract above. Docker-based isolation is not part of the hook boundary.
