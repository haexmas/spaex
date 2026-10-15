# Feature Specification: v3 Vocabulary and `haex add` / `haex remove` CLI

**Feature Branch**: `013-add-cli-and-molecule-rename`
**Created**: 2026-09-04
**Status**: Draft
**Input**: Design preview at [`docs/plans/2026-09-02-spec-013-add-cli-and-molecule-rename-design.md`](../../docs/plans/2026-09-02-spec-013-add-cli-and-molecule-rename-design.md)

## Clarifications

### Session 2026-09-04

- Q: How should a second `haex` process behave when the manifest lock `.haex-hive.json.lock` is held by a hung (not-crashed) predecessor? → A: Bounded wait with default 30 s, then refuse with `manifest-lock-contended`. Operator can override via `--lock-timeout=<sec>` (0 = fail-fast).
- Q: How should `haex add` behave when the added molecule would introduce a second constitution-contributing atom into the consumer's adopted set? → A: Refuse with `constitution-already-adopted`, name the currently adopted constitution-contributing molecule, and require the operator to `haex remove <current-id>` first. **haex-hive does NOT merge constitutions.** If the operator wants two constitutions' worth of principles, they combine them into one prose atom externally and adopt that single atom. This aligns with ADR 0010 (multi-source LLM merge retired) and Spec 014 (single non-negotiable prose atom per repository). Consequence: the `--llm=file` two-phase flow, `haex install --accept-merged`, `.haex-hive/pending/`, and the `constitution-review-pending` refusal key are all removed from Spec 013.
- Q: In what order are molecule ids stored inside a compound's `molecules[]` array after `haex add` merges new ids? → A: Deduplicated and lexically sorted. Array order is a byte-form/determinism concern only (byte-identical output for the same input; friendlier git diffs). Runtime execution order — which molecule is assembled or applied first — comes from the molecule manifest's `priority` field (publisher default), optionally overridden per molecule id via the consumer manifest's `compounds[].config.<molecule-id>.priority`. Array position is not consulted at resolution time.

### Session 2026-10-15

- Q: What happens to the molecules already adopted from a source when `spaex add` resolves that source to a different revision than the existing compound pins? → A: They are kept. `spaex add` only ever adds; removal happens exclusively through `spaex remove`. The compound keeps every existing molecule, gains the newly added ids, and the whole compound is re-pinned to the new revision (deduplicated, lexically sorted). `track` and every per-molecule `config` entry are preserved. This supersedes the earlier replace semantics, under which adding one molecule at a new revision silently dropped every other molecule of that compound.
- Q: How does the operator see that `spaex add` implicitly re-pinned molecules they did not name? → A: The output lists the carried-over molecules separately from the newly added ones, with the old and new short revision (`<old-sha> -> <new-sha>`).
- Q: What if a carried-over molecule no longer exists in the publisher manifest at the new revision? → A: Refuse with `molecule-id-not-in-source`, name the carried-over molecule(s), and write nothing. The operator runs `spaex remove <id>` first. A carried-over molecule is never dropped silently.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - v3 vocabulary in the consumer and molecule manifests (Priority: P1)

The tool speaks a single manifest vocabulary that matches Spec 007 v3. In `.haex-hive.json` the outer list is `compounds[]`, each compound contains a `molecules[]` list. In per-molecule manifests, the delivered files are grouped by category under `atoms{category: [paths]}`. Both files carry `haex_hive_version: "3"`. The tool refuses v2 files at load-time with a clear message pointing at the migrator.

**Why this priority**: This is the foundation. Without a v3-speaking tool, the atoms repository (which already publishes v3 molecule manifests such as `com.github.haexmas.atoms.graphify-first-authoring`) cannot be installed at all. Every other user story in this spec depends on it.

**Independent Test**: A test project with a hand-written v3 `.haex-hive.json` referencing a v3 molecule manifest resolves and installs cleanly. A test project with a v2 `.haex-hive.json` receives a load-time refusal that names the migrator command. No hidden v2 tolerance path exists.

**Acceptance Scenarios**:

1. **Given** a `.haex-hive.json` with `haex_hive_version: "3"` and a `compounds[]` list of one compound naming one molecule at a pinned revision, and a corresponding publisher and molecule manifest also at v3, **When** the operator runs `haex install`, **Then** the install proceeds and produces `.haex-hive/` per Spec 008's contract.
2. **Given** a `.haex-hive.json` with `haex_hive_version: "2"`, **When** the operator runs `haex install`, **Then** the tool refuses with a diagnostic that names `haex migrate` as the next step and does not modify any file.
3. **Given** a v3 consumer manifest that references a molecule from a publisher whose root `manifest.json` is still v2, **When** the operator runs `haex install`, **Then** the install refuses with a version-mismatch diagnostic; a v3 consumer never silently accepts v2 publisher metadata.

---

### User Story 2 - `haex migrate` covers v2 → v3 (Priority: P1)

An operator with an existing v2 project (including haex-hive itself) can run `haex migrate` and receive one review-gated proposal per affected file. Every proposal is written to a sibling `<file>.migrated` (or under `$HAEX_HIVE_STATE/migrations/<source-digest>/<revision>/…` for remote publisher files) with a printed unified diff. The operator adopts the proposals manually; the tool never mutates originals unattended.

**Why this priority**: The tool itself cannot boot on v3 until haex-hive's own `.haex-hive.json` and `manifest.json` are migrated to v3. Without US2, US1 lands a tool that cannot install its own repository, and the pre-user policy that lets us break v2 becomes moot.

**Independent Test**: Running `haex migrate --check` on haex-hive's own root produces a proposal for `.haex-hive.json.migrated`, a proposal for `manifest.json.migrated`, and a proposal for every affected molecule manifest, each with a printed diff, without touching the originals. Running `haex migrate` in write mode leaves originals untouched and only writes proposals plus any temporary state; a failed transform removes every temporary file it produced.

**Acceptance Scenarios**:

1. **Given** a repository at v2 with a `.haex-hive.json`, a root `manifest.json`, and one molecule manifest, **When** the operator runs `haex migrate --check`, **Then** the tool prints three proposal paths with their diffs and exits without modifying any file.
2. **Given** the same repository, **When** the operator runs `haex migrate` and the transform succeeds, **Then** every `<file>.migrated` proposal exists and validates against the v3 schema; originals are unchanged.
3. **Given** the same repository, **When** the transform fails on any file (schema, validation, or write error), **Then** every temporary file and proposal the invocation produced is removed and originals are unchanged.
4. **Given** a v3-adopted repository, **When** the operator runs `haex migrate` again, **Then** the transform is a no-op and no proposals are written.
5. **Given** a v1 repository, **When** the operator runs `haex migrate`, **Then** the transform applies v1 → v2 and then v2 → v3 within one review-gated batch.

---

### User Story 3 - `haex add` adopts a molecule in one command (Priority: P2)

An operator adopts an atom by running `haex add <source-url> [<molecule-id>[,<molecule-id>…]] [--revision=<SHA>] [--all]`. The command edits `.haex-hive.json`, resolves a full SHA if the operator did not pin one, and calls the existing `haex install` in the same invocation. No manual JSON editing is required.

**Why this priority**: One-line adoption is the primary UX win of Spec 013. It removes the copy-paste-a-JSON-block instruction from every atom README (the Spec 012 hopper README, the graphify README, and future atoms). US3 depends on US1 (v3 vocabulary in the write path); it is P2 because a v3 tool without `haex add` is still usable via manual edits, whereas a `haex add` without v3 would freeze v2 vocabulary at exactly the moment we get to fix it.

**Independent Test**: Running `haex add https://github.com/haexmas/atoms com.github.haexmas.atoms.speckit-session-hopper` on a v3-adopted repository (a) resolves the current HEAD SHA if `--revision` was not given, (b) writes a `compounds[]` entry containing that revision and the molecule id, and (c) runs `haex install` in the same process. The resulting `.haex-hive.json` is a valid v3 manifest and the installed state matches Spec 008's post-install contract.

