---

description: "Task list for Composition Status and Provenance Query"
---

# Tasks: Composition Status and Provenance Query

**Input**: Design documents from `/specs/028-status-provenance/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/status-and-trace-cli.md, quickstart.md

**Tests**: Included. Not explicitly requested in spec.md, but this project is test-first (`tests/unit/`, `tests/behavior/{unit,integration}/`), and several of this feature's own success criteria (SC-002, SC-004, SC-005, SC-006, SC-007) are exactly the kind of machine-checkable property this codebase already covers with dedicated tests rather than manual verification.

**Checkbox freshness is load-bearing** (see [ADR 0004](../../docs/adr/0004-eager-checkbox-update-rule.md)): tick a task's checkbox in the same commit as its output, or at the latest before starting the next task.

**Organization**: Tasks are grouped by user story (spec.md priorities) to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete sibling task at the same point in the list — a stated "Depends on" always names the real prerequisite)
- **[Story]**: Which user story this task belongs to (US1/US2/US3/US4)

## Path Conventions

Single existing project (`src/spaex/`, `tests/`), per plan.md's Project Structure.

---

## Phase 1: Setup

- [x] T001 [P] Create `src/spaex/report/__init__.py` as an empty package init.
- [x] T002 [P] Create `src/spaex/report/compose.py` as an empty module with a module-level docstring describing its role (builds `CompositionReport` — data-model.md) per plan.md's Project Structure.
- [x] T003 [P] Create `src/spaex/report/trace.py` as an empty module with a module-level docstring describing its role (builds `FileAttribution` — data-model.md) per plan.md's Project Structure.
- [x] T004 [P] Create `src/spaex/report/staleness.py` as an empty module with a module-level docstring describing its role (local-only constitution freshness recomputation — research.md R4) per plan.md's Project Structure.

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete — User Story 1 needs the clause parser and the pin-flattening helper; User Story 2 needs the path-ownership map; both need the generation-consistency read helper (FR-015).

- [x] T005 Extract `_TracedClause`/`_parse_clauses` (and the `_SECTION_HEADER_RE`/`_CLAUSE_RE`/`_PROVENANCE_ID_RE` regexes they use) out of `src/spaex/cli/behavior_commands.py` into `src/spaex/behavior/clauses.py` as public `TracedClause`/`parse_clauses`; update `behavior_commands.py` to import them from there instead of defining them locally (research.md R5). Pure move — no behavior change.
- [x] T006 Run `tests/behavior/integration/test_provenance_trace.py` and confirm it passes unmodified after T005 (SC-007; `constitution trace`'s own behavior, output and exit codes are unaffected by the move). Depends on T005.
- [x] T007 Add a public `flatten_compound_pins(manifest: ConsumerManifest) -> dict[str, tuple[str, str]]` to `src/spaex/model/consumer_manifest.py`, promoted from `behavior_commands.py`'s private `_load_molecule_pins` (research.md R5 addendum): a pure function over an already-parsed manifest, no file I/O or error-swallowing (that policy stays with each caller). Update `_load_molecule_pins` to keep its own manifest-loading/best-effort-empty-on-error wrapper but delegate the flattening to the new function.
- [x] T008 [P] Unit test for `flatten_compound_pins` in `tests/unit/test_consumer_manifest_pins.py`: several compounds, molecule ids from every compound flattened into one map, later compound's entry wins on a duplicated molecule id (matching the existing `_load_molecule_pins` iteration order). Depends on T007.
- [x] T009 Add a public `path_owners(lock: InstallLock) -> dict[str, tuple[str, ...]]` to `src/spaex/model/install_lock.py` (research.md R2 addendum): for every `MoleculeEntry` in `lock.molecules`, record each of its `paths` against its `id`, producing one `path -> (molecule_id, ...)` map with all owners of a shared path (data-model.md `PathOwnership`/`AtomGrouping`).
- [x] T010 [P] Unit test for `path_owners` in `tests/unit/test_install_lock_path_owners.py`: a path owned by one molecule, a path owned by several (mirrors `.spaex/constitution.md`'s existing shape), an empty lock. Depends on T009.
- [x] T011 Add a public `read_with_consistent_generation(repo_root: Path, build: Callable[[InstallLock], T]) -> T` to `src/spaex/model/install_lock.py` (research.md R9, FR-015): read `.spaex/install.lock` (an empty `InstallLock` when the file does not exist — never an error by itself), call `build(lock)`, re-read `.spaex/install.lock`'s `generation_id`, and retry the whole `read+build+re-read` sequence once if it changed; raise a typed error naming the two observed generation ids if it still disagrees after the retry, rather than returning a result built from a torn read.
- [x] T012 [P] Unit test for `read_with_consistent_generation` in `tests/unit/test_install_lock_consistent_read.py`: matching `generation_id` on the first pass returns immediately; a mismatch on the first pass followed by a match on the retry succeeds; a mismatch that persists through the retry raises. Depends on T011.

**Checkpoint**: Foundational ready — shared parsers and helpers exist and are verified; User Story 1 and User Story 2 can now proceed independently.

---

## Phase 3: User Story 1 - See what a repo's composition contains (Priority: P1) 🎯 MVP

**Goal**: `spaex status` lists every pinned/installed molecule (identifier, source, pinned/installed revision, install-hook outcome), each molecule's atoms grouped by what spaex did with them, and a composed-constitution summary — read-only, in both `--format text` and `--format json`.

**Independent Test**: In a repository with several installed molecules, run `spaex status` and confirm the output names every pinned molecule with its source and revision, lists the files/fragments/composed-artifact contributions each one produced, and summarizes the composed constitution, without modifying anything (spec.md User Story 1).

### Implementation for User Story 1

- [x] T013 [P] [US1] Implement fragment enumeration in `src/spaex/report/compose.py`: `behavior_fragment_ids(repo_root, molecule_id) -> list[str]` (sorted stems of `.spaex/constitution.d/<molecule_id>/*.md`) and `project_local_fragment_ids(repo_root) -> list[str]` (sorted stems of `.spaex/constitution.d/_project/*.md`) (data-model.md `AtomGrouping`/`ConstitutionSummary`).
- [x] T014 [US1] Implement `build_atom_grouping(molecule_id, lock) -> AtomGrouping` in `src/spaex/report/compose.py`, using T009's `path_owners`: `composed_artifacts` = paths with more than one owner including this molecule, excluding `COMPOSED_CONSTITUTION_RELATIVE_PATH`; `files` = paths with exactly this molecule as sole owner, excluding the same constant; `behavior_fragments` from T013 (research.md R1). Depends on T009, T013.
- [x] T015 [US1] Implement `check_constitution_staleness(repo_root) -> bool` in `src/spaex/report/staleness.py` per research.md R4: enumerate every `.spaex/constitution.d/**/*.md` (all molecule scopes plus `_project`), parse each with `BehaviorFragment.from_file`, compute `source_hash` (`spaex.behavior.emit.compute_source_hash`) and `build_input_hash` (`spaex.behavior.orchestrate.compute_build_input_hash`, fed `effective_prompt_sha256(load_effective_prompt(repo_root))` and the invalidated `.spaex/clarifications.json` store), and compare against `read_header_hashes(repo_root)`. Returns `False` when there are no fragments and no `.spaex/constitution.md` (nothing to be stale). No molecule resolution, no network, no cache access. Depends on T004.
- [x] T016 [P] [US1] Unit test for T015 in `tests/unit/test_report_staleness.py`: header matches freshly-recomputed hashes (not stale), header/fragment mismatch (stale), missing header with fragments present (stale), no fragments and no file (not stale — "no constitution" case). Depends on T015.
- [x] T017 [US1] Implement `build_constitution_summary(repo_root, lock) -> ConstitutionSummary | None` in `src/spaex/report/compose.py`: `None` when neither fragments nor `.spaex/constitution.md` exist; otherwise `exists`, `clause_counts` (via T005's `parse_clauses`, grouped by modality, zero-count modalities omitted), `contributing_molecules` (`.spaex/constitution.d/` directory names excluding `_project`, sorted), `project_local_fragment_ids` (T013), `stale` (T015). Depends on T005, T013, T015.
- [x] T018 [US1] Implement `build_composition_report(repo_root) -> CompositionReport` in `src/spaex/report/compose.py`: load the manifest via `spaex.cli.install._load_consumer_manifest` (propagates its existing `INCOMPLETE_TRANSACTION`-coded `HaexError` on a missing/invalid manifest, research.md R7); load the lock via T011's `read_with_consistent_generation`, calling T007's `flatten_compound_pins`, T014, and T017 inside the bracketed `build` callback; union pinned and installed molecule ids into sorted `MoleculeRecord`s with `install_state`/`pinned`/`installed`/`hook_status`; set `drift` to `()` for now (User Story 4 populates it). Depends on T007, T011, T014, T017.
- [x] T019 [US1] Implement `run_status(args: argparse.Namespace) -> int` in new `src/spaex/cli/status.py`: call T018, build one plain-data record, then render `--format text` or `--format json` (`format_version: 1`) per contracts/status-and-trace-cli.md's sample output, mirroring `behavior_commands.py`'s existing build-record-then-render split. Map `HaexError`s to their carried exit code; no other error handling needed (FR-014). Depends on T018.
- [x] T020 [US1] Wire the `status` subcommand into `src/spaex/cli/main.py`'s `_build_parser()`/`main()`: no positional argument, `--format text|json` (default `text`), dispatch to `run_status`, alongside the existing `constitution`/`install`/`add`/`remove` subcommands. Depends on T019.
- [x] T021 [P] [US1] Integration test for `spaex status` end-to-end in `tests/behavior/integration/test_status.py`: hand-written `.spaex/` fixtures (manifest, lock, `constitution.d/`, `constitution.md`, a shared generated-artifact path) mirroring `tests/behavior/integration/test_provenance_trace.py`'s style (no git/molecule resolution needed). Asserts the molecule listing (id/pinned/installed/hook_status), atom grouping for one molecule of each kind (behavior-only, composed-artifact-contributing, plain-file-only), the constitution summary, both `--format text` and `--format json`, and that the fixture repository is byte-for-byte unchanged after the run (FR-002). Depends on T019, T020.
- [x] T022 [P] [US1] Integration test for edge cases in `tests/behavior/integration/test_status.py`: no `.spaex/manifest.json` (exit 7), manifest present with no install lock (every molecule `pinned_not_installed`, `constitution` is `None`), no molecule contributes behavior (`constitution` is `None`), a molecule with empty `behavior_fragments`/`composed_artifacts`/`files` reported explicitly rather than omitted. Depends on T019, T020.

**Checkpoint**: `spaex status` is fully functional and independently testable (its `drift` field always reports `[]` until User Story 4 lands).

---

## Phase 4: User Story 2 - Find out which molecule wrote a file (Priority: P1)

**Goal**: `spaex trace <path>` names every molecule recorded as having written a file, or every recorded file under a directory, read-only, in both output formats.

**Independent Test**: For every path recorded in a repository's install lock, run `spaex trace <path>` and confirm it names the same molecule(s) the lock records; on a hand-written file, confirm a clear "not recorded" answer (spec.md User Story 2).

### Implementation for User Story 2

- [x] T023 [US2] Implement path normalization in `src/spaex/report/trace.py`: `normalize_query(repo_root, raw) -> str` accepts a repo-relative path, an absolute path inside the repository, a `./`-prefixed path, and a trailing slash, and returns the repo-relative POSIX form (FR-011); raises a typed error when `raw` resolves outside `repo_root`.
- [x] T024 [P] [US2] Unit test for T023 in `tests/unit/test_report_trace_normalize.py`: all four accepted forms of the same path resolve identically; a path outside the repository raises. Depends on T023.
- [x] T025 [US2] Implement `resolve_trace_query(repo_root, query) -> FileAttribution` in `src/spaex/report/trace.py`, using T011's `read_with_consistent_generation`; inside its `build` callback, load the manifest with `_load_consumer_manifest(repo_root)` and propagate its `HaexError`, then use T009's `path_owners` and T023's normalization (research.md R2): an exact-path lookup for a file query, a path-prefix match for a directory query; each match's owners resolved to `(molecule_id, source, revision)` from the lock; `constitution_trace_hint` set only when the matched path equals `COMPOSED_CONSTITUTION_RELATIVE_PATH` (FR-009); an empty `matches` list with an explanatory `error` when nothing is recorded (FR-010). A missing install lock remains an empty lock and returns no match. Depends on T009, T011, T023.
- [x] T026 [P] [US2] Unit test for T025 in `tests/unit/test_report_trace_resolve.py`: single-owner file, shared-owner path, directory-prefix match against several recorded files, no match, `constitution_trace_hint` true only for `.spaex/constitution.md` and false for every other shared path. Depends on T025.
- [x] T027 [US2] Implement `run_trace(args: argparse.Namespace) -> int` in `src/spaex/cli/status.py`: call T025, render `--format text` or `--format json` (`format_version: 1`) per contracts/status-and-trace-cli.md's sample output; map outcomes to exit codes per research.md R7 (0 on a match, 1 on no match, propagate `INCOMPLETE_TRANSACTION`/`VALIDATION_REFUSE` from a bad manifest/lock, `USAGE` on a path outside the repository). Depends on T025.
- [x] T028 [US2] Wire the `trace` subcommand into `src/spaex/cli/main.py`'s `_build_parser()`/`main()`: `<path>` positional, `--format text|json` (default `text`), dispatch to `run_trace`. Depends on T020 (same file as T020's `status` wiring; sequential, not parallel).
- [x] T029 [P] [US2] Integration test for `spaex trace` end-to-end in `tests/behavior/integration/test_trace_path.py`: single-owner file, the shared `.spaex/constitution.md` path with its `constitution trace` pointer, a directory query, a no-match case with the hand-written/install-hook explanation (exit 1), all four path forms from FR-011, a path outside the repository (exit 64), both `--format text` and `--format json`. Depends on T027, T028.

**Checkpoint**: User Story 1 and User Story 2 both independently functional.

---

## Phase 5: User Story 3 - Consume the same answers as structured data (Priority: P2)

**Goal**: Both commands' `--format json` output is a stable, deterministic contract a script or the future GUI (roadmap Phase D) can rely on.

**Independent Test**: Run both commands with `--format json` twice on an unchanged repository and confirm the outputs are byte-identical, valid against the documented structure, and contain no machine-specific values (spec.md User Story 3).

### Tests for User Story 3

- [x] T030 [P] [US3] Integration test in `tests/behavior/integration/test_status.py`: run `spaex status --format json` twice against an unchanged fixture repository, assert the two stdout captures are byte-identical (SC-004). Depends on T021.
- [x] T031 [P] [US3] Integration test in `tests/behavior/integration/test_trace_path.py`: run `spaex trace <path> --format json` twice against an unchanged fixture repository, assert byte-identical output (SC-004). Depends on T029.
- [x] T032 [P] [US3] Integration test covering both commands: assert neither command's JSON output contains an absolute path, a `~`-prefixed path, a timestamp-shaped string, or a host/user name, for representative fixtures already built in T021/T029 (FR-013). Depends on T021, T029.
- [x] T033 [P] [US3] Integration test covering both commands: assert every JSON output includes `"format_version": 1`, and that every list field data-model.md marks "Sorted" (`AtomGrouping`'s three lists, `ConstitutionSummary.contributing_molecules`/`.project_local_fragment_ids`, `CompositionReport.molecules`, `FileAttribution.matches`) is actually sorted in the rendered output (FR-013). Depends on T021, T029.

**Checkpoint**: Both commands' JSON determinism and portability guarantees are machine-verified, not just asserted in the contract.

---

## Phase 6: User Story 4 - Notice when the installed state has drifted (Priority: P2)

**Goal**: `spaex status` flags every disagreement between the manifest, the install lock, and the composed constitution, without repairing anything or changing its own exit code.

**Independent Test**: Seed four drift cases (pinned-not-installed, installed-not-pinned, revision-mismatch, stale constitution) in a scratch repository and confirm `spaex status` flags each one (spec.md User Story 4).

### Implementation for User Story 4

- [x] T034 [US4] Implement drift-finding assembly in `src/spaex/report/compose.py`: for each `MoleculeRecord`, emit a `pinned_not_installed` or `installed_not_pinned` `DriftFinding` when its `install_state` says so, and a `revision_mismatch` finding when both `pinned` and `installed` are present with differing `revision`; emit one `constitution_stale` finding (`molecule_id: null`) when the already-computed `ConstitutionSummary.stale` is `true` (research.md R3, R4). Wire the resulting sorted list into `build_composition_report`'s `drift` field, replacing User Story 1's hardcoded `()`. Depends on T018.
- [x] T035 [US4] Extend `run_status`'s text renderer in `src/spaex/cli/status.py` with a `Drift:` section (one line per finding, contracts/status-and-trace-cli.md's sample output) and a `run \`spaex install\`` hint line when `drift` is non-empty; omit the section entirely when `drift` is empty. The JSON renderer already carries `drift` unchanged from T019/T034 — no separate change needed there. Depends on T034, T019.
- [x] T036 [P] [US4] Integration test in `tests/behavior/integration/test_status_drift.py`: seed each of the four drift cases independently and confirm `spaex status` reports the correct `DriftFinding.kind` for each, that the exit code stays 0 in every case (drift is informational, FR-007), and that a fifth, fully-consistent fixture reports an empty `drift` list. Depends on T034, T035.

