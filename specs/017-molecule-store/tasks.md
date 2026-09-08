---
description: "Task list for Spec 017 — Molecule tree materialization store"
---

# Tasks: Molecule tree materialization store

**Input**: Design documents from `/specs/017-molecule-store/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Checkbox freshness is load-bearing.** Tick each task's checkbox in the same commit as the task's output — or at the latest in the next commit, before starting the next task. See [ADR 0004](../../docs/adr/0004-eager-checkbox-update-rule.md).

**Organization**: Tasks are grouped by user story. Priority order from spec.md: P1 (US1 core materialization, US3 safety — tightly coupled, share the same underlying validation logic) → P2 (US2 concurrency, US4 constitution-resolve migration).

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 / US4 for story-phase tasks; absent for setup/foundational/polish tasks
- Every task cites its exact file path(s)

---

## Phase 1: Setup

- [ ] T001 Verify branch `017-molecule-store` is at `origin/main` HEAD in worktree `~/Projekte/spaex-017-impl`; capture pre-implementation baseline test count via `pytest --collect-only -q | tail -3` for later comparison.

---

## Phase 2: Foundational (blocking prerequisites for all user stories)

**Purpose**: The core `get_or_extract` capability, including its path-containment validation, MUST exist and work correctly before any user story's tests can meaningfully run — FR-010 through FR-013's safety checks are not an optional add-on layered onto a separately-working happy path; they run on every extraction, always (per `contracts/tar-member-validation.md`). This phase implements the whole capability; later story phases add story-focused test coverage against it.

### Error types

- [ ] T002 [P] Add `MoleculeTreeExtractionError` to `src/spaex/util/errors.py` per [data-model.md § MoleculeTreeExtractionError](./data-model.md): `diagnostic_key = "molecule-tree-extraction-failed"`, `exit_code = exit_codes.IO_REFUSE`, hint text per data-model.md. Follow the existing `HaexError` subclass shape (see `PinnedRevisionNotFoundError` for the pattern to match).
- [ ] T003 [P] Add `MoleculeTreePathNotFoundError` to `src/spaex/util/errors.py` per [data-model.md § MoleculeTreePathNotFoundError](./data-model.md): `diagnostic_key = "molecule-tree-path-not-found"`, `exit_code = exit_codes.IO_REFUSE`, and the hint text specified there. It MUST be a different type from `MoleculeTreeExtractionError` per [contracts/get-or-extract.md](./contracts/get-or-extract.md)'s failure mapping and FR-004. Follow the existing `HaexError` subclass shape.

### Path-containment validation (the algorithm from contracts/tar-member-validation.md)

- [ ] T004 Create `src/spaex/git/molecule_store.py` with a private validation function (e.g. `_validate_and_extract(tar: tarfile.TarFile, destination: Path) -> None`) implementing the full algorithm in [contracts/tar-member-validation.md](./contracts/tar-member-validation.md): per-member, in archive order — (1) normalize and reject `..`-escaping paths (FR-010), (2a) reject symlink/hardlink members with an absolute `linkname` unconditionally (FR-011, 2026-09-08 clarification), (2b) resolve relative `linkname` against the member's own directory and reject if it escapes `destination` (FR-011 base case), (3) track established-safe ancestor paths in archive order and reject any member whose ancestor chain passes through a rejected or unvalidated-link component (FR-012, defeats the chained/sandwich escape from spec.md User Story 3 AS3). On any single-member rejection, the WHOLE validation pass MUST fail (raise `MoleculeTreeExtractionError`) — no partial extraction of "the safe subset" (per the contract's "Aggregate outcome" section). MUST NOT call `tarfile.extractall()` unfiltered as a fallback on any Python version.
- [ ] T005 [P] Add unit tests in `tests/unit/test_molecule_store_safety.py` covering [contracts/tar-member-validation.md](./contracts/tar-member-validation.md)'s six worked examples, built directly via `tarfile.TarInfo` fixtures (per research.md's "crafted fixtures over real git repos" testing-approach decision — no real git repo needed for these): (a) `..`-escaping path rejected; (b) symlink with absolute target rejected unconditionally, even one that would resolve inside `destination`; (c) symlink with escaping relative target rejected; (d) chained/sandwich escape (an accepted-looking symlink combined with a later member that traverses through it to escape) rejected — construct this as a genuinely compounding two-member case, not just a simpler single-member escape already covered by (a)/(b)/(c); (e) legitimate internal symlink (relative, non-escaping) accepted and extracted; (f) ordinary nested files/directories with no links at all extracted successfully and efficiently. Verifies FR-010, FR-011, FR-012, FR-013.

### Core `get_or_extract` implementation

- [ ] T006 Implement `get_or_extract(repo_dir: Path, source_url: str, revision: str, molecule_path: str, state_root: Path) -> Path` in `src/spaex/git/molecule_store.py` per [contracts/get-or-extract.md](./contracts/get-or-extract.md): (a) validate `molecule_path` shape via the same `RepoRelativePath` validation already used elsewhere (FR-014) — reject before any git/filesystem operation; (b) validate `revision` looks like a canonical 40-hex SHA (`ValueError` on a caller-contract violation, not a `HaexError` — this is a programming error per the contract, not a runtime condition); (c) derive `source_digest = clone_dir(state_root, source_url).name` using the same SHA-256-hex-16 scheme as the repository cache, then compute `revision_root = state_root / "molecule-store" / source_digest / revision` and `final_dir = revision_root / molecule_path`; `source_url` MUST be canonical and `repo_dir` MUST be the corresponding existing bare repository; (d) acquire a `ManifestLockContext`-style lock keyed off `final_dir` (matching `publisher_fetch.ensure_object`'s per-target lock-file pattern); (e) inside the lock, check whether `final_dir` already exists — if so, return it immediately (cache hit, no extraction); (f) otherwise run `git archive <revision> -- <molecule_path>` against `repo_dir`, capturing stdout bytes; a nonzero exit whose stderr indicates "did not match any files" (verified empirically: exit 128) raises the T003 not-found error; any other nonzero exit or launch failure raises `MoleculeTreeExtractionError`; (g) parse the captured bytes with `tarfile.open(fileobj=io.BytesIO(...))`, extract into a temp directory that is a SIBLING OF `revision_root` (not of `final_dir` — the corrected atomicity detail from research.md/design-doc review), preserving the archive's `molecule_path`-prefixed structure, running T004's validation before any member is written to disk; if the successful archive has no members, create the empty `molecule_path` directory in the temp tree explicitly; (h) atomically rename the temp directory's `molecule_path` child into `final_dir` (creating only `final_dir`'s trusted parent directories); (i) return `final_dir`. Verifies FR-001 through FR-009, FR-014 (except concurrency specifics, covered by US2 tests).
- [ ] T007 [P] Add unit tests in `tests/unit/test_molecule_store.py` for the caller-contract violations from T006 step (a)/(b), plus cache-key derivation: an unsafe `molecule_path` (absolute, `..`-containing, control characters) raises before any subprocess is invoked (verify via a subprocess-call-count assertion); a non-canonical-looking `revision` string raises `ValueError`; and the materialization path uses `clone_dir(state_root, source_url).name` consistently rather than any `repo_dir` path component.

**Checkpoint**: Foundation ready. `get_or_extract` fully implemented and self-consistent; user story test phases can now add story-focused coverage against it.

---

## Phase 3: User Story 1 — Core materialization (Priority P1) 🎯 MVP (with US3)

**Story goal**: Any caller can request a real, on-disk directory for a `(source, revision, molecule_path)` triple and get back byte-identical content, cached across repeat requests.

**Independent test**: [quickstart.md](./quickstart.md) sections 1-3. Verifies AS1, AS2, AS3.

- [ ] T008 [P] [US1] Add integration test in `tests/unit/test_molecule_store.py::test_materialize_returns_correct_directly_nested_content` (AS1): publish a molecule with a manifest and an arbitrary sibling file to a real, small git repo (matching `test_resolve.py`'s `_init_repo`/`_publish` helper style); call `get_or_extract`; assert the returned directory directly contains both files (not nested under an extra `molecule_path`-named level per FR-002), with byte-identical content to what was committed, and nothing else. Verifies FR-001, FR-002, FR-003.
- [ ] T009 [P] [US1] Add integration test `::test_repeated_request_is_a_cache_hit_no_reextraction` (AS2): call `get_or_extract` twice with the identical `(repo_dir, source_url, revision, molecule_path)` key; assert the same `Path` is returned both times and that no second `git archive` subprocess invocation occurs on the second call (spy/mock `subprocess.run`, matching quickstart.md section 2's pattern). Verifies FR-005, SC-002.
- [ ] T010 [P] [US1] Add integration test `::test_nonexistent_molecule_path_fails_distinctly` (AS3): request a `molecule_path` that doesn't exist at the given revision; assert the T003 not-found error type is raised (not `MoleculeTreeExtractionError`, not a generic exception) and that no directory exists at the would-be `final_dir` derived from `clone_dir(state_root, source_url).name`. Verifies FR-004.
- [ ] T011 [P] [US1] Add integration test `::test_empty_archive_succeeds_with_empty_directory` (Edge Case from spec.md): feed T006 a successful synthetic empty tar archive for an existing molecule path (no placeholder file and no broad exception handling); assert materialization succeeds and returns an existing, empty directory. This verifies T006's explicit empty-archive handling and keeps the successful empty result distinguishable from T010's not-found error. Verifies FR-001 and FR-004.

**Checkpoint**: US1 tests pass against the Foundational implementation.

---

## Phase 4: User Story 3 — Extraction safety (Priority P1) 🎯 MVP (with US1)

**Story goal**: `get_or_extract` cannot be tricked by hostile publisher content into writing files outside its destination directory.

**Independent test**: [quickstart.md](./quickstart.md) section 4, plus the six worked examples in [contracts/tar-member-validation.md](./contracts/tar-member-validation.md) (already covered at the unit level by T005). This story's own tests add an end-to-end sanity check that a REAL git repository, archived through REAL `git archive`, still gets correctly validated by the T004 logic — not just the crafted-`TarInfo`-fixture tests from T005.

- [ ] T012 [P] [US3] Add integration test in `tests/unit/test_molecule_store_safety.py::test_real_git_archive_with_tracked_symlink_is_validated` (per research.md's "at least one true end-to-end sanity check" recommendation): commit a molecule containing one LEGITIMATE tracked symlink (a relative, non-escaping one — git can track ordinary symlinks natively) to a real git repo; materialize it via the full `get_or_extract` path (real `git archive`, not a crafted tar fixture); assert it is accepted and extracted correctly, proving T004's validation logic and T006's `git archive` integration connect correctly end-to-end, not just in isolation against synthetic fixtures. Verifies FR-013's "no false refusals for legitimate content" together with a live `git archive` invocation.
- [ ] T013 [P] [US3] Add integration test `::test_materialization_failure_leaves_no_final_directory` (aggregate-outcome guarantee from contracts/tar-member-validation.md): use a crafted hostile tar fixture (reuse T005's fixtures) fed through the FULL `get_or_extract` flow (not just the internal validation function in isolation); assert `get_or_extract` raises, AND that no directory exists at the would-be `final_dir` afterward (the temp directory may be left behind as an orphan per the contract — assert only that the FINAL path was never populated). Verifies the "Aggregate outcome" section of contracts/tar-member-validation.md end-to-end.

**Checkpoint**: US1 + US3 complete together. This is the MVP — landable independently, and is what unblocks Spec 016's hook_runner implementation.

---

## Phase 5: User Story 2 — Concurrency and durability (Priority P2)

**Story goal**: Concurrent requests for the same not-yet-materialized key all succeed correctly; an interrupted materialization never corrupts the cache.

**Independent test**: launch two concurrent requests for an identical, never-before-materialized key; separately, simulate an interruption mid-materialization. Verifies AS1, AS2.

- [ ] T014 [P] [US2] Add test in `tests/unit/test_molecule_store_concurrency.py::test_concurrent_requests_for_same_key_both_succeed` (AS1): launch two `get_or_extract` calls for the identical `(repo_dir, source_url, revision, molecule_path)` from two threads (or subprocesses, if thread-based locking proves insufficient to exercise the `ManifestLockContext` file-lock path realistically) simultaneously; assert both complete successfully, both return a directory with complete and correct content, and no corruption or error occurs in either. Verifies FR-008, SC-005.
- [ ] T015 [P] [US2] Add test `::test_interrupted_materialization_does_not_corrupt_final_path` (AS2): simulate an interruption (e.g., monkeypatch the atomic-rename step in T006 to raise partway through a first attempt, after the temp directory has been populated but before rename completes) and assert no directory exists at `final_dir` as a result; then perform a normal, uninterrupted `get_or_extract` call for the same key and assert it completes and materializes correctly on its own, unaffected by the prior interrupted attempt. Verifies FR-009.

**Checkpoint**: US2 complete. Concurrency and crash-safety are proven, not just assumed from the atomic-rename design.

---

## Phase 6: User Story 4 — Constitution-resolve migration (Priority P2)

**Story goal**: `constitution/resolve.py`'s per-molecule manifest and constitution-body reads move onto `get_or_extract`, with zero observable behavior change for any existing scenario.

**Independent test**: the full existing `tests/unit/test_resolve.py` suite continues to pass unchanged in expected outcomes. Verifies AS1-AS4.

### Migration

- [ ] T016 [US4] In `src/spaex/constitution/resolve.py`, capture the return value of `git_revparse.full_sha(repo_dir, revision)` (currently called but discarded, per research.md's finding) and use the canonical SHA for every subsequent operation within the loop iteration: the store call, `ConstitutionSource.revision`, and the `seen` collision-tracking dict. Verifies FR-006, AS4.
- [ ] T017 [US4] In `resolve_constitution_contributions` (`src/spaex/constitution/resolve.py`), replace the per-molecule manifest read (`git_show.show_bytes(repo_dir, revision, f"{publisher_entry.path}/manifest.json", ...)`) with: call `molecule_store.get_or_extract(repo_dir, source_url, canonical_revision, publisher_entry.path, state_root)` to obtain `cache_dir`, then read `(cache_dir / "manifest.json").read_bytes()`. Translate a T003 not-found failure from `get_or_extract` into the existing `MissingAtomManifestError` (same error the pre-migration code raised for this condition — per the resolver error contract in research.md). Verifies FR-015, FR-016 (publisher ROOT manifest read stays unchanged — do not touch that call), FR-019.
- [ ] T018 [US4] In the same function, replace each constitution-body read (`git_show.show_bytes(repo_dir, revision, contribution_path, ...)`) with a direct read from the already-extracted `cache_dir` (no additional `get_or_extract` call — T017's call already materialized it): first validate `constitution_path` as a `RepoRelativePath` (shape check, likely already implicit from `MoleculeManifest.from_json`'s existing validation), then resolve it against `cache_dir` and require the resolved path to remain within `cache_dir` — reject a symlink-based escape the same way T004 does for tar members (FR-018). A missing file at the validated path raises the existing `ContributionFileNotFoundError`; a resolved-path escape raises `MoleculeTreeExtractionError`. Verifies FR-015, FR-018, FR-019.
- [ ] T019 [US4] Translate any other `MoleculeTreeExtractionError` surfacing from T017/T018's `get_or_extract` calls (extraction-specific IO/safety failures, not a "not found" case) so it propagates as `MoleculeTreeExtractionError` out of `resolve_constitution_contributions()` unchanged — confirming it is NOT silently folded into `MissingAtomManifestError` or `ContributionFileNotFoundError`. Verifies FR-019's "genuinely new failure category" requirement.

### Regression verification

- [ ] T020 [P] [US4] Run the existing `tests/unit/test_resolve.py` suite unchanged after T016-T019 land; every currently-passing test (`test_publisher_key_atom_id_mismatch`, `test_version_mismatch`, `test_atom_not_declared_by_publisher`, `test_atom_id_collision_across_two_source_revision_pairs`, `test_same_atom_same_source_revision_is_not_a_collision`, `test_non_contribution_atom_is_filtered_not_errored`, `test_effective_priority_overrides_lexical_molecule_order`, `test_canonicalization_idempotence_refusal`, `test_publisher_manifest_not_found`) MUST continue to pass with identical expected outcomes, with NO test-file edits required beyond what T016-T019 themselves might need for their own new assertions. If any existing test needs modification beyond a pure fixture adjustment for the new intermediate extraction step, treat that as a signal the migration changed observable behavior and STOP to reconcile before proceeding. Verifies FR-017, SC-004.
- [ ] T021 [P] [US4] Add a new test in `tests/unit/test_resolve.py` for FR-018's constitution-path escape rejection: pre-populate the materialized cache directory so T017's `get_or_extract()` takes its cache-hit path, create a constitution path symlink escaping that directory, and assert resolution refuses it (raises `MoleculeTreeExtractionError`) rather than silently reading through the escape. This test must exercise T018's direct-read/cache-directory validation, not T004's archive-member validation.

**Checkpoint**: US4 complete. `resolve.py` is on the same content-access path as everything else, with zero observable regressions.

---

## Phase 7: Polish & cross-cutting

- [ ] T022 [P] Add or extend a `docs/` note (or a module-level docstring in `src/spaex/git/molecule_store.py`, if the project prefers code-adjacent documentation over a separate doc file — check existing convention in `publisher_fetch.py`'s own module docstring for the pattern to match) documenting `get_or_extract`'s contract for future callers (starting with Spec 016's hook_runner): signature, caching behavior, failure modes, and the explicit non-goal of content-integrity verification.
- [ ] T023 Manual verification: run [quickstart.md](./quickstart.md) sections 1-5 end-to-end against the built implementation in a scratch directory. Confirm every assertion matches. Fix any drift between quickstart and implementation before merge.
- [ ] T024 Compare test count against T001 baseline: expect roughly 15-18 new tests across `test_molecule_store.py`, `test_molecule_store_safety.py`, `test_molecule_store_concurrency.py`, plus 2 new/modified tests in `test_resolve.py`. If significantly lower, review whether all acceptance scenarios are covered.
- [ ] T025 Full `pytest` run across the whole suite (not just the new/modified files) to confirm zero regressions anywhere else in the codebase from the `resolve.py` migration.

**Final checkpoint**: All phases complete, all checkboxes ticked in their corresponding commits, `pytest` green across the full suite, `resolve.py`'s observable behavior is unchanged for every pre-existing scenario, and `get_or_extract` is ready for Spec 016's hook_runner to consume.

---

## Dependencies (story completion order)

```text
Phase 1 (Setup, T001)
   ↓