**Acceptance Scenarios**:

1. **Given** a v3-adopted repository with no compound for `<source-url>`, **When** the operator runs `haex add <source-url> <molecule-id>`, **Then** a new compound is appended with the resolved SHA and molecule id, `haex install` runs successfully, and both actions complete under a single manifest lock so no other process observes a half-written state.
2. **Given** a repository that already has a compound for the same `<source-url>` at the same resolved revision, **When** the operator runs `haex add <source-url> <new-molecule-id>`, **Then** the new molecule id is merged into the existing compound's `molecules[]` list rather than appended as a duplicate compound.
3. **Given** a repository that already has a compound for the same `<source-url>` at a different resolved revision, **When** the operator runs `haex add <source-url> <molecule-id>` (with or without `--revision`), **Then** every molecule already in that compound is kept, the new molecule id is added, and the whole compound is re-pinned atomically to the new revision after the new publisher manifest validates; `track` and per-molecule `config` entries are preserved, and the output lists the carried-over molecules (old short SHA to new short SHA) separately from the added ones. If a carried-over molecule no longer exists in the publisher manifest at the new revision, the tool refuses with `molecule-id-not-in-source`, names it, and does not modify the manifest.
4. **Given** an operator ran `haex add <source-url>` without positional molecule ids and without `--all`, **When** the terminal is a TTY, **Then** the tool fetches the publisher manifest at the resolved SHA and prompts the operator to pick one or more molecule ids from the discovered list; a non-TTY invocation refuses with a diagnostic that asks for explicit molecule ids or `--all`.
5. **Given** an operator ran `haex add --all <source-url>`, **When** the publisher manifest resolves at the given revision, **Then** every molecule id listed by that publisher manifest is included in the compound; `--all` and a positional molecule-id list are mutually exclusive and combining them refuses.
6. **Given** the newly added compound resolves a workflow molecule while a different workflow molecule is already adopted, **When** the manifest edit is validated, **Then** the tool refuses with `workflow-molecule-already-adopted`, names the currently adopted workflow molecule, and does not modify `.haex-hive.json`.
7. **Given** the operator has already adopted a molecule that contributes a constitution and now attempts to `haex add <source-url> <second-constitution-molecule>`, **When** the manifest edit would introduce a second constitution-contributing molecule, **Then** the tool refuses with `constitution-already-adopted`, names the currently adopted constitution-contributing molecule, and does not modify `.haex-hive.json`. Recovery is by `haex remove <current-id>` first, or by combining the two constitutions into one atom externally and adopting that single atom.
8. **Given** the underlying `haex install` fails after `haex add` wrote the manifest edit, **When** the error surfaces, **Then** `haex add` rolls the manifest edit back atomically under the still-held manifest lock and reports the recovery path if the rollback itself fails.

---

### User Story 4 - `haex remove` retracts a molecule (Priority: P3)

An operator retracts an adopted molecule by running `haex remove <molecule-id>[,<molecule-id>…]`. The command removes every named molecule id from every compound in `.haex-hive.json`, drops compounds whose `molecules[]` empties out, and calls `haex install` so Spec 008's delete-orphans deletes whatever the removed molecules contributed.

**Why this priority**: The symmetric counterpart of `haex add`. Nice to have but not blocking; an operator can also remove a molecule by hand-editing `.haex-hive.json` and re-running install.

**Independent Test**: Running `haex remove <molecule-id>` on a repository that adopts that molecule (a) removes it from the compound(s), (b) drops any compound whose `molecules[]` became empty, and (c) runs `haex install`. Files installed only by the removed molecule are deleted per Spec 008.

**Acceptance Scenarios**:

1. **Given** a repository with a compound containing `[<molecule-id-a>, <molecule-id-b>]`, **When** the operator runs `haex remove <molecule-id-a>`, **Then** the compound's `molecules[]` becomes `[<molecule-id-b>]` and any file the tool published only for `<molecule-id-a>` is deleted by the ensuing install.
2. **Given** a repository with a compound containing only `[<molecule-id-a>]`, **When** the operator runs `haex remove <molecule-id-a>`, **Then** the compound is dropped from `compounds[]` and the install runs with the smaller manifest.
3. **Given** a `<molecule-id>` that is not present in any compound, **When** the operator runs `haex remove <molecule-id>`, **Then** the tool refuses with `unknown-molecule-id` and does not modify `.haex-hive.json`.
4. **Given** the removed molecule is the currently adopted workflow molecule, **When** the ensuing install completes, **Then** the tool falls back to the bundled `speckit` workflow on the next resolve without requiring a separate activation step (per Spec 011 amendment FR-008).

---

### Edge Cases

- **`git ls-remote` cannot reach the source**: `haex add` fails fast with `source-url-invalid`; nothing is written.
- **An explicit `--revision=<SHA>` does not exist at the remote**: `haex add` refuses with `revision-not-found` before any manifest edit.
- **The resolved publisher manifest has no `manifest.json` at the repo root**: `haex add` refuses with `publisher-manifest-missing`.
- **A positional `<molecule-id>` is not listed in the publisher manifest at the resolved revision**: `haex add` refuses with `molecule-id-not-in-source`.
- **Two `haex` processes race**: the manifest lock (`.haex-hive.json.lock`) serializes them; the second one either waits or refuses on contention; no half-written state is observable.
- **A failed transform in `haex migrate` leaves temporary files**: the transform must remove every temporary file and proposal produced by that invocation on failure, while leaving all originals untouched.
- **A v3 consumer against a v2 publisher**: refused with a version-mismatch diagnostic; never silently accepted.
- **`haex migrate` run twice**: idempotent on a v3-adopted repository (no-op, no proposals).

## Requirements *(mandatory)*

### Functional Requirements

**Vocabulary and version (US1 foundation):**

- **FR-001**: The tool MUST read and write `.haex-hive.json` in v3 shape: `haex_hive_version: "3"`, top-level `compounds[]` (renamed from v2 `atoms[]`), each compound with `source`, `revision`, and `molecules[]` (renamed from v2 `includes[]`).
- **FR-002**: The tool MUST read and write per-molecule manifests in v3 shape: `haex_hive_version: "3"`, top-level `id`, `version`, `priority`, and `atoms{category: [paths]}` (replacing the v2 scalar `contributes`).
- **FR-003**: The tool MUST read and write publisher-root manifests in v3 shape: `haex_hive_version: "3"`, top-level `molecules{}` map (renamed from v2 `atoms{}`), each entry preserving id, path, version, and optional description.
- **FR-004**: The tool MUST refuse a v2 consumer manifest, a v2 molecule manifest, or a v2 publisher-root manifest at load-time with a diagnostic that names `haex migrate` as the next step. There is no runtime tolerance path.
- **FR-005**: The tool MUST refuse to resolve a v3 consumer manifest against a v2 publisher manifest (and vice versa) with an explicit version-mismatch diagnostic.
- **FR-006**: `haex_hive_min_version` in a v3 consumer manifest MUST preserve the operator and meaning of its predecessor: exact `2.x.y` becomes exact `3.x.y`; lower bound `>=2.x.y` becomes `>=3.0.0`. Any other major on the constraint refuses as unsupported.

**Migration (US2):**

- **FR-007**: `haex migrate` MUST extend its existing v1 → v2 transform with a v2 → v3 transform. Running it on v1 sources applies both transforms as one review-gated batch.
- **FR-008**: `haex migrate` MUST emit one proposal per affected file: `.haex-hive.json.migrated` for the consumer manifest, `manifest.json.migrated` for a local publisher-root manifest or a local molecule manifest, and `$HAEX_HIVE_STATE/migrations/<source-digest>/<revision>/<repo-relative-path>.migrated` for a publisher manifest read from an immutable remote revision. Every proposal is validated against the v3 schema.
- **FR-009**: `haex migrate` MUST print a unified diff for every input/proposal pair, including the target path and adoption instructions. Adoption is a manual operator step; the tool never overwrites originals.
- **FR-010**: `haex migrate` in write mode MUST remove every temporary file and every proposal produced by the invocation on any failed transform, validation, or proposal publication, while leaving all originals untouched. `--dry-run` and `--check` mutate nothing.
- **FR-011**: `haex migrate` MUST be idempotent: running it on an already-adopted v3 file is a no-op that emits no proposals.
- **FR-012**: `haex migrate` MUST default a missing `priority` in an affected v2 molecule manifest to `100` in the v3 proposal, and preserve every existing integer priority unchanged.
- **FR-013**: `haex migrate` MUST preserve molecule ids, versions, priorities (subject to FR-012), and file bytes across the transform. Directory-form v2 `contributes` entries expand deterministically to their regular files in the v3 `atoms` category list; scalar contributions become single-element lists.