**Checkpoint**: All four user stories are independently functional; `spaex status` now reports drift end to end.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T037 [P] Fix the stale `SYSTEM_REFUSE` (5) comment in `src/spaex/util/exit_codes.py` (claims "missing `.spaex/manifest.json` or version mismatch") to match actual usage (`VersionBelowMinError`'s `spaex_min_version` gate and `SpeckitCliMissingError`), discovered while resolving research.md R7. Comment-only change; no behavior change.
- [x] T038 [P] Add `spaex status` and `spaex trace <path>` to README.md's "What you can do today" bullet list, matching its existing one-line-per-command style.
- [x] T039 Run quickstart.md's walkthrough end-to-end against the built implementation in a scratch repository; confirm every command and every assertion in it matches.
- [x] T040 Run the project's formatter, linter (`ruff`), type checker (`mypy`), and the full test suite; confirm SC-001 (`spaex status` completes in under 5 seconds on this repository's current 8-molecule composition) by timing a real run.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — the four new empty modules can be created immediately, all in parallel.
- **Foundational (Phase 2)**: Depends on Setup (T004 must exist before T015 uses `report/staleness.py`, though T004 itself has no other prerequisite) — BLOCKS all user stories.
- **User Stories (Phase 3-6)**: All depend on Foundational completion.
  - User Story 1 and User Story 2 have no dependency on each other and can proceed in parallel.
  - User Story 3 depends on User Story 1 and User Story 2 (it tests their already-built JSON output).
  - User Story 4 depends on User Story 1 (it extends `build_composition_report`/`run_status`, both built in Phase 3); it has no dependency on User Story 2 or 3.
