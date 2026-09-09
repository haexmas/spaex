---
description: "Task list for Spec 016 — Molecule install-hooks in spaex install"
---

# Tasks: Molecule install-hooks in `spaex install`

**Input**: Design documents from `/specs/016-molecule-install-hooks/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Checkbox freshness is load-bearing.** Tick each task's checkbox in the same commit as the task's output — or at the latest in the next commit, before starting the next task. See [ADR 0004](../../docs/adr/0004-eager-checkbox-update-rule.md).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing. Priority order from spec.md: P1 (US1) → P2 (US2) → P3 (US3, US4). Foundational infrastructure precedes all stories.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 / US4 for story-phase tasks; absent for setup/foundational/polish tasks
- Every task cites its exact file path(s)

---

## Phase 1: Setup

**Purpose**: Verify baseline before touching code.

- [x] T001 Verify branch `016-molecule-install-hooks` is at `origin/main` HEAD in worktree `~/Projekte/spaex-016`; capture pre-implementation baseline test count via `pytest --collect-only -q | tail -3` and record in a note for later diff. Baseline: 367/376 collected (9 deselected), branch `016-implement` at origin/main HEAD, recorded 2026-09-09.

---

## Phase 2: Foundational (blocking prerequisites for all user stories)

**Purpose**: Schema extension, dataclass, parser, resolver plumbing, path-containment helper, hook-runner module. NO user story work begins until this phase completes.

### Schemas

- [x] T002 [P] Extend `src/spaex/schema/data/molecule-manifest.v4.schema.json` with the optional `install_hook` object property per [contracts/molecule-manifest-v4-install-hook.schema.json](./contracts/molecule-manifest-v4-install-hook.schema.json). Preserve `additionalProperties: false` on the manifest root and on the hook object. Verifies FR-001.
- [x] T003 [P] Extend `src/spaex/schema/data/install-lock.v4.schema.json` with optional `hook_status` enum (`"ok" | "failed" | "skipped"`) on the per-molecule record per [contracts/install-lock-v4-hook-status.schema.json](./contracts/install-lock-v4-hook-status.schema.json). Verifies FR-020.
- [x] T004 [P] Add contract-level schema tests in `tests/contract/test_molecule_manifest_install_hook_schema.py`: accept min form (interpreter + script), accept full form (with args + on_failure), reject missing interpreter, reject missing script, reject unknown top-level keys under install_hook, reject non-object install_hook (string, null, array, number, boolean), reject on_failure outside `{abort, warn}`, backwards-compat (manifest without install_hook stays valid). Verifies FR-001 through FR-004, SC-006.
- [x] T005 [P] Add contract-level schema tests in `tests/contract/test_install_lock_hook_status_schema.py`: accept "ok"/"failed"/"skipped", accept absent, reject unknown values, backwards-compat (existing lock records without hook_status stay valid). Verifies FR-020 through FR-023.

### Model layer

- [x] T006 Create `InstallHook` dataclass (frozen, slots) in `src/spaex/model/molecule_manifest.py`: fields `interpreter: str`, `script: str`, `args: tuple[str, ...]` (immutable), `on_failure: Literal["abort", "warn"]`. No behaviour methods, pure value type. Verifies data-model.md § InstallHook.
- [x] T007 Update `MoleculeManifest.from_json()` in `src/spaex/model/molecule_manifest.py`: parse optional `install_hook` field into `InstallHook | None`. When `install_hook` object is present but omits `on_failure`, EXPLICITLY set `on_failure="abort"` in Python (do NOT rely on the JSON-Schema `default`). When `args` is omitted, use `()`. When top-level `install_hook` is absent, store `None`. Verifies FR-005, FR-006.
- [x] T008 [P] Add unit tests in `tests/unit/test_manifest_install_hook_parser.py`: absent field → None; present min form → dataclass with on_failure="abort" explicitly (do NOT rely on JSON-Schema default; test uses a stub parser to prove the parser sets the value); present with all fields → dataclass with all fields; parses `args` as tuple (immutable). Verifies FR-005, FR-006.

### Resolver

- [x] T009 Extend `src/spaex/constitution/resolve.py::resolve_constitution_contributions` (or replace it with an equivalent result type) so the install path receives the complete resolved-molecule collection, not only constitution contributions: (a) introduce `ResolvedMolecule` with `molecule_id: str`, `source_url: str`, `revision: str`, `repo_dir: Path`, `molecule_path: str`, `install_hook: InstallHook | None`, and `effective_priority: int`, retaining existing constitution contributions for publication (per data-model.md's 2026-09-09 amendment — `repo_dir`/`molecule_path` replace the earlier, incorrect assumption of a pre-populated `cache_dir`; Spec 017's `molecule_store.get_or_extract()` lands 2026-09-08/09 and is what actually materializes a molecule's tree, on demand, from these two fields plus `source_url`/`revision`); (b) compute `effective_priority` as the consumer's `compounds[].config[<molecule-id>].priority` override if present, else the publisher's `manifest.priority`; (c) ensure the resolver emits a `ResolvedMolecule` for EVERY selected molecule, including molecules whose manifest declares NO `atoms.constitution` — this resolver already computes `repo_dir` (from `clone_dir()`) and `publisher_entry.path` per iteration; expose both on the record instead of discarding them once the constitution-body read is done. Verifies FR-007, FR-008.
- [x] T010 [P] Add unit tests in `tests/unit/test_resolver_hook_only_molecule.py`: resolver returns record for hook-only molecule (no atoms.constitution); resolver exposes every FR-008 field with canonical source and lowercase full revision; hook-only record construction does not call the store; effective_priority reflects consumer override when present. Preserve existing constitution-contribution behavior. If Spec 017's resolver migration lands first, its independent content-read extraction remains permitted per data-model.md. Verifies FR-007, FR-008.

### Path containment helper

- [x] T011 [P] Create `src/spaex/util/path_containment.py` exposing `canonicalise_within(root: Path, candidate: Path) -> Path`: raises `PathEscapeError` when the canonicalised candidate (symlinks followed, `..` resolved) is not a descendant of the canonicalised `root`. Never follows into `root`'s parent. Returns the canonical target on success. Verifies FR-014, FR-015.
- [x] T012 [P] Add unit tests in `tests/unit/test_path_containment.py`: descendant path returns canonical target; symlink pointing outside root raises; `..` segment resolving inside root allowed; `..` segment escaping root raises; symlink chain that stays inside root allowed; broken symlink raises. Verifies FR-014, FR-015.

### Hook runner

- [x] T013 Create `src/spaex/install/hook_runner.py` exposing `run_install_hook(resolved: ResolvedMolecule, consumer_repo_root: Path, state_root: Path) -> HookOutcome`: (a) call `shutil.which(resolved.install_hook.interpreter)` — missing → `HookOutcome.LAUNCH_FAILURE` with reason `interpreter_not_on_path`, WITHOUT calling `get_or_extract()` first; (b) call `spaex.git.molecule_store.get_or_extract(resolved.repo_dir, resolved.source_url, resolved.revision, resolved.molecule_path, state_root)` to obtain `molecule_dir` — a `MoleculeTreePathNotFoundError` or `MoleculeTreeExtractionError` → `HookOutcome.LAUNCH_FAILURE` with reason `molecule_tree_unavailable`; (c) canonicalise `molecule_dir / resolved.install_hook.script` with T011's `canonicalise_within()` and require a strict descendant of the canonical `molecule_dir` on EVERY invocation, including store cache hits. An escaping or unresolvable script target → `HookOutcome.LAUNCH_FAILURE` with reason `path_containment_failure`; (d) build argv `[interpreter, str(target), *install_hook.args]` using the returned canonical target; (e) call `subprocess.run(argv, cwd=consumer_repo_root, check=False)` with NO `capture_output=True`, NO `env=` override (inherits complete env per FR-013), and NO `stdin=` override; (f) on process-launch `OSError` → `HookOutcome.LAUNCH_FAILURE` reason `process_launch_oserror`; (g) catch `KeyboardInterrupt` raised while waiting for `subprocess.run` and return `HookOutcome.INTERRUPTED` with reason `interrupted`; (h) on returncode != 0 → `HookOutcome.NONZERO_EXIT` with the code; (i) on returncode == 0 → `HookOutcome.OK`. All non-OK outcomes are subject to the configured `on_failure` policy. Extraction validation is retained by Spec 017, but it does not replace the execution-time molecule boundary (see plan.md's amendment). Verifies FR-009 (partially: runner is called after atoms), FR-012 through FR-015.
- [x] T014 [P] Add tests in `tests/unit/test_hook_runner.py`: subprocess called with correct argv (canonical script target), explicit consumer-root `cwd`, and no env override; store receives the record's `repo_dir`, `source_url`, `revision`, `molecule_path` and the installation `state_root`; missing interpreter → LAUNCH_FAILURE/interpreter_not_on_path without calling the store; either typed store error → LAUNCH_FAILURE/molecule_tree_unavailable; escaping or broken script symlink → LAUNCH_FAILURE/path_containment_failure without launching a subprocess; internal symlink → OK with the canonical target in argv; process-launch `OSError` → LAUNCH_FAILURE/process_launch_oserror; `KeyboardInterrupt` → INTERRUPTED/interrupted; nonzero exit → NONZERO_EXIT with code; zero exit → OK. Mock store calls for these cases. Also add a real-store regression in the same file: materialize sibling and molecule trees from a pinned bare-repo fixture where `mol/install.py -> ../sibling/install.py`; verify the runner refuses that escape both immediately after extraction and on a cache hit. Verifies FR-012 through FR-015.

### install.lock writer/reader

- [x] T015 Extend the install.lock model/writer in `src/spaex/model/install_lock.py` and `src/spaex/constitution/publish.py`: serialise optional `hook_status: Literal["ok", "failed", "skipped"] | None` on each per-molecule record. Emit the field ONLY when the molecule declares `install_hook` in the pinned revision. Verifies FR-020 through FR-023, data-model.md § install.lock per-molecule record. (Model writer done in this commit; publish.py plumbing to propagate hook_status from the resolved-molecule map lands with T017 wiring.)
- [x] T016 [P] Extend the install.lock reader in `src/spaex/model/install_lock.py` to parse the optional `hook_status` field: unknown value → schema-validation error via existing lock schema check; absent → None on the parsed record. Verifies backwards-compat SC-006.

**Checkpoint**: Foundation ready. User story implementation can begin.

---

## Phase 3: User Story 1 — Hook runs on adopt (Priority P1) 🎯 MVP

**Story goal**: A molecule author declares `install_hook`; consumer runs `spaex add` and the hook runs after atoms materialise, produces a real side effect in the consumer repo, and install.lock records `hook_status: "ok"`.

**Independent test**: [quickstart.md](./quickstart.md) sections 1-3 (the graphify-out gitignore round-trip). Verifies AS1, AS2, AS3.

**Suggested MVP scope**: Land Phase 1-3 as an initial merge; Phases 4-6 can follow in the same PR or a stacked PR.

### Wiring

- [x] T017 [US1] Wire hook execution into `src/spaex/cli/install.py::run`: update the resolver result consumed by `run` to include ALL resolved molecules (including hook-only molecules), remove or replace the existing single-constitution-molecule guard, and after ALL atoms materialise into the Spec-008 staging generation iterate the collection in ascending `effective_priority` then ascending UTF-8 molecule-ID. For each record with `install_hook != None`, call `hook_runner.run_install_hook(record, consumer_repo_root=repo_root, state_root=state_root)` and collect outcomes into a per-molecule status map. Do NOT invoke `publish_constitution()` (or its Spec-008 generalisation) until hook execution completes. Verifies FR-009, FR-010, FR-011. (MVP: hook-only molecules are refused with install-failed; support lands with US4 T037. Full per-molecule on_failure policy lands with US2 T023-T024; MVP treats every non-OK outcome as an abort.)
- [x] T018 [US1] Translate `HookOutcome` values into `hook_status` field values written to install.lock (via T015 writer). For US1 default policy (`on_failure="abort"`), OK → `hook_status: "ok"`. Non-OK outcomes are handled in US2 phase. Verifies FR-021.

### Integration tests

- [x] T019 [P] [US1] Add integration test in `tests/integration/test_install_hook_execution.py::test_hook_runs_after_atoms_and_writes_marker` (AS1): fixture publisher molecule with install_hook script appending `graphify-out/` to `.gitignore`; consumer runs `spaex add`; assert `.gitignore` contains line exactly once, `.spaex/constitution.md` present, `.spaex/install.lock` has `hook_status: "ok"`. Verifies FR-009, FR-021.
- [x] T020 [P] [US1] Add integration test `::test_hook_is_idempotent_on_second_install` (AS2): run install twice; assert `.gitignore` line still exactly once (no duplicate), hook_status stays `"ok"`. Verifies FR-024.
- [x] T021 [P] [US1] Add integration test `::test_hook_interactive_prompt_via_pty` (AS3): use `pexpect` or `pty` fixture to attach a pseudo-TTY; hook script calls `input()`; assert prompt appears, typed answer reaches the hook. Skip on Windows CI if needed. Verifies FR-013 stdio-inheritance in TTY.
- [x] T022 [P] [US1] Add integration test `::test_hook_eoferror_in_non_tty_env` (edge case documented in spec § Edge Cases): stdin piped from `/dev/null`; hook calls `input()`; expect EOFError; molecule-author's fallback (default_yes) proves flow completes. Verifies interactive-prompt Assumption.

**Checkpoint**: US1 fully implemented and tested. This is the MVP — landable independently.

---

## Phase 4: User Story 2 — Failure policy per molecule (Priority P2)

**Story goal**: `on_failure: "abort"` triggers Spec-008 rollback on any hook failure. `on_failure: "warn"` records `hook_status: "failed"` in install.lock, continues, CLI exits 0.

**Independent test**: [quickstart.md](./quickstart.md) section 5 (both abort AND warn variants). Verifies AS1, AS2, AS3.

### Abort semantics

- [x] T023 [US2] Wire `on_failure="abort"` in the hook orchestration (T017 wiring): on non-OK `HookOutcome` from any molecule with `on_failure="abort"`, halt further hook execution AND trigger the Spec-008 install-transaction rollback path: discard staged atoms, do NOT write install.lock, revert delegated `.spaex.json` compound-entry update (from `spaex add`); raise the existing `install-failed` diagnostic (at `src/spaex/cli/install.py:232`) with `context={"molecule_id": <id>, "hook_failure": <reason>}`. Verifies FR-016, FR-017.

### Warn semantics

- [x] T024 [US2] Wire `on_failure="warn"` in the hook orchestration: on non-OK `HookOutcome` from a molecule with `on_failure="warn"`, DO NOT halt; record `hook_status="failed"` for that molecule; continue with the next molecule; after all hooks complete, publish install.lock and swap the staged generation as normal; CLI exits 0. Emit ONE post-exit line to stderr: `WARN: molecule <id> install_hook failed (<reason>)`. MUST NOT prefix any of the hook's own inherited stderr lines with `WARN:`. Verifies FR-018, FR-019, FR-022.

### Integration tests

- [x] T025 [P] [US2] Add integration test in `tests/integration/test_install_hook_failure_policy.py::test_abort_rolls_back_transaction` (AS1): fixture molecule with `on_failure="abort"` and script that exits 1; `spaex add`; assert the managed `.spaex/` directory and `.spaex.json` are unchanged from pre-add state (byte-for-byte compare); do not require external hook side effects to roll back; CLI exits non-zero; diagnostic key is `install-failed` with molecule id in context. Verifies FR-016, FR-017, SC-003.
- [x] T026 [P] [US2] Add integration test `::test_warn_continues_with_hook_status_failed` (AS2): fixture molecule with `on_failure="warn"` and script that exits 1; `spaex add`; assert atoms materialised, install.lock has `hook_status: "failed"` for that molecule, ONE `WARN:` line appears on stderr after process exits, CLI exits 0. Verifies FR-018, FR-019, FR-022, SC-004.
- [x] T027 [P] [US2] Add integration test `::test_missing_interpreter_treated_per_on_failure` (AS3): fixture molecule with `install_hook.interpreter = "nonexistent-interpreter-xyz"`; run once with `on_failure="abort"` (rollback), once with `on_failure="warn"` (continue with hook_status=failed, reason=interpreter_not_on_path). Verifies FR-016 (any launch failure) + FR-022 hook_status=failed for launch-failure category.
- [x] T028 [P] [US2] Add integration test `::test_stderr_not_prefixed_with_warn` (FR-019 specific): fixture molecule whose script writes distinctive stderr lines before exiting 1 with `on_failure="warn"`; capture spaex' stderr; assert the hook's own stderr lines appear verbatim (no `WARN:` prefix); ONE post-exit summary `WARN:` line exists. Verifies FR-019.

**Checkpoint**: US2 complete. Failure policy is expressive and testable.

---

## Phase 5: User Story 3 — Global `--no-install-hooks` opt-out (Priority P3)

**Story goal**: Consumer can globally skip all install-hooks for one invocation via `--no-install-hooks` on `spaex add` and `spaex install`. install.lock records `hook_status: "skipped"`.

**Independent test**: [quickstart.md](./quickstart.md) section 4. Verifies AS1, AS2.

### CLI plumbing

- [x] T029 [P] [US3] Add `--no-install-hooks` boolean flag to `spaex install` CLI in `src/spaex/cli/install.py`. Follows the existing argparse pattern. No short form, no inverse flag. Threaded through to the install orchestration layer (T017) as a `skip_hooks: bool` parameter. Verifies FR-026.
- [x] T030 [P] [US3] Add `--no-install-hooks` boolean flag to `spaex add` CLI in `src/spaex/cli/add.py`. When set, propagate through to the internal `spaex install` invocation (same `skip_hooks: bool` parameter). Verifies FR-027.
- [x] T031 [US3] In hook orchestration (T017): when `skip_hooks=True`, DO NOT call `hook_runner.run_install_hook()`; instead record `hook_status="skipped"` for every `ResolvedMolecule` with `install_hook != None`; continue publishing atoms and install.lock as normal. Verifies FR-023, FR-026, FR-028.

### Integration tests

- [x] T032 [P] [US3] Add integration test in `tests/integration/test_install_hook_opt_out.py::test_no_install_hooks_skips_execution` (AS1): fixture molecule with a marker-writing hook; `spaex add --no-install-hooks`; assert marker file NOT created, atoms materialised, install.lock has `hook_status: "skipped"`, CLI exits 0. Verifies FR-026, FR-023.
- [x] T033 [P] [US3] Add integration test `::test_no_install_hooks_is_per_invocation` (AS2): run `spaex add --no-install-hooks` then run `spaex install` WITHOUT the flag; assert second run executes the hook (marker file appears), install.lock hook_status flips from "skipped" to "ok". Verifies FR-028.
- [x] T034 [P] [US3] Add integration test `::test_no_install_hooks_via_spaex_add_propagates` (FR-027 specific): `spaex add --no-install-hooks`; assert the internal install did NOT invoke hooks (verified by absence of marker file + hook_status=skipped). Verifies FR-027.

**Checkpoint**: US3 complete. Opt-out flag works on both commands with correct propagation and non-persistence.

---

## Phase 6: User Story 4 — Multi-molecule order + hook-only molecules (Priority P3)

**Story goal**: When multiple molecules with hooks are installed, they execute in a deterministic order (ascending effective priority, ties broken by UTF-8 molecule-ID). Hook-only molecules (no atoms.constitution) survive the resolver and their hooks run.

**Independent test**: publish two molecules with hooks and priorities 10 and 20 whose scripts append distinct lines to a shared log file; adopt both; verify log order. Verifies AS1, AS2, AS3.

- [x] T035 [US4] Verify hook orchestration (T017) uses the exact sort key `(effective_priority, molecule_id.encode("utf-8"))` ascending. If T017 already uses this — no code change; add a comment referencing FR-010 for future readers. Verifies FR-010. (Docstring in `_run_hooks` in cli/install.py cites FR-010 and points at the resolver's canonical sort key.)
- [x] T036 [P] [US4] Add integration test in `tests/integration/test_install_hook_multi_molecule.py::test_priority_order_execution` (AS1): fixture two molecules, priorities 10 and 20; hooks each append `<molecule_id>\n` to `<consumer>/hook-log.txt`; run install; assert log's line order is molecule-with-priority-10 before molecule-with-priority-20. Verifies FR-010.
- [x] T037 [P] [US4] Add integration test `::test_hook_only_molecule_hook_runs` (AS2): fixture molecule whose manifest declares `install_hook` but has NO `atoms.constitution`; adopt; assert hook ran (marker file present), install.lock has a record for this molecule with `hook_status: "ok"`. Verifies FR-007. (Guard `_refuse_hook_only_in_mvp` and its call site removed; hook-only molecules land as `MoleculeEntry(paths=(), hook_status=...)` records via the extended `publish_constitution`.)
- [x] T038 [P] [US4] Add integration test `::test_abort_stops_later_hooks_total_rollback` (AS3): fixture three molecules with hooks; the middle one (by priority) has `on_failure="abort"` and exits 1; adopt all three; assert the third molecule's hook did NOT run, ALL atoms rolled back (no `.spaex/` writes), `.spaex.json` compound entries NOT added. Verifies FR-016, FR-025 (integration of rollback with multi-molecule ordering).

**Checkpoint**: US4 complete. Multi-molecule and hook-only cases are correct and tested.

---

## Phase 7: Hook-only transaction (idempotency + FR-025)

**Purpose**: Support the "atom bytes unchanged but hook_status changed" case with a hook-only install.lock generation.

- [X] T039 In `src/spaex/cli/install.py::run`, defer `_is_no_op_single_source(...)` and all no-op returns until AFTER every enabled hook has run and the newly-computed `hook_status` map has been compared with the current install.lock's map. If atom bytes are unchanged AND hook_status map is unchanged → clean no-op (do NOT publish a new generation). If atom bytes are unchanged BUT hook_status map differs → publish a new install.lock generation containing only the hook_status delta (no atom file rewrites). If atom bytes changed → normal generation publish (regardless of hook_status). Verifies FR-025. (Unified `_is_no_op(repo_root, expected_body, expected_records)` replaces the old `_is_no_op_single_source`/`_is_no_op_empty` split; contributor + hook-only records are compared as one sorted molecule map against the on-disk lock. Pre-hook staging now decides on body match alone, so the no-op comparison is done exactly once, post-hook.)
- [X] T040 [P] Add integration test in `tests/integration/test_install_hook_idempotency.py::test_hook_only_transaction_publishes_new_generation`: run `spaex install` once (hook_status=ok); keep the pinned molecule script and atom bytes unchanged, then use an external fixture-controlled condition such as an environment variable or consumer marker to make the hook exit 1 with `on_failure=warn`; run `spaex install` again (atom bytes unchanged; hook_status flips to failed); assert a new install.lock generation was published with the changed hook_status. The test MUST NOT mutate the pinned molecule cache. Verifies FR-025.
- [X] T041 [P] Add integration test `::test_full_no_op_when_atoms_and_hook_status_unchanged`: run `spaex install` twice with no changes anywhere; assert the second run does NOT publish a new generation (verify by comparing install.lock generation ID or mtime). Verifies FR-025.

---

## Phase 8: `spaex remove` interaction

- [ ] T042 In `src/spaex/cli/remove.py`, when removing a molecule whose install.lock record has `hook_status` present (indicating the molecule declared `install_hook` in the pinned revision), emit a WARN to stderr: `WARN: molecule <id> had an install_hook; side effects (git hooks, gitignore entries, provisioned tools, agent-harness registrations) may remain. Consult the molecule's README for reverse steps.` Do NOT change the CLI exit code. Verifies FR-029.
- [ ] T043 [P] Add integration test in `tests/integration/test_install_hook_remove_warn.py::test_remove_hook_carrying_molecule_emits_warn`: after installing a hook-carrying molecule, run `spaex remove`; assert stderr contains the WARN line with the molecule id; CLI exits 0. Verifies FR-029.
- [ ] T044 [P] Add integration test `::test_remove_hook_less_molecule_no_warn`: after installing a molecule WITHOUT install_hook, run `spaex remove`; assert stderr does NOT contain any install_hook-related WARN. Verifies FR-029 specificity (WARN only when appropriate).

