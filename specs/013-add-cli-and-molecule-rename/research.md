# Phase 0 Research: v3 Vocabulary and `haex add` / `haex remove` CLI

**Feature**: Spec 013
**Phase**: 0 (Outline & Research)
**Purpose**: Resolve every question that would otherwise be a `NEEDS CLARIFICATION` in the plan by naming the chosen approach, the rationale, and the alternatives that were considered and rejected.

The spec left no `NEEDS CLARIFICATION` markers, so the entries below are the load-bearing implementation decisions the plan depends on rather than open-ended investigations. Each decision has already been referenced by the plan's Technical Context; this file captures the reasoning.

---

## D1: Retirement path for v2 schemas

**Decision**: v2 schema files under `src/haex_hive/schema/data/` are deleted in the same commit that introduces the v3 equivalents. The tool ships v3-only from this feature onward.

**Rationale**: The spec (Assumption "Pre-user policy") and the operator's 2026-09-04 decision explicitly forbid a dual-vocabulary tolerance layer. haex-hive has no external adopters as of 2026-09-04; a hard v2 refuse at load time (FR-004) plus a `haex migrate` hint is clearer than mixed-vocabulary tolerance. Keeping both schemas in `schema/data/` would create a "which one wins?" ambiguity that Principle IV's determinism guidance forbids.

**Alternatives considered**:
- **Keep v2 schemas as read-only fallback**. Rejected: the schema loader dispatch complexity is not free, and every future contributor would have to reason about which version applies where. Pre-user policy makes this speculative flexibility.
- **Rename v2 files to `.deprecated` and leave in the tree**. Rejected: identical to above with more filesystem noise.

---

## D2: Manifest lock (`.haex-hive.json.lock`) cross-platform strategy

**Decision**: The permanent advisory manifest lock at repository root uses the same pattern as Spec 008's `writer_lock.py`: `fcntl.flock` on POSIX (Linux, macOS, WSL2) and Win32 `LockFileEx`/`UnlockFileEx` on Windows via `ctypes`. The lock file is created once with `O_CREAT|O_EXCL` semantics if absent; existing files are opened without truncation. The lock is advisory (an unauthenticated process could race), consistent with the tool's threat model, and is never renamed or deleted by the tool.

**Rationale**: Reusing Spec 008's abstraction avoids parallel implementations. `fcntl.flock` is per-file-descriptor and advisory, which matches the "wait or refuse on contention" behavior FR-026 requires. Win32 `LockFileEx` with `LOCKFILE_EXCLUSIVE_LOCK` provides the same semantics.

**Alternatives considered**:
- **`filelock` third-party package**. Rejected: introduces a new dependency for what stdlib already provides, and Spec 008 already ships the primitive.
- **Directory-based lock via `os.mkdir`**. Rejected: not automatically released on process crash without extra bookkeeping; the OS-level flock/LockFileEx is released by the kernel when the process dies.
- **Lockfile at `$HAEX_HIVE_STATE/locks/<repo-key>/manifest.lock` rather than at repo root**. Rejected for the manifest lock specifically: co-locating with `.haex-hive.json` makes the coupling visible and makes the lock's lifetime match the manifest's (both live in the repo). The install mutex at `$HAEX_HIVE_STATE/...` remains where Spec 008 put it; the two locks are independent (FR-026 acquisition order: manifest lock first, then install mutex).

---

## D3: Publisher-manifest fetch approach during `haex add`

**Decision**: `haex add` runs `git ls-remote <source-url> HEAD` (or the given ref) to resolve a full SHA. If a publisher clone already exists under `$HAEX_HIVE_STATE/repos/<clone-hash>/`, `haex add` runs `git fetch origin <sha> --depth 1` into that existing bare/mirror clone so the resolved SHA is guaranteed to be reachable locally. If no publisher clone exists yet, `haex add` initializes a temporary bare repository under `tempfile.TemporaryDirectory()`, runs `git remote add origin <source-url>` and `git fetch origin <sha> --depth 1`, then either promotes the fetched objects into a fresh `$HAEX_HIVE_STATE/repos/<clone-hash>/` (to warm the cache for the subsequent `haex install`) or reads `manifest.json` from the temp checkout via `git show FETCH_HEAD:manifest.json` and deletes the temp. In either path, the publisher-root `manifest.json` is validated against `publisher-manifest.v3.schema.json` before the consumer manifest is written.