Phase 2 (Foundational, T002-T007)   ← get_or_extract fully implemented, including validation
   ↓
Phase 3 (US1, T008-T011)     ┐
Phase 4 (US3, T012-T013)     ┘  ← MVP together: both exercise the same Foundational implementation,
   ↓                              can be worked in parallel once Phase 2 lands
Phase 5 (US2, T014-T015)     ← concurrency tests; independent of US1/US3's test content, same Foundational dependency
Phase 6 (US4, T016-T021)     ← the only phase that touches resolve.py; independent of US2/US3's test-only additions
   ↓
Phase 7 (Polish, T022-T025)  ← last; depends on everything above
```

## Parallel execution opportunities

- **Phase 2**: T002 and T003 (both `[P]`, different error classes, same file but additive/non-conflicting — sequence if a merge-conflict risk on the same file is a concern, otherwise safe to parallelize as independent additions) can proceed alongside T004 (different file). T005's tests depend on T004 completing. T006 depends on T002, T003, and T004. T007 depends on T006.
- **Phases 3 and 4** (US1 and US3): once Phase 2 completes, all of T008-T013 are `[P]` — different test functions, potentially different files, no cross-dependencies, since they all test the ALREADY-COMPLETE Foundational implementation rather than building new production code.
- **Phase 5** (US2): T014 and T015 are `[P]`, independent test functions in the same new file.
- **Phase 6** (US4): T016 is a prerequisite for T017 and T018 (same function, sequential edits within `resolve.py`); T019 depends on T017/T018 existing. T020 and T021 are `[P]` once T016-T019 land — one is pure regression verification (no new code), the other is a new test.

## Implementation strategy

**MVP-first**: Land Phase 1-4 (Setup, Foundational, US1, US3) as one merge — `get_or_extract` fully implemented and safety-proven. This alone unblocks Spec 016's hook_runner implementation, even before US2's concurrency tests or US4's `resolve.py` migration land.

**Story-by-story delivery**: US2 (concurrency proof) and US4 (resolve.py migration) can each land in their own follow-up commit or stacked PR after the MVP, in either order — they are independent of each other.

**Post-implementation** (out of this task list): once this spec lands, amend Spec 016's `data-model.md`/`tasks.md` (its T009 resolver-extension task and T013 hook-runner task) to call `molecule_store.get_or_extract()` at the correct call sites instead of assuming a pre-populated `cache_dir`, then resume Spec 016's implementation (currently paused, no committed code).

## Format validation

Every task above follows the `- [ ] TID [P?] [USn?] Description with file path` format:

- ✅ Checkbox `- [ ]` starts every line.
- ✅ Task IDs are sequential (T001..T025).
- ✅ `[P]` markers appear only on parallelisable tasks.
- ✅ `[US1]` / `[US2]` / `[US3]` / `[US4]` labels appear only on user-story-phase tasks (Phase 3-6); absent on Setup (Phase 1), Foundational (Phase 2), and Polish (Phase 7).
- ✅ Every description cites at least one exact file path.