- **Polish (Phase 7)**: Depends on every user story whose behavior it documents or verifies (T039/T040 exercise all four).

### User Story Dependencies

- **User Story 1 (P1)**: Starts after Foundational. No dependency on any other story.
- **User Story 2 (P1)**: Starts after Foundational. No dependency on User Story 1, aside from T028's `main.py` edit landing after T020's (same file, sequential — not a logical dependency).
- **User Story 3 (P2)**: Starts after User Story 1 and User Story 2 are both complete (it tests their output).
- **User Story 4 (P2)**: Starts after User Story 1 is complete (extends its report builder and CLI renderer). Independent of User Story 2 and User Story 3.

### Within Each User Story

- Data/logic modules before CLI wiring; CLI wiring before integration tests.
- Unit tests for a small pure function follow that function's own task, not the whole story's implementation.
- Each story's checkpoint is reached once its integration tests pass against real CLI invocations, not just its unit tests.

### Parallel Opportunities

- All Setup tasks (T001-T004) run in parallel.
- Within Foundational, T008/T010/T012 (unit tests) can each start once their respective sibling task (T007/T009/T011) completes; T005-T006 and T007 and T009 and T011 touch different functions but T005/T007 share `behavior_commands.py`, so keep those two sequential.
- Once Foundational completes, User Story 1 (T013-T022) and User Story 2 (T023-T029) can be worked in parallel by different contributors, except each story's final `main.py` wiring task (T020, T028) must land sequentially (same file).
- Within User Story 3, all four tasks (T030-T033) are independent of each other and can run in parallel once their prerequisites (T021, T029) exist.
- T037 and T038 (Polish) can run in parallel with each other and with any still-open story once Foundational is done, since neither touches files any story depends on.