---

## Phase 9: Polish & cross-cutting

- [ ] T045 Bump spaex version in `pyproject.toml`: `4.0.1.dev0` → `4.1.0`. Verifies plan.md § Summary version bump.
- [ ] T046 [P] Update `spaex install --help` and `spaex add --help` argparse text to document `--no-install-hooks`. File: `src/spaex/cli/install.py` and `src/spaex/cli/add.py`.
- [ ] T047 [P] Update the `description` fields inside `molecule-manifest.v4.schema.json`'s new `install_hook` property (and its sub-properties) to mention non-reversibility and interactive-prompt semantics for reviewers who read the schema directly. File: `src/spaex/schema/data/molecule-manifest.v4.schema.json`.
- [ ] T048 [P] Add or update a section in `README.md` (or create `docs/install-hooks.md`) documenting: how a molecule author declares `install_hook`, the four failure kinds spaex distinguishes (nonzero exit, missing interpreter, path containment, OSError launch), the `--no-install-hooks` opt-out, the idempotency contract, the non-reversibility limitation. Cross-reference [spec.md](./spec.md) and [design doc](../../docs/plans/2026-09-08-spec-016-molecule-install-hooks-design.md).
- [ ] T049 Manual verification: run [quickstart.md](./quickstart.md) sections 1-5 end-to-end against the built implementation in a scratch directory. Confirm every "Expected output" and every assertion matches. Fix any drift between quickstart and implementation before merge.
- [ ] T050 Verify SC-006 (backwards-compat): run schema validation of the extended `molecule-manifest.v4.schema.json` against `~/Projekte/haex-hive-atoms/graphify-first-authoring/manifest.json` (pre-1.0.3, no install_hook) AND `~/Projekte/haex-hive-atoms/speckit-session-hopper/manifest.json` (no install_hook). Both MUST pass. Also validate the extended `install-lock.v4.schema.json` against a locally-generated pre-Spec-016 install.lock (e.g. from any spaex 4.0.x install snapshot in scratch). All existing shapes MUST pass.
- [ ] T051 Compare test count against T001 baseline: expect at least ~25 new tests across integration + unit + contract layers. If significantly lower, review whether user-story acceptance scenarios are all covered.
- [ ] T052 Sync CHANGELOG.md (if the repo has one; grep first). Add a `4.1.0` entry summarising: new optional `install_hook` field, `--no-install-hooks` opt-out flag, `hook_status` in install.lock, `spaex remove` WARN for hook-carrying molecules, non-reversibility limitation.

