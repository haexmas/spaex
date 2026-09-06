---
description: "Task list for Spec 013: v3 vocabulary and haex add/remove CLI"
---

# Tasks: v3 Vocabulary and `haex add` / `haex remove` CLI

**Input**: Design documents from `/specs/013-add-cli-and-molecule-rename/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)
**Tests**: Included. The feature touches schema shape, lock semantics, migration determinism, and cross-platform behavior — every one of these is a class the operator has repeatedly asked to catch at test time rather than in production, so tests are part of the task list rather than optional.

**Checkbox freshness is load-bearing.** When a task is completed, tick its checkbox in the same commit as the task's output — or at the latest in the next commit, before starting the next task. See [ADR 0004](../../docs/adr/0004-eager-checkbox-update-rule.md).

**Organization**: Tasks are grouped by phase and by user story to enable independent implementation and independent testing of each story.

## Format

`- [ ] TID [P?] [Story?] Description with file path`

- `[P]`: parallelizable (different files, no dependency on incomplete tasks in the same phase)
- `[Story]`: user story tag (`[US1]`, `[US2]`, `[US3]`, `[US4]`). Setup, Foundational, and Polish phases carry no story tag.
- Every task names the exact file path it touches.

## Path Conventions

Single Python CLI project (unchanged from Specs 007 and 008):

- Source: `src/haex_hive/…`
- Tests: `tests/…`
- Docs: `docs/…`, `specs/…`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: prepare the codebase for a v3-only tool. Version bump, schema payload rewrite, and dependency confirmation.

- [X] T001 Bump the tool's version in [pyproject.toml](../../pyproject.toml): change `version = "2.0.0.dev0"` to `version = "3.0.0.dev0"` and update the `description` field to reference v3 vocabulary and `haex add`/`haex remove` instead of "Unified manifest v2 CLI".
- [X] T002 [P] Copy [specs/013-add-cli-and-molecule-rename/contracts/consumer-manifest.v3.schema.json](./contracts/consumer-manifest.v3.schema.json) to `src/haex_hive/schema/data/consumer-manifest.v3.schema.json` verbatim so the schema-loader payload matches the spec contract.
- [X] T003 [P] Copy [specs/013-add-cli-and-molecule-rename/contracts/molecule-manifest.v3.schema.json](./contracts/molecule-manifest.v3.schema.json) to `src/haex_hive/schema/data/molecule-manifest.v3.schema.json` verbatim.
- [X] T004 [P] Copy [specs/013-add-cli-and-molecule-rename/contracts/publisher-manifest.v3.schema.json](./contracts/publisher-manifest.v3.schema.json) to `src/haex_hive/schema/data/publisher-manifest.v3.schema.json` verbatim.
- [X] T005 [P] Copy [specs/013-add-cli-and-molecule-rename/contracts/install-lock.v3.schema.json](./contracts/install-lock.v3.schema.json) to `src/haex_hive/schema/data/install-lock.v3.schema.json` verbatim.
- [X] T006 Delete the v2 schema payloads from `src/haex_hive/schema/data/` in one commit: `atom-manifest.v2.schema.json`, `haex-hive.v2.schema.json`, `install-lock.v2.schema.json`, `publisher-manifest.v2.schema.json`. Leave `visibility-marker.v1.schema.json` untouched (Spec 008, unchanged by this feature).
- [X] T007 [P] Update `[tool.setuptools.package-data]` in [pyproject.toml](../../pyproject.toml) if needed to keep the `haex_hive = ["schema/data/*.json"]` glob correct after the file swap (verify no explicit-file entries reference v2 names).

**Checkpoint**: schema payload is v3-only, tool version reflects the major bump. `haex_hive_version: "3"` becomes the only accepted value at the schema layer.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: reshape the model classes and the schema-loader dispatch so US1's runtime read path reads v3 and refuses v2. Applies before every user story.

**⚠️ CRITICAL**: no user story work can begin until this phase is complete; every user story reads at least one of the reshaped model classes.

- [X] T010 Rename `src/haex_hive/model/atom_manifest.py` to `src/haex_hive/model/molecule_manifest.py` (via `git mv`) and rename the exported `AtomManifest` dataclass to `MoleculeManifest` in one atomic edit. Update every import site under `src/haex_hive/` and `tests/` in the same commit.
- [X] T011 Rework `src/haex_hive/model/molecule_manifest.py` field shape to v3: replace the v2 scalar `contributes` field with a `Dict[str, List[str]]` `atoms` field, add `defaults: Optional[Dict[str, Any]]` and `config_schema: Optional[str]`, keep `id`, `version`, `priority`, bump the class's `haex_hive_version` const to `"3"`. Add a load-time check that no path appears in more than one category's list within `atoms{}` and refuse with `atoms-category-overlap` per [data-model.md](./data-model.md) "Cross-category path overlap is refused".
- [X] T012 Rework `src/haex_hive/model/consumer_manifest.py` to the v3 shape per [contracts/consumer-manifest.v3.schema.json](./contracts/consumer-manifest.v3.schema.json): rename `AtomEntry` to `CompoundEntry`, rename its `includes` field to `molecules`, rename the top-level `atoms: List[AtomEntry]` to `compounds: List[CompoundEntry]`, bump the class's `haex_hive_version` const to `"3"`. Update every import site.
- [X] T013 Rework `src/haex_hive/model/publisher_manifest.py` to the v3 shape: rename the top-level `atoms` map to `molecules`, rename `PublisherAtomEntry` to `PublisherMoleculeEntry`, bump `haex_hive_version` const to `"3"`. Update every import site.
- [X] T014 Rework `src/haex_hive/model/install_lock.py` to the v3 shape per [contracts/install-lock.v3.schema.json](./contracts/install-lock.v3.schema.json): rename the top-level `atoms` array to `molecules`, rename `AtomInstallRecord` to `MoleculeInstallRecord`, bump `haex_hive_version` const to `"3"`. Update every import site. **Superseded 2026-09-03 (Spec 008's own npm/pip-shape amendment)**: `MoleculeInstallRecord` was further renamed to `MoleculeEntry` and its `contributed_paths` field to `paths`; `generated_by`, `constitution`, `participating_roots`, and `generation_inputs` were dropped from `InstallLock` entirely.
- [X] T015 Update `src/haex_hive/schema/loader.py` so every read path accepts only `haex_hive_version: "3"` for consumer, publisher, molecule, and install-lock manifests. Any other version raises a diagnostic that names `haex migrate` as the next step. The migrate module remains the only reader that understands older versions (via [`migrate/transform.py`](../../src/haex_hive/migrate/transform.py)).
- [X] T016 Update `src/haex_hive/schema/validator.py` (or equivalent) if it holds v2-specific validation logic: remove v2-specific branches so a v3-only shape is validated end-to-end. Add a helper that dispatches to the correct v3 schema by manifest kind.
- [X] T017 Extend `src/haex_hive/constitution/resolve.py` to read `molecule.atoms.constitution` as a `List[str]` under the v3 shape. Every path in that list contributes a constitution source in the same order the operator declared. Publish the declared constitution paths in `.haex-hive/install.lock` through the v3 lock shape (the standalone `constitution` block was retired by the 2026-09-03 npm/pip-shape amendment; provenance is now derived from `molecules[].paths[]`).
- [X] T018 [P] Update `src/haex_hive/model/atom_id.py` to `molecule_id.py` (rename via `git mv`), rename `AtomId` to `MoleculeId`, and update every import site. The regex and validation logic are unchanged.

**Checkpoint**: model classes and schema dispatch speak v3 exclusively; v2 inputs refuse at load-time; imports across `src/haex_hive/` and `tests/` are consistent.

---

## Phase 3: User Story 1 - v3 vocabulary in the consumer and molecule manifests (Priority: P1) 🎯 MVP

**Goal**: the tool reads and writes v3 manifests end-to-end. haex-hive's own `.haex-hive.json` and root `manifest.json` are migrated to v3 so the repo continues to install itself.

**Independent Test**: create a fixture repo with a hand-written v3 `.haex-hive.json` that references a v3 molecule manifest at a pinned SHA; run `haex install`; expect success and a v3 `.haex-hive/install.lock`. Create a fixture repo with a v2 `.haex-hive.json`; run `haex install`; expect refusal that names `haex migrate` in the diagnostic.

### Tests for User Story 1

- [X] T020 [P] [US1] Add contract tests for the v3 consumer-manifest schema in `tests/contract/test_consumer_manifest_v3.py`: valid minimum shape passes, unknown top-level property fails, `haex_hive_version: "2"` fails, non-40-hex `revision` fails, duplicate molecule id within one compound's `molecules[]` fails.
- [X] T021 [P] [US1] Add contract tests for the v3 molecule-manifest schema in `tests/contract/test_molecule_manifest_v3.py`: `atoms{category: [paths]}` shape passes, empty category array fails, cross-category path overlap fails (via the runtime check invoked by the loader), missing `priority` fails.
- [X] T022 [P] [US1] Add contract tests for the v3 publisher-manifest schema in `tests/contract/test_publisher_manifest_v3.py`: `molecules{}` map passes, `atoms{}` legacy key fails, molecule id not prefixed by `publisher` fails, invalid `path` fails.
- [X] T023 [P] [US1] Add contract tests for the v3 install-lock schema in `tests/contract/test_install_lock_v3.py`: `molecules[]` array passes with `moleculeInstallRecord` entries, unknown root property fails (proves `additionalProperties: false` at root), non-POSIX `contributed_paths` item fails, duplicate items in `contributed_paths` fail. **Superseded 2026-09-03**: entries are now `MoleculeEntry` with a `paths` field (not `moleculeInstallRecord`/`contributed_paths`); the test file was updated accordingly and gained coverage for the new required `generation_id`, the retired top-level fields, and the `molecules[]` canonical-order check.
- [X] T024 [P] [US1] Add an integration test in `tests/install/integration/test_install_v3_end_to_end.py` that installs a fixture v3 consumer against a fixture v3 publisher with one molecule contributing a constitution and produces a v3 `.haex-hive/install.lock` with byte-identical output across runs.
- [X] T025 [P] [US1] Add an integration test in `tests/install/integration/test_install_refuses_v2.py`: a v2 consumer or a v3 consumer resolving against a v2 publisher refuses with a diagnostic that names `haex migrate`, and nothing is written to `.haex-hive/`.

### Implementation for User Story 1

- [X] T030 [US1] Rewrite `.haex-hive.json` at the repo root from the current v2 shape to v3: `haex_hive_version: "3"`, `atoms[]` -> `compounds[]`, per-entry `includes[]` -> `molecules[]`. Preserve the currently-adopted `com.github.haexmas.haex-hive.constitution` compound entry byte-for-byte otherwise.
- [X] T031 [US1] Rewrite `manifest.json` at the repo root from the current v2 shape to v3: `haex_hive_version: "3"`, inner `atoms{}` -> `molecules{}`. Preserve the currently-published `com.github.haexmas.haex-hive.constitution` entry byte-for-byte otherwise.
- [X] T032 [US1] Rewrite the per-molecule `manifest.json` at `.specify/memory/manifest.json` (or wherever the haex-hive constitution molecule declares itself) from v2 shape (`contributes` scalar) to v3 shape (`atoms.constitution: ["constitution.md"]`) and add a default `priority: 100` if absent. Preserve id, version, and file bytes otherwise.
- [X] T033 [US1] Run `haex install` locally against the migrated haex-hive root to confirm SC-004 (haex-hive installs itself under v3); resolve any Principle IV or byte-identity fallout before committing.
- [X] T034 [P] [US1] Update every v2 test fixture under `tests/` to v3 shape. Grep for `haex_hive_version.*2`, `"atoms":`, `"includes":`, `"contributes":` and convert. Preserve semantic intent; only rename fields and expand `contributes` scalars to `atoms{}` category lists (single-element lists for scalar entries; refuse in tests any directory-form entries as unsupported per Spec 013's migrate contract).
- [X] T035 [US1] Update `README.md` at the repo root to reference v3 vocabulary in code snippets and to point at `haex add`/`haex remove` in the Adoption section (mirror [quickstart.md](./quickstart.md)). Docs-only change, but ships in this PR.

**Checkpoint**: US1 fully functional. Every schema, model, and read path speaks v3. haex-hive's own manifests are v3 and the repo installs itself.

---

## Phase 4: User Story 2 - `haex migrate` covers v2 → v3 (Priority: P1)

**Goal**: an operator with a v2 project (or the pre-migration haex-hive itself) can run `haex migrate` and receive one review-gated proposal per affected file.

**Independent Test**: hand-craft a fixture v2 repo (consumer + publisher-root + one per-molecule manifest); run `haex migrate --check`; expect three proposal paths printed with their unified diffs and no files written. Run `haex migrate`; expect three `.migrated` sibling files that validate against the v3 schemas, with originals untouched. Run `haex migrate` again; expect a no-op with no new proposals (idempotency).

### Tests for User Story 2

- [ ] T040 [P] [US2] Add unit tests for the consumer-manifest v2→v3 transform in `tests/unit/test_migrate_consumer_v2_to_v3.py`: `atoms[]` -> `compounds[]`, `includes[]` -> `molecules[]`, `haex_hive_min_version` rewrites per FR-006 (exact `2.x.y` -> exact `3.x.y`, lower bound `>=2.x.y` -> `>=3.0.0`, other majors refuse with `unsupported-min-version-constraint`).
- [ ] T041 [P] [US2] Add unit tests for the molecule-manifest v2→v3 transform in `tests/unit/test_migrate_molecule_v2_to_v3.py`: scalar `contributes.<cat> = "path"` -> `atoms.<cat> = ["path"]`; missing `priority` defaults to `100`; existing integer `priority` preserved; directory-form `contributes.<cat> = "dir/"` refuses with `directory-form-contributes-unsupported` and names the affected categories.
- [ ] T042 [P] [US2] Add unit tests for the publisher-root v2→v3 transform in `tests/unit/test_migrate_publisher_v2_to_v3.py`: inner `atoms{}` -> `molecules{}`, each entry preserves `path`, `version`, `description` byte-identically, `publisher` field preserved.
- [ ] T043 [P] [US2] Add unit tests for the invocation-level behavior in `tests/unit/test_migrate_invocation.py`: idempotency on all-v3 inputs (no proposals), failure cleanup (registered temp files/proposals removed on transform error), `--dry-run` and `--check` do not touch the filesystem, exit code precedence (0 for success/no-op, 1 for mixed proposal+refused, 2 for hard-refusal-without-any-proposal).
- [ ] T044 [P] [US2] Add an integration test in `tests/integration/test_migrate_end_to_end.py`: on a fixture v2 repo (consumer + publisher + molecule), run `haex migrate` and assert each expected `.migrated` sibling exists with content matching the v3 schema. On a fixture publisher read from an immutable remote SHA (via a tmpdir bare repo), assert the proposal lands under `$HAEX_HIVE_STATE/migrations/<source-digest>/<revision>/manifest.json.migrated`.

### Implementation for User Story 2

- [ ] T050 [US2] Extend `src/haex_hive/migrate/transform.py` with a `v2_to_v3` transform function that operates on parsed JSON input and emits parsed JSON output. Cover consumer, molecule, and publisher-root shapes. Route each input through the correct sub-transform based on its shape (presence of `compounds`/`atoms`/`molecules`/`contributes` fields, plus the `haex_hive_version` value).
- [ ] T051 [US2] Extend `src/haex_hive/migrate/transform.py` with the `haex_hive_min_version` rewriter per FR-006. Exact `2.x.y` maps to exact `3.x.y`, lower bound `>=2.x.y` maps to `>=3.0.0`, any other major refuses with `unsupported-min-version-constraint` naming the offending constraint.
- [ ] T052 [US2] Add a per-invocation temp-file/proposal registry to `src/haex_hive/migrate/transform.py` (or to a small helper `src/haex_hive/migrate/registry.py`). The registry registers every path the invocation would create, exposes a `commit()` that clears the registry after all files land, and exposes a `rollback()` that unlinks every registered path. Wire it into every proposal-emission call so a failure inside the invocation cleans up.
- [ ] T053 [US2] Extend the migrate CLI in `src/haex_hive/cli/migrate.py` to chain v1→v2 (unchanged existing transform) and v2→v3 as one review-gated batch. On v3 inputs, short-circuit per input (idempotency). Preserve the existing `--dry-run`/`--check` semantics.
- [ ] T054 [US2] Implement proposal placement per [contracts/haex-migrate.v2-to-v3.md](./contracts/haex-migrate.v2-to-v3.md): `.haex-hive.json.migrated` sibling, `manifest.json.migrated` sibling, `<molecule-dir>/manifest.json.migrated` sibling for local files, and `$HAEX_HIVE_STATE/migrations/<source-digest>/<revision>/<repo-relative-path>.migrated` for publisher files read from immutable remote SHAs. Reuse the `clone_dir()` digest helper from `src/haex_hive/migrate/transform.py`.
- [ ] T055 [US2] Implement the exit-code precedence in `src/haex_hive/cli/migrate.py`: classify every input as `noop`/`proposal`/`refused`; pick invocation exit code by precedence: 2 (hard refusal, no proposals) > 1 (mixed) > 0 (success or all-v3 no-op).
- [ ] T056 [US2] Implement unified-diff printing per input/proposal pair in `src/haex_hive/cli/migrate.py`. Include the target path and adoption instructions (local: `mv <file>.migrated <file>`; remote: copy into publisher checkout, PR, pin bump).

**Checkpoint**: US2 fully functional. A v2 repository can be migrated to v3 through review-gated proposals; failed transforms clean up; idempotent on v3-adopted inputs.

---

## Phase 5: User Story 3 - `haex add` adopts a molecule in one command (Priority: P2)

**Goal**: `haex add <source-url> [<molecule-id>...]` edits `.haex-hive.json` and runs `haex install` in one invocation under a permanent manifest lock.

**Independent Test**: on a v3-adopted repo with no compound for `https://github.com/haexmas/atoms`, run `haex add https://github.com/haexmas/atoms com.github.haexmas.atoms.speckit-session-hopper`. Expect a new compound in `.haex-hive.json` with the resolved SHA, an updated `.haex-hive/install.lock` mentioning the new molecule, and exit 0. Run with `--revision=<older-SHA>` and confirm the exact SHA is written verbatim. Run against a source-URL that fails `git ls-remote`; expect exit 2 with `source-url-invalid` and no manifest edit.

