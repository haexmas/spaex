# Spec 008 — Install Transaction Contract

**Status**: Implemented as [Spec 008](../../specs/008-install-transaction/) (`spaex install` publishes generations transactionally), with gaps: in its `tasks.md` 38 checkboxes are ticked and 17 are open, some of which the spec marks as retired or deferred by the trust-git amendment (2026-09-01). Original status: Draft (extracted from [Spec 007 design doc](2026-08-28-spec-007-unified-manifest-design.md) 2026-08-29 to keep the Spec 007 doc focused on the manifest-v2 architecture)
**Author**: haex-hive constitution v1.3.0 process
**Related**: [Spec 007 — Unified Manifest & harness_sources v2 design](2026-08-28-spec-007-unified-manifest-design.md);
[Constitution §Principle IV, VI](../../.specify/memory/constitution.md)

## Purpose

Spec 008 delivers `haex install` end-to-end. The requirements captured here
are load-bearing for correctness under concurrency and interruption and are
non-negotiable for the Spec 008 landing. When Spec 008 is drafted via
`/speckit-specify`, this document is its authoritative source for the
transaction contract; Spec 008's plan/tasks reference this file rather than
restating.

**2026-09-01 trust-git amendment**: Git's immutable revisions and committed
tree content pin the inputs to the generated `.haex-hive/` view, but they do not
make a rerun of an arbitrary generator deterministic. Every generated payload
byte MUST therefore be a pure function of pinned input bytes, the pinned
adapter/tool configuration, and canonical serialization; timestamps, random
values, environment state, locale, and filesystem enumeration order MUST NOT
enter generated payloads. A confirmed multi-source LLM result is an input
artifact, not an install-time inference: `haex install` consumes the reviewed,
committed result and MUST NOT invoke the LLM again. Transaction metadata such
as `generation_id` and `written_at` may vary only when a substantive
publication occurs. The per-root/per-file digest, journal, snapshot, and
persisted mixed-root ownership requirements from the original draft are
retired. Spec 008 keeps the rename-swap transaction, generation compatibility,
root availability checks, and exclusive-lock discipline. Mixed-root ownership
details are deferred to Spec 010.

## Install-transaction requirements

The following rules are load-bearing for correctness under concurrency and
interruption and are non-negotiable for the Spec 008 landing:

- **Repository lock ordering**. Acquire an exclusive advisory lock at the
  device-local `$HAEX_HIVE_STATE/locks/<repo-key>/install.mutex` (or per-OS
  equivalent) **before** reading
  `.haex-hive.json`, cloning, resolving, or building the install plan. Hold
  it through recovery, staging, commit, rollback, and cleanup. Concurrent
  invocations wait or fail with the lock owner's PID, hostname, and start
  time. Ordinary `haex verify` acquires a shared/read lock so a concurrent
  install cannot present it a torn view. `haex verify --recover` is a
  modifying operation: it MUST acquire the same exclusive lock as `haex
  install` before inspecting in-flight state, and it MUST NOT first take a
  shared lock and upgrade it before recovering or changing any output root.
- **Directory-name startup recovery**. For each haex-owned output root, the
  presence or absence of `<root>/`, `<root>.next/`, and `<root>.prev/` is the
  complete durable in-flight state. The next `haex install` (or `haex
  verify --recover`) resolves that state before building new output. Recovery
  completes forward, restores the previous generation, or refuses according to
  the state table in research §R7. Every rename between those names fsyncs the
  parent directory. A generation is usable only when its metadata is
  schema-compatible and all named roots and active overlay pointers are
  available for the same `generation_id`.
- **Repository-wide visibility commit**. All new bytes are written to a
  staging root next to the target (same filesystem), fsynced, and prepared as
  complete logical output-root views for `.haex-hive/`, `.claude/`, and
  `.codex/`. `.haex-hive/` is haex-owned and uses a same-filesystem directory
  rename-swap. `.claude/` and
  `.codex/` are mixed-ownership roots and MUST NEVER be exchanged or renamed as
  directories. Their adapter-owned leaves are instead stored under a versioned
  generation directory and published through a stable per-adapter overlay and
  current-generation pointer (for example, a supported symlink/junction or
  adapter-managed launcher). The overlay changes only paths declared by the
  adapter as owned; it never enumerates, copies, or replaces sibling entries in
  the mixed-ownership root. A platform without an atomic pointer or stable
  overlay mechanism MUST refuse the install rather than publish a torn direct
  view. After every other staged output is sealed, the transaction writes and
  fsyncs the final staged `install.lock`, then writes the staged
  `.haex-hive/visibility.json` marker last. The marker contains a unique,
  time-based generation ID and the names of every participating output root.
  Readers MUST NOT treat individual root replacements or adapter pointer
  replacements as publication. The final rename that makes the staged
  `.haex-hive/` directory live is the sole publication event and publishes the
  generation. Cleanup may follow but cannot change the marker or generation.
  Readers first load the marker and then require every named root and active
  overlay pointer to be available for the marker's `generation_id`; a missing
  marker, incomplete root set, or generation mismatch is an unavailable
  installation, never a partially valid one. Recovery tests MUST cover a crash
  after each root publication step and a
  reinstall with non-empty output roots, including an unowned `.claude/` or
  `.codex/` file modified during staging that survives unchanged, proving that
  recovery either restores the previous marker-consistent generation or
  completes the new one before readers resume.