**Final checkpoint**: All phases complete, all checkboxes ticked in their corresponding commits, `pytest` green, `spaex install` continues to work for molecules without `install_hook` (backwards-compat).

---

## Dependencies (story completion order)

```text
Phase 1 (Setup, T001)
   ↓
Phase 2 (Foundational, T002-T016)
   ↓
Phase 3 (US1, T017-T022)     ← MVP: landable independently
   ↓ (US1 wiring is reused by later stories)
Phase 4 (US2, T023-T028)     ← extends the wiring with on_failure policy
Phase 5 (US3, T029-T034)     ← adds CLI flag; can run in parallel with Phase 4 after T017
Phase 6 (US4, T035-T038)     ← multi-molecule + hook-only; can run in parallel with Phases 4/5 after T017
   ↓
Phase 7 (Idempotency, T039-T041)   ← needs T017 + T023/T024 wiring
Phase 8 (spaex remove, T042-T044)  ← needs T015 install.lock writer/reader; independent of US1-4 wiring
Phase 9 (Polish, T045-T052)        ← last; depends on everything above
```

## Parallel execution opportunities

Within Phase 2 (foundational), the following tracks can run in parallel because they touch different files:

- **Schema track**: T002 (molecule-manifest), T003 (install-lock), T004 (schema tests), T005 (lock tests) — all `[P]`, no cross-dependencies.
- **Model track**: T006 (dataclass) → T007 (parser) → T008 (parser tests). Sequential within track; parallel to schema track.
- **Path-containment track**: T011 → T012. Independent helper and tests; T013 depends on T011.
- **Hook-runner track**: T013 → T014. Depends on T006 (dataclass), T009 (resolved record), T011 (execution-time containment), and Spec 017's `molecule_store.get_or_extract()` (merged 2026-09-09, no longer an in-repo task this spec needs to build). Once these prerequisites land, parallel to install.lock track (T015-T016).