### Tests for User Story 3

- [X] T060 [P] [US3] Add unit tests for the manifest-lock helper in `tests/unit/test_manifest_lock.py`: lock file is created if absent and never renamed/deleted; bounded-wait acquisition returns success within the timeout when the lock frees up in time; contended acquisition after the timeout refuses with `manifest-lock-contended` (exit code 6); `--lock-timeout=0` (fail-fast) refuses immediately on contention without waiting; `--lock-timeout` operator override is honored; nested acquisition in the same process reuses the held context on POSIX and Windows; kernel-level release on process crash is the sole automatic recovery path (the tool does not force-break locks held by living processes).
- [X] T061 [P] [US3] Add unit tests for the `write_and_reinstall` helper in `tests/unit/test_write_and_reinstall.py`: manifest is written atomically via `.haex-hive.json.tmp` + rename; ANY install failure rolls the manifest back under the still-held lock (no `constitution-review-pending` exception — Spec 013 has no post-install review-pending state per the 2026-09-04 clarification); rollback preserves the operator's pre-add-or-remove state byte-identically; a rollback failure surfaces the recovery path with the lock still held.
- [X] T062 [P] [US3] Add unit tests for `git ls-remote`/`git fetch origin <sha> --depth 1` helper in `tests/unit/test_publisher_fetch.py`: resolves HEAD when no `--revision`, uses provided SHA verbatim when `--revision=<SHA>`, refuses with `source-url-invalid` for a bogus URL, refuses with `revision-not-found` for a SHA absent at the remote. The fetch happens into either the existing publisher clone under `$HAEX_HIVE_STATE/repos/<clone-hash>/` or a `tempfile.TemporaryDirectory()` bare repo.
- [X] T063 [P] [US3] Add a CLI test in `tests/cli/test_add.py`: happy-path adoption of a molecule from a fixture publisher (bare repo in tmpdir), merge-into-existing-compound path (same source+revision), replace-compound path (same source, different revision), non-TTY refusal without positional ids or `--all`, `--all` adopts every molecule in the fixture publisher, `workflow-molecule-already-adopted` refusal when a second workflow molecule is added.
- [X] T064 [P] [US3] Add an integration test in `tests/integration/test_add_non_head_revision.py` that exercises the exact regression from [research.md](./research.md) D3: pin a `--revision=<SHA>` at a non-HEAD commit of a fixture publisher and confirm the manifest.json read succeeds against the fetched-by-SHA object.
- [X] T065 [P] [US3] Add an integration test in `tests/integration/test_add_constitution_already_adopted.py` that exercises the single-constitution rule (per FR-020 and Spec 013 Clarification): `haex add` on a source whose molecule contributes a constitution refuses with `constitution-already-adopted` when `.haex-hive.json` already resolves to another constitution-contributing molecule; the diagnostic names the currently adopted molecule; `.haex-hive.json` is not modified; no `.haex-hive/pending/` directory is written. Recovery via `haex remove <current-id>` followed by a second `haex add` succeeds.