---

## Parallel Example: Foundational Phase

```bash
# After T001-T004 (Setup) complete, these three extraction/addition tasks
# touch three different files and have no dependency on each other:
Task: "Add path_owners to src/spaex/model/install_lock.py (T009)"
Task: "Add read_with_consistent_generation to src/spaex/model/install_lock.py (T011)"
# (T009 and T011 share a file — land T009 first, then T011, but both can be
#  authored independently of T005/T007's behavior_commands.py work)
Task: "Extract TracedClause/parse_clauses into src/spaex/behavior/clauses.py (T005)"
```

## Parallel Example: User Story 1 + User Story 2

```bash
# Once the Foundational checkpoint is reached, an implementer can work
# User Story 1's report-building tasks (T013-T018) while another works
# User Story 2's trace-building tasks (T023-T025) — different files, no
# shared state until each story's own main.py wiring task.
Task: "Implement build_atom_grouping in src/spaex/report/compose.py (T014)"
Task: "Implement resolve_trace_query in src/spaex/report/trace.py (T025)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (critical — blocks all stories).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: run `spaex status` against this repository itself and against quickstart.md's fresh-clone scenario.
5. `spaex status` is independently useful at this point, even with `drift` always empty.

### Incremental Delivery

1. Setup + Foundational → shared parsers/helpers exist and are verified.
2. Add User Story 1 → `spaex status` works (MVP).
3. Add User Story 2 → `spaex trace <path>` works, independent of User Story 1.
4. Add User Story 3 → both commands' JSON output is machine-verified as deterministic.
5. Add User Story 4 → `spaex status` also reports drift.
6. Polish → documentation, comment fix, quickstart walkthrough, full check suite.

### Parallel Team Strategy

With two contributors: both complete Setup + Foundational together, then one takes User Story 1 (Phase 3) while the other takes User Story 2 (Phase 4) — they only need to coordinate on the shared `main.py` edit (T020 before T028). User Story 3 and User Story 4 follow once their respective prerequisites land.

---

## Notes

- [P] tasks touch different files and have no incomplete prerequisite at the point they are listed.
- [Story] labels map every user-story-phase task back to spec.md's priorities for traceability.
- FR-002 (read-only) and FR-017 (no install-pipeline/schema change) are structural properties of every task above, not a separate task: no task in this list writes to `.spaex/`, the local molecule cache, or the manifest/lock schema.
- Commit after each task or logical group; tick its checkbox in the same commit (ADR 0004).
- Stop at any checkpoint to validate a story independently before continuing.