**`haex add` (US3):**

- **FR-014**: `haex add <source-url> [<molecule-id>[,<molecule-id>…]] [--revision=<SHA>] [--all]` MUST edit `.haex-hive.json` and then run `haex install` in the same invocation. Both actions execute under a single acquisition of the manifest lock.
- **FR-015**: When `--revision` is omitted, `haex add` MUST resolve the source's current HEAD SHA via `git ls-remote` and write that full SHA verbatim into the compound entry. When `--revision` is given, that value is written verbatim.
- **FR-016**: When `<molecule-id>` positional arguments are omitted and `--all` is not passed, `haex add` MUST fetch the publisher manifest at the resolved revision and, on a TTY, prompt the operator to select one or more molecule ids from the discovered list. Non-TTY invocations MUST refuse and ask for explicit molecule ids or `--all`.
- **FR-017**: `--all` selects every molecule id present in the publisher manifest at the resolved revision. `--all` and positional molecule ids MUST be mutually exclusive.
- **FR-018**: If a compound with the same `source` and `revision` already exists, `haex add` MUST merge the new molecule ids into that compound's `molecules[]` list rather than append a duplicate compound. After the merge, the compound's `molecules[]` MUST be deduplicated and lexically sorted (Unicode code-point order); an existing manual ordering is not preserved. This is a byte-form determinism rule: array position does not affect runtime execution order, which is determined by the molecule manifest's `priority` field (publisher default) and optional per-molecule-id `config.<molecule-id>.priority` overrides. If a compound exists for the same `source` at a different resolved `revision`, `haex add` MUST keep every molecule already in that compound, add the new molecule ids, and re-pin the whole compound to the new `revision` atomically after the new publisher manifest has validated (amended 2026-10-15; `haex add` never removes an adopted molecule, only `haex remove` does). The compound's `track` and every `config` entry MUST be preserved. Every carried-over molecule MUST exist in the publisher manifest at the new `revision`; otherwise `haex add` MUST refuse with `molecule-id-not-in-source` naming it and write nothing. The output MUST list carried-over molecules separately from newly added ones, with the old and new short revision. The singleton rules of FR-019 and FR-020 apply to the resulting molecule set, including the re-pinned carried-over molecules. The same rules apply to `--local` adoption against the local overlay.
- **FR-019**: `haex add` MUST refuse with `workflow-molecule-already-adopted` when the added molecule set includes a workflow molecule and `compounds[]` already resolves to a different workflow molecule. The refusal names the currently adopted workflow molecule and asks the operator to `haex remove <current-id>` first.
- **FR-020**: `haex add` MUST refuse with `constitution-already-adopted` when the added molecule set includes a molecule whose per-molecule manifest declares a non-empty `atoms.constitution` list AND the consumer's existing `compounds[]` already resolves to another molecule that also contributes a constitution. The refusal names the currently adopted constitution-contributing molecule and asks the operator to `haex remove <current-id>` first. haex-hive MUST NOT perform multi-source constitution merges (per ADR 0010 and Spec 014); the tool ships no `--llm=file` or `--accept-merged` path in Spec 013 and does not persist a manifest edit for a review-gated merge.
- **FR-021**: When the underlying `haex install` fails after `haex add` has written the manifest edit, `haex add` MUST roll the edit back atomically under the still-held manifest lock. A rollback failure MUST report the recovery path without releasing the manifest lock early.
- **FR-022**: `haex add` MUST expose the refusal keys `source-url-invalid`, `revision-not-found`, `publisher-manifest-missing`, `publisher-manifest-invalid`, `molecule-id-not-in-source`, `workflow-molecule-already-adopted`, and `constitution-already-adopted`. Each key names the failing input in the diagnostic. No `constitution-review-pending` key exists; multi-source constitution merges are refused pre-write per FR-020, not deferred to a post-install review candidate.