### Implementation for User Story 3

- [X] T070 [US3] Implement `src/haex_hive/install/manifest_lock.py` with `ManifestLockContext` (create-if-absent, `fcntl.flock` on POSIX, `LockFileEx`/`UnlockFileEx` on Windows via `ctypes`). Expose an `acquire(timeout_seconds: float = 30.0)` context manager: bounded-wait acquisition per FR-028 (default 30 s; `0` means fail-fast; positive value polls or blocks with a deadline). On timeout, raise a diagnostic that surfaces as `manifest-lock-contended` at the CLI boundary (exit code 6). The tool MUST NOT try to detect or forcibly break a lock held by a still-running process; kernel-level release on process exit is the sole automatic recovery path. The lock file at `.haex-hive.json.lock` is never renamed or deleted by the tool. Follow the pattern in Spec 008's `writer_lock.py`.
- [X] T071 [US3] Extend `src/haex_hive/cli/install.py` so `install.run(...)` accepts an optional `held_manifest_lock: ManifestLockContext | None = None`. When present, install skips its own manifest-lock acquisition and reuses the passed context. When absent, install acquires the lock itself before reading `.haex-hive.json`. Install-mutex acquisition order stays second per FR-026.
- [X] T072 [US3] Implement `src/haex_hive/install/write_and_reinstall.py` (or extend `install.py`): under the acquired manifest lock, mutate `.haex-hive.json` in memory, write via `.haex-hive.json.tmp` + rename, call `install.run(held_manifest_lock=…)` in-process, roll the manifest edit back on ANY install failure (Spec 013 has no post-install review-pending exception per the 2026-09-04 clarification), and report any rollback-failure recovery path with the lock still held.
- [X] T073 [US3] Implement `src/haex_hive/git/publisher_fetch.py` with `resolve_sha(source_url, revision_or_head)` (runs `git ls-remote`) and `ensure_object(source_url, sha)` (runs `git init` + `git remote add origin` + `git fetch origin <sha> --depth 1` into either the existing publisher clone under `$HAEX_HIVE_STATE/repos/<clone-hash>/` or a `tempfile.TemporaryDirectory()` bare repo). Cover the refusal keys `source-url-invalid` and `revision-not-found` with contextual diagnostics.
- [X] T074 [US3] Implement `src/haex_hive/cli/add.py` per [contracts/haex-add.cli.md](./contracts/haex-add.cli.md). Handle argument parsing (source-url, comma-separated molecule ids, `--revision`, `--all`, `--lock-timeout=<sec>`), TTY-only interactive selection, merge-vs-replace-vs-append logic for the compound entry (deduplicated, lexically sorted `molecules[]` per FR-018 and the 2026-09-04 clarification), workflow-molecule-already-adopted check, constitution-already-adopted check (FR-020: refuse pre-write when the added set introduces a second constitution-contributing molecule), and delegation to `write_and_reinstall`.
- [X] T075 [US3] Add the `publisher-manifest-invalid` refusal path in `src/haex_hive/cli/add.py`: when the fetched publisher `manifest.json` does not validate against the v3 schema (schema violation or `haex_hive_version` is not `"3"`), refuse with `publisher-manifest-invalid`, exit 2, no manifest edit.
- [X] T076 [US3] Wire the `add` subcommand into `src/haex_hive/cli/main.py`. Expose it under `haex add …`. Preserve the existing `migrate`, `constitution`, and `install` subcommands.
- [X] T077 [P] [US3] Update `[project.scripts]` in [pyproject.toml](../../pyproject.toml) — no change expected since `haex = "haex_hive.cli.main:main"` already dispatches subcommands, but verify.
- [X] T078 [US3] Update [quickstart.md](./quickstart.md) if the implementation surfaced any command-line ergonomics not captured in the design (do not weaken the CLI contract in [contracts/haex-add.cli.md](./contracts/haex-add.cli.md); the contract wins on conflict).