**Rationale**: `git fetch origin <sha> --depth 1` explicitly requests the resolved SHA as a fetch target and works on the git 2.30+ baseline the project already documents. It handles authentication, protocol negotiation, and shallow object plumbing without the tool re-implementing them. Fetching by SHA (as opposed to `git clone --depth 1 <url>` which only fetches the default branch's tip) guarantees that an arbitrary historical or non-default revision the operator pinned via `--revision=<SHA>` is available in the local object graph before the manifest read. Reusing an existing publisher clone avoids a redundant network round-trip and warms the cache that `haex install` will consult immediately after.

**Alternatives considered**:
- **`git clone --depth 1 --revision <sha>`**. Rejected: `git clone --revision` was introduced in git 2.49; the project's documented baseline is git 2.30+. Using this flag would exclude satellites on 2.30–2.48 without a clear operator-facing gain.
- **`git clone --depth 1 <source-url>`** (without `--revision`). Rejected: only fetches the tip of the default branch; a historical SHA supplied via `--revision=<SHA>` would not be reachable in the resulting clone, and the manifest read would either fail or (worse) read the wrong revision's `manifest.json`. This is the failure mode CodeRabbit flagged on the initial draft.
- **`git sparse-checkout` of just `manifest.json`**. Rejected for the MVP: works but adds fetch-shape complexity and only saves a fraction of the object graph on small publisher repos. Considered as a follow-up if `haex add` latency becomes a real complaint.
- **HTTP fetch of the raw manifest from GitHub/GitLab**. Rejected: couples the tool to specific forge APIs, breaks for self-hosted git, and skips the git-object integrity check that a real clone provides.
- **Prompt the operator for the publisher manifest content directly**. Rejected: defeats the "one-line adoption" goal of the whole spec.

**Test coverage requirement**: the integration test for `haex add` MUST include at least one case where `--revision=<SHA>` points at a non-`HEAD` commit of a fixture publisher repo, so the fetch path is exercised against the exact regression this decision guards against.

---

## D4: Migration proposal placement

**Decision**: Local consumer and molecule manifest proposals live as sibling `.migrated` files: `.haex-hive.json.migrated`, `<molecule-dir>/manifest.json.migrated`, and (for a local publisher-root manifest) `manifest.json.migrated`. Proposals for a publisher manifest read from an immutable remote revision live under `$HAEX_HIVE_STATE/migrations/<source-digest>/<revision>/<repo-relative-path>.migrated`, matching the digest hash that `clone_dir()` already uses for `$HAEX_HIVE_STATE/repos/<clone-hash>/`.

**Rationale**: Principle VI v1.3.0 requires (a) a `.migrated` sidecar rather than in-place rewrite, (b) a printable diff, (c) determinism, and (d) `--dry-run`/`--check`. The design preview settled the placement rule; this decision records the concrete filenames. The remote-publisher case uses `$HAEX_HIVE_STATE` because the remote git object is immutable and never modified by the tool, but the operator still needs a materialized proposal to review before copying it into a publisher checkout and opening a PR.

**Alternatives considered**:
- **All proposals under `$HAEX_HIVE_STATE/migrations/...`**. Rejected: for a local file, an in-tree `.migrated` sibling is discoverable via `git status` and reviewable via `git diff --no-index` without knowing the state root path. The operator gets a natural review workflow.
- **All proposals in-tree**. Rejected for remote publisher manifests: the operator does not have write access to the remote repo's object tree, and materializing the proposal inside the local `haex-hive` checkout would pollute the source tree with foreign-repo files.

---

## D5: Model-class rename `atom_manifest.py` → `molecule_manifest.py`

**Decision**: Rename the Python module `src/haex_hive/model/atom_manifest.py` to `molecule_manifest.py` and rename its dataclass(es) from `AtomManifest` to `MoleculeManifest` in the same commit. Every import path is updated in one sweep. No compatibility shim (no `atom_manifest = molecule_manifest` re-export) is introduced.

**Rationale**: The v3 vocabulary (Spec 007 v3 + this spec) treats the per-directory manifest as describing a "molecule" that contains a category-keyed map of "atoms" (delivered files). Keeping the module named after the old prose meaning of "atom" would freeze the vocabulary mismatch inside the codebase. Pre-user policy makes a hard-rename acceptable.

**Alternatives considered**:
- **Keep module name, only rename dataclass**. Rejected: leaves grep-hostile mismatch between filename and content; every future contributor pays a small tax.
- **Introduce a compatibility shim**. Rejected: pre-user policy, and shims tend to outlive their utility.

---

## D6: Schema loader dispatch

**Decision**: The v3 schema loader in `src/haex_hive/schema/loader.py` accepts only `haex_hive_version: "3"` in every read path. Any other version at the top of a consumer, publisher, or molecule manifest is refused with a message that names `haex migrate` as the next step. The `haex migrate` command remains the sole entry point that reads v2 (and, transitively, v1) input and emits v3 proposals.

**Rationale**: A single-version tool (post-D1) has a single dispatch. The migrate command is the ONE reader that must understand older versions to produce proposals; that reader lives inside `src/haex_hive/migrate/` and is not shared with the runtime read path. This separation keeps the runtime path simple and keeps the migration reader's complexity bounded to a single module.

**Alternatives considered**:
- **Version-dispatching read path shared by runtime and migrate**. Rejected: violates D1 by preserving v2 knowledge in a runtime hot path. Also complicates test surface.
- **Loose read that tolerates v2 shapes and coerces to v3 in memory**. Rejected: silently violates FR-004 and would let a v2 file appear to "work" without adoption.

---

## D7: Held-lock context between `haex add`/`haex remove` and `haex install`

**Decision**: `haex_hive.cli.install.run(...)` gains an optional `held_manifest_lock: ManifestLockContext | None = None` parameter. When present, the install code path skips its own manifest-lock acquisition and reuses the passed context for read operations against `.haex-hive.json`. When absent (standalone `haex install`), install acquires the lock itself before reading the manifest. This threads the FR-027 requirement without turning the manifest lock into a global.

**Rationale**: Nested lock acquisition on the same file descriptor is safe under `fcntl.flock` (POSIX documents this as reentrant on the same fd) but not portable to Win32 `LockFileEx`. Passing the context object explicitly avoids that portability foot-gun. It also matches Spec 008's pattern for the writer lock, which similarly threads context objects rather than relying on ambient state.

**Alternatives considered**:
- **Global "manifest lock is held" flag**. Rejected: ambient global state, hard to test.
- **Standalone `haex install` also always acquires the manifest lock in a new stack frame regardless of caller**. Rejected: works on POSIX for the trivial case (same fd), fails on Windows.
- **Merge `haex add` and `haex install` into one function without a subcall boundary**. Rejected: overcouples the CLI wrapping to the install pipeline and would duplicate install logic.

---

## D8: Interaction with Spec 011 workflow-molecule adoption

**Decision**: `haex add` refuses with `workflow-molecule-already-adopted` when the added molecule set includes a molecule whose per-molecule manifest declares a non-empty `atoms.workflow` list AND `.haex-hive.json`'s existing `compounds[]` already resolves to a different workflow molecule (FR-019). The refusal names the currently adopted workflow molecule; the operator must run `haex remove <current-id>` first, per Spec 011 amendment FR-008. `haex add` never emits an activation step (there is none under the Spec 011 amendment).

**Rationale**: Spec 011 amendment FR-008 already establishes the "at most one workflow molecule adopted" invariant and the fallback-to-bundled-speckit behavior. Spec 013 inherits this rule; the CLI just needs to detect the situation and refuse cleanly.

**Alternatives considered**:
- **Automatically remove the existing workflow molecule when adding a new one**. Rejected: silent replacement of a workflow atom hides operator intent. Explicit `haex remove` first, then `haex add`, is the visible flow.
- **Refuse only at install time**. Rejected: `haex add` has already fetched the publisher manifest and knows enough to detect the conflict pre-write; refusing pre-write is the earliest place the operator can be told.

---

## D9: Interaction with the single-constitution rule (superseded by Spec 013 Clarification, 2026-09-04)

**Decision (as clarified 2026-09-04)**: `haex add` refuses at the CLI boundary with `constitution-already-adopted` when the added molecule set includes a constitution-contributing molecule AND the consumer's existing `compounds[]` already resolves to another constitution-contributing molecule. haex-hive does NOT perform multi-source constitution merges. The `--llm=file` two-phase flow and `haex install --accept-merged` are retired by ADR 0010 and NOT re-introduced by Spec 013. The operator combines two constitutions externally into one prose atom if needed.

**Rationale**: Principle VI is NON-NEGOTIABLE and ADR 0010 removed the multi-source LLM merge as the mechanism that would have violated it in practice. Spec 014 formalizes the "exactly one prose atom with `binding: non-negotiable` per repository" rule. `haex add` therefore refuses pre-write when it would break that rule; no manifest edit persists, no review candidate is produced. This is the cleanest way to keep the tool a pure function of pinned inputs.

**Alternatives considered (rejected)**:
- **`haex add --accept-merged <candidate>`** (single-command sugar for a merge flow). Rejected: presumes a merge path that no longer exists.
- **Automated in-tool merge with review candidate**. Rejected: retired by ADR 0010; would need a fresh amendment to reintroduce.
- **Silent replacement (auto-remove the existing constitution atom)**. Rejected: too destructive; the operator must consciously choose which constitution rules a repository.

**Prior-version note**: an earlier draft of this decision described a `haex add`-yields-to-`--llm=file` path. That draft is superseded by the 2026-09-04 clarification in [spec.md](./spec.md) `## Clarifications` and by ADR 0010; retained here in prose only to prevent confusion if reviewers see the earlier PR diff.

---

## D10: `haex migrate` idempotency and failure cleanup

**Decision**: `haex migrate` in write mode wraps every proposal-producing operation in a per-invocation temp-file registry. On any transform, validation, or write failure inside the invocation, the registry unregisters and removes every temporary file and every proposal produced by that invocation before propagating the error. `--dry-run` and `--check` do not touch the filesystem. On a v3-adopted repository, every transform detects the v3 shape at input and short-circuits without emitting proposals (FR-011 idempotency).

**Rationale**: FR-010 explicitly requires this cleanup behavior; a partial proposal left after a failure would confuse review workflows and clutter `git status`. Idempotency (FR-011) matches Principle VI's determinism requirement: running the migrator repeatedly is a no-op on a settled repo.

**Alternatives considered**:
- **Best-effort cleanup that logs partial failures but does not remove**. Rejected: violates FR-010 wording.
- **Refuse the second migrate run on a v3 file**. Rejected: idempotent no-op is friendlier and matches how similar migration tools behave.

---

## D11: Publisher-manifest bump timing for `haexmas/haex-hive` and `haexmas/atoms`

**Decision**: haex-hive's own root `manifest.json` (currently v2) and `.haex-hive.json` (currently v2) are migrated to v3 within the same PR that ships this spec. The `haexmas/atoms` repository is already published at v3 (verified 2026-09-04 at revision `ff6fda2180563479497e0bd5a25144653d3175fb`); no change is needed there. Once this PR lands, `haex-vault` (or any other v3 consumer) can `haex install` at the v3 tool version and adopt the atoms-repo molecules directly.

**Rationale**: The pre-user policy lets us make the transition atomic. A PR that flipped the tool to v3 while leaving haex-hive's own manifests at v2 would break haex-hive's ability to install itself. Bundling the manifest migration into the same PR keeps the repository consistent at every commit boundary.

**Alternatives considered**:
- **Two PRs: tool first, then migrate haex-hive's own manifests**. Rejected: leaves haex-hive in a broken state between merges. Even with pre-user policy, that friction hurts development on haex-hive itself.
- **Auto-migrate haex-hive's own manifests as part of the tool's install-time**. Rejected: violates Principle VI (in-place rewrite of versioned config); the human review of the migration commit stays required.