**`haex remove` (US4):**

- **FR-023**: `haex remove <molecule-id>[,<molecule-id>…]` MUST remove every named molecule id from every compound in `.haex-hive.json` and drop any compound whose `molecules[]` becomes empty. It MUST then run `haex install` under the same lock acquisition.
- **FR-024**: `haex remove` MUST refuse with `unknown-molecule-id` when a named molecule id is not present in any current compound and MUST NOT modify `.haex-hive.json` in that case.
- **FR-025**: When the removed molecule is the currently adopted workflow molecule, the ensuing install MUST cause the tool to fall back to the bundled `speckit` workflow on the next resolve without any activation step (per Spec 011 amendment FR-008).

**Concurrency and integrity:**

- **FR-026**: `haex add` and `haex remove` MUST acquire the permanent advisory manifest lock at `.haex-hive.json.lock` before reading or replacing `.haex-hive.json`. The lock file MUST be created once if absent and MUST NEVER be renamed, replaced, or removed by the tool. Lock acquisition order is manifest lock first, then device-local install mutex.
- **FR-027**: `haex install` invoked standalone MUST acquire the manifest lock before reading `.haex-hive.json`. `haex install` invoked in-process by `haex add` or `haex remove` MUST accept the held-lock context and MUST NOT acquire the manifest lock a second time.
- **FR-028**: Manifest-lock acquisition MUST use a bounded-wait strategy with a default timeout of 30 seconds. A contender that cannot acquire the lock within the timeout MUST refuse with `manifest-lock-contended` (exit code 6) rather than block indefinitely. The timeout MUST be operator-configurable via a `--lock-timeout=<sec>` flag on `haex add`, `haex remove`, and `haex install`; a value of `0` means fail-fast (refuse immediately on contention without any wait). The tool MUST NOT attempt to detect or forcibly break a lock held by a still-running process; kernel-level release on process exit remains the sole automatic recovery path.

### Key Entities

- **Consumer manifest** (`.haex-hive.json`): the operator's own file declaring which molecules to adopt. In v3: `haex_hive_version`, `identity`, `haex_hive_min_version`, `compounds[]`, `groups[]`, `active_feature`.
- **Compound**: one entry in `compounds[]`, keyed logically by `(source, revision)` and holding a `molecules[]` list of adopted molecule ids.
- **Molecule**: a publisher-side packaging unit named in the publisher manifest's `molecules{}` map. Its per-molecule manifest declares delivered files by category under `atoms{}`.
- **Publisher-root manifest** (`manifest.json`): the publisher-side file that maps molecule ids to their per-molecule directories and versions.
- **Atom (category)**: one entry inside a molecule manifest's `atoms{}` map: a category name (e.g. `constitution`, `workflow`, `hooks`) mapped to a non-empty list of delivered, molecule-directory-relative paths.
- **Adopted workflow molecule**: a molecule whose manifest declares a non-empty `atoms.workflow` list and which appears in a compound's `molecules[]`. At most one such molecule may be adopted at a time (Spec 011 amendment).
- **Migration proposal**: a `<file>.migrated` sibling (or a state-directory-rooted proposal for remote publisher files) validated against the v3 schema and displayed as a unified diff, adopted by an explicit operator step.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The atoms-repository molecule `com.github.haexmas.atoms.graphify-first-authoring` at its current published revision installs into a v3-adopted consumer project through a single `haex install` call, with no v2 workarounds and no hand-modified manifests.
- **SC-002**: Adopting an atom takes exactly one command (`haex add <source-url> <molecule-id>`), replacing the current README instruction of "paste this JSON into `.haex-hive.json` and run `haex install`".
- **SC-003**: Retracting an atom takes exactly one command (`haex remove <molecule-id>`), and the ensuing install removes every file the retracted molecule contributed (per Spec 008 delete-orphans).
- **SC-004**: Running `haex migrate` on haex-hive's own v2 root produces one proposal per affected file (consumer manifest, publisher-root manifest, and any local molecule manifest present), each validated against the v3 schema. Adopting all proposals lets `haex install` succeed on haex-hive itself.
- **SC-005**: A v2 manifest never installs silently: every load-time refusal names `haex migrate` as the next step within the diagnostic itself, so no operator has to hunt for the migration command.
- **SC-006**: A concurrent `haex add` and standalone `haex install` never observe a half-written `.haex-hive.json`; the second contender either waits or refuses on lock contention.
- **SC-007**: Every failed `haex migrate` invocation removes every temporary file and proposal it produced in the same directory tree, verified by a directory-diff after the failure.