**Checkpoint**: US3 fully functional. Adopting an atom is one command; every refusal key produces its documented behavior; concurrency is serialized by the manifest lock.

---

## Phase 6: User Story 4 - `haex remove` retracts a molecule (Priority: P3)

**Goal**: `haex remove <molecule-id>` removes the id from every compound in `.haex-hive.json` and runs `haex install` so orphan files are deleted.

**Independent Test**: on a repo that adopts `com.github.haexmas.atoms.graphify-first-authoring`, run `haex remove com.github.haexmas.atoms.graphify-first-authoring`. Expect the molecule id removed from the compound, orphaned files under `.haex-hive/` deleted per Spec 008 US3, exit 0. Run `haex remove <absent-id>`; expect exit 2 with `unknown-molecule-id` and no manifest edit. Run `haex remove <present>,<absent>`; expect exit 2 (preflight refuses before touching the manifest).

### Tests for User Story 4

- [X] T080 [P] [US4] Add CLI tests in `tests/cli/test_remove.py`: single-id retraction, comma-separated multi-id retraction, empty-compound drop after retraction, `unknown-molecule-id` refusal for absent id, preflight refusal for mixed present/absent request (no manifest edit; every missing id named in the diagnostic).
- [X] T081 [P] [US4] Add an integration test in `tests/integration/test_remove_orphan_deletion.py`: retract a molecule and assert that every file `.haex-hive/install.lock` had listed as `paths` for that molecule is deleted after the ensuing install (per Spec 008 US3), while files from surviving molecules are untouched.
- [X] T082 [P] [US4] Add a CLI test in `tests/cli/test_remove_workflow_fallback.py`: retract the currently adopted workflow molecule and confirm the ensuing install falls back to the bundled `speckit` workflow on the next resolve without any activation step (per Spec 011 amendment FR-008).

