# Tasks: Local (Per-Developer) Molecule Scope

**Input**: Design documents from `/specs/029-local-molecule-scope/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/local-scope-cli.md, quickstart.md

**Tests**: Included. The spec's success criteria (SC-001 to SC-006) are verified by automated tests, following the project rule "leave exactly one runnable check behind for any non-trivial logic".

**Organization**: Grouped by user story. US1 (adopt locally), US2 (local behavior) and US3 (remove) are P1; US4 (provenance) and US5 (fresh clone) are P2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: user story the task belongs to (US1–US5)

## Implementation notes (from reading the install pipeline)

- `constitution/publish._publish_constitution` allocates a new `generation_id` on every project publish, so a local-only change must never trigger a project publish: `.spaex/install.lock` is committed, and changing it would break SC-001/SC-002. Local scope therefore publishes through its own `local_scope.publish_local_generation`, which re-stages every live `.spaex/` file outside `local/` byte-for-byte. The local lock carries its own `generation_id`, allocated from the local seed. This corrects data-model.md ("equals the project lock's generation_id"), which is updated in T003.
- When project scope does change, the project publish carries `.spaex/local/**` through the swap verbatim (T009), and the local publish follows inside the same rollback context. Every local refusal (shadowing, path conflicts, tracked paths, Spec Kit conflict, hook side effects) runs **before** any project publish, so only I/O errors can fail after the project swap. Those errors are covered by the existing `.spaex` rollback context (research R2; `ponytail:` ceiling note for root files written by the project publish).

---

## Phase 1: Setup

- [ ] T001 Add local-scope path helpers `local_dir()`, `local_manifest_path()`, `local_lock_path()`, `local_constitution_path()` and the constants `LOCAL_DIRNAME = "local"`, `LOCAL_RELATIVE_DIR = ".spaex/local"` in `src/spaex/paths.py`
- [ ] T002 [P] Create the schema `src/spaex/schema/data/local-manifest.v1.schema.json`: required `spaex_version` (const `"4"`) and `compounds` (array, may be empty), `additionalProperties: false`, compound items identical to the consumer manifest's compound definition (canonical `source`, 40-hex `revision`, unique non-empty `molecules`, optional `track`, optional `config`)
- [ ] T003 [P] Update `specs/029-local-molecule-scope/data-model.md`: the local lock's `generation_id` is allocated independently from the local seed (see the implementation notes above)

---

## Phase 2: Foundational (blocks every story)

- [ ] T004 Extract compound parsing and serialization from `ConsumerManifest.from_json` / `to_json_bytes` into the module-level functions `parse_compounds(raw)` and `compounds_to_json(compounds)` in `src/spaex/model/consumer_manifest.py`, with no behavior change (existing tests must pass unmodified)
- [ ] T005 Create the `LocalManifest` dataclass (`spaex_version`, `compounds`) with `from_json` (validates against `local-manifest.v1.schema.json`, reuses `parse_compounds`), `to_json_bytes`, and `as_consumer_manifest(identity)` (an in-memory `ConsumerManifest` for the resolver) in `src/spaex/model/local_manifest.py`
- [ ] T006 Add the typed errors `LocalManifestInvalidError` (`local-manifest-invalid`, INCOMPLETE_TRANSACTION), `LocalAdoptionShadowedError` (`local-adoption-shadowed`, VALIDATION_REFUSE), `LocalPathConflictError` (`local-path-conflict`, VALIDATION_REFUSE), `LocalExcludeMalformedError` (`local-exclude-malformed`, VALIDATION_REFUSE) and `LocalHookSideEffectError` (`local-hook-side-effect`, VALIDATION_REFUSE) in `src/spaex/util/errors.py`
- [ ] T007 Implement the per-worktree exclusion block in `src/spaex/install/git_exclude.py`: `exclude_file(repo_root)` (via `git rev-parse --git-path info/exclude`; `None` outside git), `worktree_key(repo_root)` (basename of `git rev-parse --git-dir`), `read_block(...)` (refuses a start marker without an end marker with `LocalExcludeMalformedError`), and `reconcile(repo_root, paths)`, which rewrites only this worktree's sorted, de-duplicated, `/`-anchored block through temp-file plus atomic rename, removes the block when `paths` is empty, and never touches text outside spaex blocks. Include a `ponytail:` note on the shared-across-worktrees ceiling
- [ ] T008 Implement `src/spaex/install/local_scope.py` with:
  - (a) `load_overlay(repo_root)`, returning `LocalManifest | None` and raising `LocalManifestInvalidError` on a bad file;
  - (b) `split_shadowed(project_pins, local_resolved)`, returning the kept local molecules and the shadowed ids;
  - (c) `tracked_paths(repo_root, paths)` (`git ls-files -z --`; an empty set outside git);
  - (d) `preflight(...)`, which refuses local exclusive destinations that are project-owned (project lock paths plus project delivered files) or tracked, and refuses a local `speckit` declaration when project scope has one (`SpeckitDeclarationConflictError`) or a local legacy `atoms.constitution` contribution;
  - (e) `hook_snapshot(repo_root, protected_paths)`, a context that records tracked-file status (`git status --porcelain=v1 -z --untracked-files=no`), bytes of dirty tracked and project-owned files, and the untracked-unignored set (`git ls-files --others --exclude-standard -z`). On exit it refuses changes to tracked or project-owned paths, restoring the pre-hook state via `git checkout -- <clean paths>` and the saved bytes, and returns newly created untracked paths
- [ ] T009 Carry `.spaex/local/**` through the project swap: add `_preserved_local_files(repo_root)` to the `preserved_files` tuple in `src/spaex/cli/install.py` (all regular files under `.spaex/local/`, symlinks skipped)
- [ ] T010 [P] Pass `SPAEX_SCOPE=project|local` to hook subprocesses: add `scope: str = "project"` to `run_install_hook` in `src/spaex/install/hook_runner.py`
- [ ] T011 [P] Unit tests for T004/T005 in `tests/unit/test_local_manifest.py` (round trip, empty compounds, extra key refused, non-canonical source refused, short revision refused) and the schema contract test `tests/contract/test_local_manifest_v1.py`
- [ ] T012 [P] Unit tests for T007 in `tests/unit/test_git_exclude.py`: create block in missing file, update, remove when empty, foreign lines untouched, two worktree keys independent, malformed block refused, non-git repo returns `None`

**Checkpoint**: overlay model, exclusion writer and preflight primitives exist and are tested in isolation.

---

## Phase 3: User Story 1 – Adopt a molecule just for myself (P1) 🎯 MVP

**Goal**: `spaex add --local` installs a molecule's files and hooks for one developer without any change visible to git and without touching project outputs.

**Independent test**: in a git repo with project adoptions, `spaex add --local` a molecule delivering an exclusive file and a hook. Afterwards `git status --porcelain` is empty, `.spaex/manifest.json`, `.spaex/install.lock` and every project file are byte-identical, and the local file exists.

- [ ] T013 [US1] Add `--local` to the `add` subparser in `src/spaex/cli/main.py` and branch in `src/spaex/cli/add.py`: when local, refuse ids pinned in project scope (`LocalAdoptionShadowedError`), mutate the overlay with the existing `_mutate_compounds` logic applied to `LocalManifest` (keep the committed manifest untouched), write it atomically under the manifest lock, reinstall, and restore the previous overlay bytes (or absence) on failure. Print the hook warning text from contracts/local-scope-cli.md for hook-bearing molecules
- [ ] T014 [US1] Implement `build_local_plan(...)` in `src/spaex/install/local_scope.py`:
  - resolve overlay molecules through `resolve_install_inputs(overlay.as_consumer_manifest(identity), state_root)`;
  - split out shadowed ids;
  - collect local exclusive atoms with `collect_exclusive_atoms`;
  - compose local `nix_packages` into `local/generated/nix-packages.json`;
  - run `preflight`;
  - run local hooks after the project hooks via `hook_snapshot` with `scope="local"`, folding newly created paths into the owning molecule's record;
  - run local Spec Kit via `prepare_install(local_resolved, existing_lock=<local lock>)`;
  - build the local `MoleculeEntry` records and `content_hashes`.

  Return a frozen `LocalPlan` (records, staged files, delivered files, shadowed ids, exclusion paths, `is_no_op` compared against the on-disk local lock)
- [ ] T015 [US1] Implement `publish_local_generation(repo_root, plan, state_root)` in `src/spaex/install/local_scope.py`:
  - staged files are every live `.spaex/` file outside `local/` (byte-for-byte, `manifest.json.lock` included), plus `local/manifest.json`, `local/.gitignore` (`*\n`), `local/install.lock` (own generation id via `allocate_generation_id`), `local/generated/**` and the existing `local/constitution.d/**` and `local/constitution.md`;
  - in `post_write_verify`, snapshot and write local delivered files, then run `_delete_orphaned_paths` with the previous and new local locks;
  - when the overlay is empty or absent, stage nothing under `local/`.
- [ ] T016 [US1] Wire the local plan into both branches of `run()` in `src/spaex/cli/install.py`:
  - build the plan after the project Spec Kit step;
  - the no-op path requires both the project and the local plan to be no-ops;
  - when only local differs, call `publish_local_generation` without a project publish;
  - otherwise call it right after `publish_constitution`, inside the same rollback context;
  - print `local: <n> molecule(s) installed` and the `shadowed:` lines from the contract;
  - extend `_preserve_generation_for_behavior` so it is active whenever local scope exists or existed.
- [ ] T017 [US1] Reconcile the exclusion block at the end of every successful `run()` (including no-op paths) from the current local lock plus Spec Kit output paths (`.specify/integrations/<key>.manifest.json` file lists, plus `/.specify/` when local scope created it). On reconcile failure, roll back the generation and the root snapshot before raising (research R7)
- [ ] T018 [P] [US1] Integration test `tests/integration/test_local_scope_add_remove.py::test_add_local_leaves_git_clean_and_project_identical` (git repo via `git_binary`, `haex_add_helpers` publisher with an exclusive-file molecule; asserts `git status --porcelain` is empty, project files byte-identical, local file present, block present in `info/exclude`) and `::test_add_local_twice_is_byte_identical` (SC-004)
- [ ] T019 [P] [US1] Integration tests for refusals in `tests/integration/test_local_scope_refusals.py`: shadowed add, project-owned destination, tracked destination, Spec Kit declared in both scopes, invalid overlay. Each asserts nothing was written and the overlay was restored
- [ ] T020 [P] [US1] Integration test `tests/integration/test_local_hook_side_effects.py`: a local hook that edits a tracked file refuses and restores the file; a hook that creates an untracked file gets it recorded in the local lock and excluded; the hook sees `SPAEX_SCOPE=local`
- [ ] T021 [P] [US1] Crash-safety test `tests/integration/test_local_scope_crash_safety.py` using `SPAEX_CRASH_AFTER`: a crash during the local publish leaves the previous generation recoverable and the next install converges, including the exclusion block

**Checkpoint**: MVP. Local adoption works end to end for files, hooks and Spec Kit.

---

## Phase 4: User Story 2 – Personal behavior rules reach my agent (P1)

**Goal**: local behavior fragments compose into `.spaex/local/constitution.md`; the project constitution stays byte-identical; agents are told to read the local document.

**Independent test**: adopt a behavior-only molecule locally with a stubbed composer; `.spaex/constitution.md` is unchanged, the local document exists with the preamble, and the bootstrap block v3 text mentions it.

- [ ] T022 [US2] Parameterize the behavior output location: add an optional `target: Path | None` to `emit_composed`, `remove_if_exists` and `read_header_hashes` in `src/spaex/behavior/emit.py`, plus an optional `preamble: str` emitted after the header in `emit_composed`. Defaults keep today's bytes exactly
- [ ] T023 [US2] Add `spaex_dir: Path | None = None` and `preamble: str = ""` to `orchestrate.run` in `src/spaex/behavior/orchestrate.py`, threading the directory through `target`/`staging`/`prev`, the clarifications path, the stale path and `_commit_behavior_artifacts`/`_publish_empty_artifacts`. Defaults preserve today's behavior (the existing behavior test suite must pass unmodified)
- [ ] T024 [US2] Run the local behavior pass in `_run_behavior_pipeline` in `src/spaex/cli/install.py` after the project pass: `orchestrate.run(resolved=local_resolved, project_local=(), spaex_dir=.spaex/local, preamble=LOCAL_PREAMBLE)`, with output lines naming `.spaex/local/constitution.md`. Define `LOCAL_PREAMBLE` (text from data-model.md) in `src/spaex/install/local_scope.py`
- [ ] T025 [US2] Bump `BLOCK_VERSION` to `"3"` and extend `BLOCK_BODY` in `src/spaex/behavior/bootstrap.py` with the local-document sentence from research R6. Extend `maybe_emit_no_bootstrap_hint` in `src/spaex/cli/behavior_commands.py` to also hint when `.spaex/local/constitution.md` exists and an installed block is older than version 3
- [ ] T026 [P] [US2] Behavior integration test `tests/behavior/integration/test_local_behavior.py` (stubbed `invoke_composer`): the project constitution is byte-identical with and without the local behavior molecule, the local document has the preamble, `git status` is clean, and a second install reuses the local document (`skipped_composer`)
- [ ] T027 [P] [US2] Update `tests/behavior/unit/test_bootstrap_marker.py` expectations for block version 3 and add a v2→v3 upgrade case

**Checkpoint**: local behavior is active for the developer, invisible to the team.

---

## Phase 5: User Story 3 – Remove a local adoption cleanly (P1)

**Goal**: `spaex remove --local` deletes everything that molecule contributed; removing the last one leaves no `.spaex/local/` and no exclusion block.

**Independent test**: add then remove a local molecule delivering a file, a behavior fragment and a hook-created file; afterwards no local file, no `.spaex/local/`, no `spaex-local` block, project byte-identical.

- [ ] T028 [US3] Add `--local` to the `remove` subparser in `src/spaex/cli/main.py` and branch in `src/spaex/cli/remove.py`: preflight against the overlay (`UnknownMoleculeIdError` with a hint naming `.spaex/local/manifest.json`), apply `_apply_removal` semantics to `LocalManifest`, write it or delete it when empty, then reinstall with restore-on-failure. Without `--local`, an id adopted only locally gets the hint "use --local"
- [ ] T029 [US3] Ensure `publish_local_generation` drops `local/**` entirely and `git_exclude.reconcile` removes the block when the overlay becomes empty, and that the local behavior pass removes `.spaex/local/constitution.md` when no local fragments remain (existing empty-artifact path with `spaex_dir`) in `src/spaex/install/local_scope.py`
- [ ] T030 [P] [US3] Integration tests in `tests/integration/test_local_scope_add_remove.py`: `::test_remove_local_deletes_only_its_files`, `::test_remove_last_local_leaves_no_trace` (SC-005), `::test_remove_without_local_hints_for_local_only_id`

**Checkpoint**: full add/remove lifecycle.

---

## Phase 6: User Story 4 – See which scope everything comes from (P2)

**Goal**: `status`, `trace` and `constitution show` label scope.

**Independent test**: with both scopes populated, `status --format json` shows `"scope"` per molecule and `format_version: 2`; `trace` on a local file names the local owner; `constitution show` prints the local section after the project document.

- [ ] T031 [US4] Read both locks consistently in `src/spaex/report/compose.py`: per-molecule `scope`, the top-level `shadowed` list, per-scope drift (local pins from the overlay versus the local lock), and `format_version` 2. Extend `read_with_consistent_generation` usage to re-check both generation ids
- [ ] T032 [US4] Build owners from both locks with a `scope` per owner in `src/spaex/report/trace.py`; text output appends ` (local)`
- [ ] T033 [US4] Render ` [local]` per local molecule and a `Shadowed:` section in `src/spaex/cli/status.py`
- [ ] T034 [US4] Append `## Local (this checkout only)` and the local document when present in `src/spaex/constitution/show.py`
- [ ] T035 [P] [US4] Update the existing status/trace JSON tests for `format_version: 2` and add `tests/behavior/integration/test_status_local_scope.py` covering scope labels, shadowed listing, trace ownership (SC-006) and constitution show ordering

**Checkpoint**: provenance across scopes.

---

## Phase 7: User Story 5 – Teammates and fresh clones are unaffected (P2)

**Goal**: no overlay means no behavior change at all.

- [ ] T036 [US5] Guard every new code path in `src/spaex/cli/install.py` behind "overlay or local lock exists" so a checkout without local scope makes no extra git calls and stages identical bytes
- [ ] T037 [P] [US5] Integration test `tests/integration/test_local_scope_add_remove.py::test_fresh_clone_ignores_local_scope`: clone the consumer repo after a local add; install in the clone yields byte-identical project files and no `.spaex/local/`; and `::test_no_overlay_install_is_byte_identical_to_baseline` (SC-002)

---

## Phase 8: Polish & cross-cutting

- [ ] T038 [P] Document local scope in `README.md` (commands, what stays out of git, older-version caveat) and `docs/install-hooks.md` (`SPAEX_SCOPE`, local hook side-effect checks)
- [ ] T039 [P] Set ADR 0027 status to Accepted in `docs/adr/0027-local-molecule-scope.md`, adding the independent local generation id to its Consequences
- [ ] T040 Run `pytest -q`, `ruff check .`, `mypy src`; walk through `specs/029-local-molecule-scope/quickstart.md` against a real consumer repo and record the result in the PR

---

## Dependencies & execution order

- Setup (T001–T003) → Foundational (T004–T012) → US1 (T013–T021) → US2, US3 (can proceed in parallel once T016 lands) → US4 → US5 → Polish.
- US2 depends on T009/T016 (local files carried through publishes). US3 depends on T013–T015. US4 depends on the local lock existing (T015). US5 checks are regression guards over all earlier work.

## Parallel opportunities

- T002, T003 in Setup; T010, T011, T012 in Foundational.
- Within US1: tests T018–T021 are independent files.
- T026/T027 (US2 tests) and T030 (US3 tests) in parallel after their implementation tasks.

## Implementation strategy

MVP is Phase 1–3 (US1): local files, hooks and Spec Kit stay out of git. US2 is the most common real use (personal behavior rules) and directly follows. Everything ships in one implementation PR, as agreed with the operator; the commits are grouped per phase to keep review manageable.