Within each user story phase, tests (T019-T022, T025-T028, T032-T034, T036-T038, T040-T041, T043-T044) are marked `[P]` and can run concurrently because each test file is independent. Wiring tasks (T017, T023-T024, T029-T031, T035, T039, T042) are sequential within their phase because they modify shared install orchestration.

## Implementation strategy

**MVP-first**: Land Phase 1-3 as one merge. Verify with the quickstart's US1 walk-through against a real consumer repo. Only then start Phase 4+.

**Story-by-story delivery**: Each user story is independently testable (see the per-phase "Independent test" clauses). If the PR gets too big, split at story boundaries — US1 is the load-bearing MVP; US2/US3/US4 can follow in stacked PRs.

**Post-implementation** (out of this task list, in a follow-up PR against haexmas/atoms):
- Bump `graphify-first-authoring` 1.0.2 → 1.0.3 with the `install_hook` field pointing at existing install.py. atoms PR against protected main.
- Once atoms 1.0.3 SHA is known, in each of haex-crdt/specifyr/holzi: `spaex add --revision <new-sha>` in existing PR branches. Manual gitignore commits from 2026-09-08 become redundant (idempotent, harmless; can be removed in a follow-up).

## Format validation

Every task above follows the `- [ ] TID [P?] [USn?] Description with file path` format:

- ✅ Checkbox `- [ ]` starts every line.
- ✅ Task IDs are sequential (T001..T052).
- ✅ `[P]` markers appear only on parallelisable tasks (different files, no dependencies on incomplete tasks).
- ✅ `[US1]` / `[US2]` / `[US3]` / `[US4]` labels appear only on user-story-phase tasks (Phase 3-6); absent on Setup (Phase 1), Foundational (Phase 2), and Polish/Cross-cutting (Phase 7-9).
- ✅ Every description cites at least one exact file path.