### Implementation for User Story 4

- [X] T085 [US4] Implement `src/haex_hive/cli/remove.py` per [contracts/haex-remove.cli.md](./contracts/haex-remove.cli.md). Accept `--lock-timeout=<sec>` (default 30, `0` = fail-fast). Preflight every named molecule id against `.haex-hive.json.compounds[].molecules[]` under the acquired manifest lock. Refuse with `unknown-molecule-id` naming every missing id if any are absent, before any mutation. On success, remove the ids, drop empty compounds, call `write_and_reinstall(…)`.
- [X] T086 [US4] Wire the `remove` subcommand into `src/haex_hive/cli/main.py`. Expose it under `haex remove …`.

**Checkpoint**: US4 fully functional. Retracting a molecule is one command; the preflight preserves "no state change on refusal" for mixed requests; orphan deletion inherits from Spec 008.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: end-to-end confirmation, documentation touch-ups, and follow-up bookkeeping.

- [ ] T090 [P] Run `haex install` against a fresh clone of haex-hive after this PR's changes and assert byte-identical `.haex-hive/install.lock` and `.haex-hive/visibility.json` output between two consecutive runs on unchanged inputs (Spec 008 SC-003 preserved).
- [ ] T091 [P] Add an end-to-end test in `tests/integration/test_atoms_repo_installation.py`: `haex add https://github.com/haexmas/atoms com.github.haexmas.atoms.graphify-first-authoring` against a fixture consumer, then `haex install`, then assert the graphify constitution.md and its accompanying files land under `.haex-hive/` per Spec 007 v3 plus Spec 008. This closes SC-001 (the atoms-repo molecule installs into a v3-adopted consumer through a single call).
- [ ] T092 [P] Regenerate the [quickstart.md](./quickstart.md) walkthrough against the final CLI by running each command block and confirming outputs match the documented expectations; update the doc for any ergonomic drift.
- [ ] T093 [P] Grep for lingering v2 vocabulary across `docs/`, `specs/`, and `src/haex_hive/`: search for `atom-manifest.v2`, `haex-hive.v2`, `contributes:` (in prose about the current tool, not historical docs), and `includes[]` in prose. Replace with v3 equivalents where the reference is about current-tool behavior. Historical spec documents (Specs 001-011) stay unchanged; they describe what was landed at the time.
- [ ] T094 Update memory `haex_hive_pre_user` in the operator's memory index to note that Spec 013 is landed and v3 is the tool's baseline. Follow the existing memory-file format; no code impact.
- [ ] T095 Update `docs/plans/2026-09-02-spec-013-add-cli-and-molecule-rename-design.md` header from `Status: Design preview` to `Status: Landed as Spec 013 on <date>` with a pointer to `specs/013-add-cli-and-molecule-rename/`.