## Assumptions

- **Pre-user policy**: haex-hive has no external adopters as of 2026-09-04. A hard v2-refuse plus a `haex migrate` hint is acceptable; no dual-vocabulary tolerance layer is required.
- **`haex install` primitives are stable**: Spec 008 has landed. `haex add` and `haex remove` add no new file-publication primitives; they edit `.haex-hive.json` and delegate.
- **`git ls-remote` and shallow-clone availability**: the operator has git installed and can reach `<source-url>`. `haex add` does not offer an offline mode.
- **Adoption implies binding for workflow molecules**: per the Spec 011 amendment, adopting a workflow molecule in `.haex-hive.json` alone makes it the binding workflow. No activation step exists; `haex add` therefore ships no `workflow activate` subcommand and no `--activate` flag.
- **Rename is worth the churn**: renaming v2 vocabulary to v3 (`atoms[]` → `compounds[]`, `includes[]` → `molecules[]`, `contributes` scalar → `atoms{}` category map) is a judgment call whose value (matching Spec 010 and Spec 007 v3 prose; `atoms:` inside a molecule reads naturally) outweighs the migration cost (test-fixture sweep, migrate transform, two publisher-manifest updates).
- **Single constitution atom per repository**: per ADR 0010 and Spec 014, a repository adopts exactly one prose atom with `binding: non-negotiable`. Spec 013 refuses to add a second constitution-contributing molecule at the CLI boundary (FR-020, `constitution-already-adopted`). No multi-source merge path exists in Spec 013.
- **Interactive molecule-id selection is TTY-only at MVP**: non-TTY callers must pass positional molecule ids or `--all`.

## Dependencies

- **Spec 007** ([`specs/007-unified-manifest-v2/`](../007-unified-manifest-v2/)): defines the v3 molecule model this spec consumes. Spec 013 does not change v3's molecule-side schema; it defines the consumer-side rename and the CLI wrappers.
- **Spec 008** ([`specs/008-install-transaction/`](../008-install-transaction/)): defines the install transaction, delete-orphans, and lockfile semantics that `haex add` and `haex remove` invoke unchanged.
- **Spec 011 amendment (2026-09-02)** ([`specs/011-speckit-workflow-atom/`](../011-speckit-workflow-atom/)): retires `workflow-registry.json` and `active_workflow`. Spec 013 inherits this: no activation step, no separate workflow subcommand.
- **Constitution Principle IV (immutable revisions)** ([`.specify/memory/constitution.md`](../../.specify/memory/constitution.md)): `haex add` writes only full 40-hex SHAs.
- **Constitution Principle VI (review-gated schema migrations)**: `haex migrate` produces `.migrated` sidecars for operator review, never mutating originals. `haex add` and `haex remove` write to `.haex-hive.json` in place (a user-authored file whose edit is the operator's own intent), reviewable through the project's PR flow rather than through an in-tool merge candidate.
- **ADR 0010 and Spec 014 (single non-negotiable prose atom)**: `haex add` refuses to introduce a second constitution-contributing molecule; no multi-source merge is available in Spec 013.