- **Stable staged-input reads through commit**. The exclusive install lock is
  trusted to prevent supported haex writers from mutating `.haex-hive.json` or
  publisher/atom inputs during an install. All supported haex input writers
  MUST use the same exclusive install lock; a coordinated mutation attempt is
  therefore refused or waits until the transaction releases its fence. An
  out-of-band writer that ignores the lock is outside Spec 008's trusted-writer
  threat model.
- **Every side effect through the transaction**. The following outputs
  MUST be produced through the same staging-root transaction:
  `.haex-hive/constitution.md` (Spec 007 D2), `.haex-hive/config/<atom-id>.json`
  (Spec 007 D7), every file under `.haex-hive/generated/`, and any device-local
  agent-facing copy under `.claude/`, `.codex/`, etc. that Spec 010's
  adapters emit. `install.lock` is written last, after every other output
  in the transaction has been sealed (including any deferred publisher-hook
  outputs — see Spec 007's Non-Goals "Publisher install-time outputs" clause).
- **Delete-orphans in-transaction**. The complete staged directory for a
  haex-owned root is materialised from the current resolved output set. Files
  owned by removed resources are omitted from `<root>.next/` and disappear
  atomically when the staged directory replaces the live root. The retained
  `<root>.prev/` directory supplies whole-generation rollback; no per-path
  ownership record, content-integrity field, or rollback log is defined by
  Spec 008. Mixed-root ownership and deletion rules are deferred to Spec 010;
  unowned mixed-root entries remain outside the adapter overlay.
- **`install.lock` computed last**. The lockfile records the resolved atom set,
  immutable `generation_inputs` identities, `participating_roots`, and its
  `visibility_marker.generation_id` cross-reference over the final staged
  outputs. It has no per-file or per-root content-integrity fields and no
  persisted mixed-root ownership inventory. The generation-input identities
  are validated against the adapter/tool configuration actually used.
  Its own fsync precedes construction of `visibility.json`; the final atomic
  directory rename is the sole publication step. Any output that could still
  mutate (native-tool outputs when they return — see Spec 007's Non-Goals
  clarifier) is sealed before `install.lock` is computed.

- **Mixed-root pointer recovery**. Before the new
  `.haex-hive/visibility.json` is published, every adapter pointer transition
  MUST be atomic and retain a recoverable reference to its prior generation.
  Recovery MUST compare every active pointer with the still-live marker:
  pointers naming the candidate generation are restored to the prior
  generation, while pointers naming the prior generation are retained. A
  pointer naming neither generation, or a missing prior marker needed for
  classification, MUST cause refusal without cleanup or publication. After the
  marker is published, it is authoritative: matching candidate pointers are
  retained and obsolete generations are cleaned only after all pointers match
  it. This ordering makes an interrupted mixed-root exchange unavailable
  rather than readable as a mixed generation.

## Conformance suite

Spec 008's conformance suite MUST cover:

- Concurrent `haex install` invocations (one wins, the other waits or fails
  with owner detail)
- Crash recovery from every `<root>{,.next,.prev}` state
- A coordinated `.haex-hive.json` mutation attempt while the install lock is
  held (blocked by the lock)
- Rollback of a partially-applied delete-orphans plan

## `install.mutex` placement

The resolved placement is the device-local state root:
`$HAEX_HIVE_STATE/locks/<repo-key>/`, alongside the content store, keeping
`.haex-hive/` fully committed content. `<repo-key>` is the lowercase
hexadecimal SHA-256 of the canonical Spec-007 repo identity. The full identity
is stored separately in `repo-identity.v1.json` for diagnostics and collision
detection; the key contains neither the identity nor a path verbatim.

The fenced-lease contract is fixed: owner token
`<pid>:<hostname>:<start_ns>:<uuid4_hex>`, 5-second heartbeat, 60-second TTL,
5-second safety margin, reboot-safe `heartbeat_at_ns_wallclock` expiry values,
the same non-blocking exclusive OS lock for recovery, unchanged-token
revalidation, and in-place fencing before resolving in-flight state or
performing recovery/rename operations.
No in-repository transaction lock or journal is used. In-flight transaction
state lives in same-filesystem sibling directories beside each participating
output root; all lock state remains device-local.