**Checkpoint**: end-to-end flows (self-install + atoms-repo install) verified. Documentation and memory reflect v3 as the tool's current baseline.

---

## Dependencies

**Between phases:**

- Phase 1 (Setup) must complete before Phase 2. The v3 schema files must live under `src/haex_hive/schema/data/` before the model reshaping in Phase 2 references them.
- Phase 2 (Foundational) must complete before Phase 3, 4, 5, 6. Every user story reads at least one reshaped model class.
- Phase 3 (US1) is independent of Phase 4/5/6 once Phase 2 is done. It can proceed in parallel with US2 planning, but US1's self-migration of haex-hive's own manifests (T030–T032) must land before any developer working in the same clone can run `haex install`.
- Phase 4 (US2) is independent of Phase 5 and Phase 6.
- Phase 5 (US3) and Phase 6 (US4) share the manifest-lock helper (T070) and the `write_and_reinstall` helper (T072); US4 can start after those two tasks land. Otherwise US3 and US4 are independent.

**Within a phase:**

- All `[P]` tasks in the same section are parallelizable (different files, no dependency on incomplete tasks in the same phase).
- Tests in each user-story phase (T020–T025, T040–T044, T060–T065, T080–T082) run in parallel with each other and independently of the corresponding implementation tasks (they land in separate files).

## Parallel execution examples

**Phase 1 batch**: T002, T003, T004, T005, T007 all touch different schema files or pyproject.toml sections; run in parallel. T006 (delete v2 schemas) is a single deletion and can also run alongside them.

**Phase 2 batch**: T010, T011, T012, T013, T014, T018 all touch different model files; run in parallel. T015 and T016 share the schema loader; sequence them after the model reshape lands. T017 (constitution resolver) is independent once T011 is done.

**Phase 3 tests batch**: T020, T021, T022, T023, T024, T025 land in six different test files; run in parallel.

**Phase 4 tests batch**: T040, T041, T042, T043, T044 land in five different test files; run in parallel.

**Phase 5 tests batch**: T060, T061, T062, T063, T064, T065 land in six different test files; run in parallel.

**Phase 6 tests batch**: T080, T081, T082 land in three different test files; run in parallel.

**Phase 7 batch**: T090, T091, T092, T093 land in disjoint files or run against a fully-implemented tool; run in parallel.

## Implementation strategy

**MVP path**: Phase 1 + Phase 2 + Phase 3 delivers the smallest viable slice that unblocks holzi (or any other v3 consumer). The v3 tool speaks v3 exclusively, refuses v2 with a migrate hint, and haex-hive's own repo self-installs under v3.

**Incremental delivery**:

1. Ship Phase 1 + Phase 2 + Phase 3 first. This unblocks holzi's `haex install` even without `haex add`/`haex remove` (operators can hand-edit `.haex-hive.json`).
2. Ship Phase 4 (`haex migrate` v2→v3) so downstream consumers on v2 can transition.
3. Ship Phase 5 (`haex add`) so the one-line adoption UX lands.
4. Ship Phase 6 (`haex remove`) as the symmetric counterpart.
5. Ship Phase 7 (polish) once the previous phases are stable.

Each user story is independently testable per its `Independent Test` block. The story-level parallelism (US2 and US3 in particular) reflects real independence: `haex migrate` and `haex add` share no code paths beyond the model and schema layer that Phase 2 fixes.

**Total tasks**: 66 (ID range T001–T095 with intentional numeric gaps to leave room for follow-up sub-tasks discovered during implementation). Setup 7, Foundational 9, US1 12, US2 12, US3 15, US4 5, Polish 6.
