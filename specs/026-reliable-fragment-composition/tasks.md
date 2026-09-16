---

description: "Task list for Reliable Fragment Composition"
---

# Tasks: Reliable Fragment Composition

**Input**: Design documents from `/specs/026-reliable-fragment-composition/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/batch-merge-composer-interface.md, quickstart.md

**Tests**: Included. Not explicitly requested in spec.md, but the existing `spaex.behavior.composer` subsystem this feature extends is exhaustively test-first (`tests/behavior/{unit,fault_injection,integration}/`), and the properties this feature must hold (byte-reproducibility, non-destructive rollback, contradiction detection) are exactly the kind existing project convention already covers with dedicated tests rather than manual verification.

**Checkbox freshness is load-bearing** (see [ADR 0004](../../docs/adr/0004-eager-checkbox-update-rule.md)): tick a task's checkbox in the same commit as its output, or at the latest before starting the next task.

**Organization**: Tasks are grouped by user story (spec.md P1/P2/P3) to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1/US2/US3)

## Path Conventions

Single existing project (`src/spaex/`, `tests/`), per plan.md's Project Structure.

---

## Phase 1: Setup

- [x] T001 Create `src/spaex/behavior/composer/batching.py` and `src/spaex/behavior/composer/reduce.py` as empty modules with module-level docstrings describing their role per plan.md's Project Structure.

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete — every user story's tests depend on the log format and the extracted clarification helper.

- [x] T002 [P] Change `$SPAEX_COMPOSER_LOG` to a JSON-lines format (data-model.md's `ComposerLogEntry`: `step`, `invocation`, `phase`, `raw_output`, `outcome`), truncate it exactly once at attempt start, and append/flush each completed invocation thereafter in `src/spaex/behavior/composer/invoke.py` (`write_composer_log`/`resolve_composer_log_path` and their call sites). Preserve both records of a clarification round trip. Applies uniformly whether a build has one step or many — no separate "small fragment set" log format.
- [x] T003 [P] Extract `orchestrate.py`'s existing `_resolve_clarifications` clarification round-trip into a form callable once per batch call or once for the merge call (not only once for the whole build), preserving its existing one-round-trip bound (a second Shape B from the same call remains `invalid-output`). **Deviation**: lives in new module `src/spaex/behavior/composer/clarify.py`, not `orchestrate.py` — `orchestrate.py` imports `reduce.py` for T013's entry point, so putting the shared helper in `orchestrate.py` would make `reduce.py`'s import of it a cycle. `orchestrate._resolve_clarifications` now delegates to `clarify.resolve_step_clarifications`, unchanged in behavior.
- [x] T004 [P] Implement deterministic fragment→batch partitioning per research.md §2 (byte-size ceiling with a fragment-count guard; a molecule's fragments never split across batches) in `src/spaex/behavior/composer/batching.py`.
- [x] T005 [P] Unit tests for batch partitioning — determinism (same input → same batches across repeated calls), boundary sizes (exactly at the ceiling, one byte over), a molecule whose fragments would otherwise straddle a boundary, an oversized molecule that returns the typed `input-too-large` diagnostic without a `Batch`, and the single-batch degenerate case — in `tests/behavior/unit/test_batching.py`.
- [x] T006 [P] Unit test asserting the new composer-log format: truncate once per simulated attempt, append multiple independently parseable entries across steps, and retain ordered initial/resolved records for a clarification round trip, in `tests/behavior/unit/test_composer_log_format.py`.

**Checkpoint**: Foundation ready — user story implementation can begin.

---

## Phase 3: User Story 1 - Install succeeds reliably at real-world molecule counts (Priority: P1) 🎯 MVP

**Goal**: `spaex install` composes a complete, correct constitution for a fragment set of any size, via bounded batch calls plus one merge call, reusing the existing single-call machinery unchanged per call.

**Independent Test**: Adopt a fragment set spanning at least 3 batches (synthetic, via `stub_caller` — no real subprocess in tests). Run the composition entry point and confirm every fragment is cited in the final document, the response carries the correct full-set `source_hash`/`build_input_hash` header, and the same single runtime answered every step.

### Tests for User Story 1 ⚠️

- [x] T007 [P] [US1] Fault-injection test: batch 1 of 3 succeeds, batch 2 times out — assert the build aborts as `behavior-composer-timeout`, the previously published constitution is byte-unchanged (FR-004), and `$SPAEX_COMPOSER_LOG` contains batch 1's completed entry even though batch 2 is the one that failed (FR-008), in `tests/behavior/fault_injection/test_reduce_partial_failure.py`.
- [x] T008 [P] [US1] Integration test: a synthetic fragment set spanning 3+ batches composes successfully end-to-end via `stub_caller` — every fragment cited, correct final header hashes, single runtime used throughout — in `tests/behavior/integration/test_composition_scales.py`.
- [x] T009 [P] [US1] Integration test: a fragment set small enough for one batch produces output byte-identical to today's single-call path (SC-004 no-regression check), in the same test file as T008.

### Implementation for User Story 1

- [x] T010 [US1] Add the merge-step system prompt constant to `src/spaex/behavior/composer/prompt.py`: instructs the LLM to merge N already-composed partial documents (not raw fragments) into one, re-checking for contradictions across the partial documents' clauses, and to stamp the `spaex-composed:source_hash=... build_input_hash=...` header using the full-set hashes supplied in its input.
- [x] T011 [US1] Implement per-batch dispatch in `src/spaex/behavior/composer/reduce.py`: for each `Batch` (T004), build a scoped `ComposerInput` (batch-local fragments + batch-local clarifications per data-model.md), invoke via the existing `invoke.py` single-call machinery with one runtime resolved once for the whole attempt (FR-011), and handle a batch's own Shape B via the extracted round-trip (T003). Depends on T002, T003, T004.
- [x] T012 [US1] Implement bounded merge dispatch in `src/spaex/behavior/composer/reduce.py`: assemble `MergeInput` from every `BatchComposition` plus any cross-batch clarifications; use one N-ary merge when the serialized input fits the fixed ceiling, otherwise reduce adjacent inputs in deterministic pairwise tree levels with odd inputs carried forward; preserve citations, source membership, clarification answers, and full-set hash/header propagation at every intermediate and root result; handle each merge node's Shape B via the same extracted round-trip (T003). Depends on T010, T011.
- [x] T012a [P] [US1] Unit-test bounded tree reduction in `tests/behavior/unit/test_reduce.py`: force a merge input over the ceiling, assert adjacent pair grouping and deterministic odd-item carry-forward, assert every intermediate payload remains bounded, and assert a pair that cannot fit returns the typed `input-too-large` diagnostic without raw concatenation. Depends on T012.
- [x] T012b [US1] Integration-test final tree composition in `tests/behavior/integration/test_composition_scales.py`: compose a synthetic set requiring multiple tree levels, assert the root is the only result with the full-set header, every fragment citation and provenance survives, a cross-tree contradiction raises a merge-node Shape B, and a resolved answer is honored at the final output. Depends on T008 and T012.
- [x] T013 [US1] Wire a new multi-step entry point in `reduce.py` (partition → dispatch batches → dispatch merge → return the same `InvokeOutcome`/`ComposedShape` shape `orchestrate.py` already expects) and replace `orchestrate.py`'s direct `invoke_composer(...)` call with it, preserving the existing single-batch degenerate case exactly. Depends on T012.
- [x] T014 [US1] Progress/log messages per batch/merge step, reusing the existing invocation-progress and elapsed-time-on-response format (`composer: invoking <runtime>...` / `composer: <runtime> responded in X.Xs`) plus a per-step completion line (e.g. `composer: batch-2 composed (...)`), in `reduce.py`. Depends on T011, T012.

**Checkpoint**: User Story 1 is fully functional and independently testable — this is the MVP.

---

## Phase 4: User Story 2 - Composed output stays byte-reproducible (Priority: P2)

**Goal**: Confirm the byte-reproducibility guarantee (research.md §6: holds by construction from US1's deterministic batching + single-runtime resolution) actually holds under the new multi-step pipeline.

**Independent Test**: Run composition twice against the same unchanged multi-batch fragment set and diff the output byte-for-byte; confirm a third run with nothing changed skips composition entirely.

### Tests for User Story 2

- [ ] T015 [P] [US2] Test: two consecutive compositions (via `stub_caller`, deterministic stub responses) against the same unchanged multi-batch fragment set produce byte-identical composed output, and a subsequent run with nothing changed hits the existing reproducibility skip without invoking any batch or merge call, in `tests/behavior/integration/test_reproducibility.py`.
- [ ] T016 [P] [US2] Test: forcing recomposition (`force_composer=True`, matching `spaex constitution build --force`) of the same unchanged multi-batch fragment set produces output byte-identical to the original composition, in the same test file.

### Implementation for User Story 2

No new production code expected (research.md §6: determinism holds by construction from US1's design). If either test above fails, that is itself the finding — fix the specific nondeterminism it exposes in `reduce.py`/`batching.py` rather than adding new mechanism speculatively.

**Checkpoint**: User Stories 1 and 2 both verified independently.

---

## Phase 5: User Story 3 - Genuine cross-fragment contradictions are still caught (Priority: P3)

**Goal**: Confirm a contradiction between two fragments placed in different batches is still surfaced to the operator via Shape B, exactly as a same-batch or single-call contradiction would be.

**Independent Test**: Two molecules whose fragments contradict, positioned (via the deterministic batching from T004) so they land in different batches. Run composition and confirm a Shape B contradiction question naming both fragments is raised at the merge step, not silently resolved either way.

### Tests for User Story 3

- [ ] T017 [P] [US3] Test: two molecules with contradicting fragments placed in different batches — assert the merge step raises a `contradiction` Shape B question citing both fragments, in `tests/behavior/integration/test_case_b_cross_molecule.py` (extend existing file, which already covers this scenario for the single-call path).
- [ ] T018 [P] [US3] Test: once the operator answers that cross-batch clarification, a subsequent composition of the same fragment set honors the persisted answer and does not re-ask, in the same test file.

### Implementation for User Story 3

No new production code expected beyond T012's merge-step Shape B handling and T003's extracted round-trip. If either test above fails, the fix belongs in the merge-step's clarification handling (T012), not a new mechanism.

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T019 [P] Add a short cross-reference from `specs/023-behavior-harness/contracts/composer-interface.md` to `contracts/batch-merge-composer-interface.md`, noting the latter extends the former for multi-batch builds (Spec Kit constitution Principle III: cross-artifact consistency).
- [ ] T020 Manually run `quickstart.md`'s walkthrough against this project's own real fragment set (currently 9 molecules) once T001-T014 are implemented, confirming the actual observed behavior matches the documented example output.
- [ ] T021 [P] Add a short ADR under `docs/adr/` recording the map-reduce composition decision and the new `Batch`/`BatchComposition`/`MergeInput` entities (Spec Kit constitution: architectural decisions materially changing the domain model SHOULD be recorded as ADRs).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories (T011 needs T002-T004; T012 needs T003).
- **User Story 1 (Phase 3)**: Depends on Foundational. This is the only phase with new production code — it *is* the mechanism the spec asks for.
- **User Story 2 (Phase 4)**: Depends on User Story 1 (nothing to verify reproducibility of until the mechanism exists). No new production code expected.
- **User Story 3 (Phase 5)**: Depends on User Story 1 (specifically T012's merge Shape B handling). No new production code expected. Independent of Phase 4 — can run in parallel with it.
- **Polish (Phase 6)**: Depends on Phase 3 being complete (T020 needs a working implementation to walk through); T019 and T021 can start as soon as Phase 3's design is stable.

### Within Each Phase

- Tests before implementation (write, watch fail, then implement) per this project's `test-driven-development`/`tdd` conventions.
- `batching.py` (T004) before `reduce.py`'s batch dispatch (T011).
- Merge prompt (T010) before merge dispatch (T012).
- Batch dispatch (T011) before merge dispatch (T012) before orchestrate.py wiring (T013).

### Parallel Opportunities

- T002, T003, T004 (Foundational) touch different files/functions and can run in parallel.
- T005, T006 (Foundational tests) can run in parallel with each other and with T002-T004 once their respective targets exist.
- T007, T008, T009 (US1 tests) can run in parallel with each other.
- Phase 4 and Phase 5 (US2, US3) can run fully in parallel once Phase 3 lands — neither touches the other's files.
- T019, T021 (Polish) can run in parallel with each other and with T020.

---

## Parallel Example: Foundational Phase

```bash
Task: "Change $SPAEX_COMPOSER_LOG to JSON-lines format in src/spaex/behavior/composer/invoke.py"
Task: "Extract the clarification round-trip helper in src/spaex/behavior/orchestrate.py"
Task: "Implement deterministic fragment→batch partitioning in src/spaex/behavior/composer/batching.py"
```

## Parallel Example: User Story 1 Tests

```bash
Task: "Fault-injection test: partial multi-batch failure in tests/behavior/fault_injection/test_reduce_partial_failure.py"
Task: "Integration test: multi-batch composition succeeds end-to-end in tests/behavior/integration/test_composition_scales.py"
Task: "Integration test: single-batch output byte-identical to today's path in tests/behavior/integration/test_composition_scales.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational — the log format, the extracted clarification helper, and deterministic batching every later phase relies on).
2. Complete Phase 3 (User Story 1) — the actual map-reduce mechanism. This alone resolves the reported failure (SC-001: 9-molecule fragment set succeeds reliably).
3. **STOP and VALIDATE**: run T020's quickstart walkthrough against the real 9-molecule repo state before proceeding.

### Incremental Delivery

1. Setup + Foundational → batching and logging primitives ready, independently unit-tested.
2. User Story 1 → the reliability fix itself, independently integration-tested → this is deployable on its own (MVP).
3. User Story 2 and User Story 3 → verification-only phases confirming the two guarantees US1's design was supposed to preserve actually hold; either can surface a bug in US1 rather than requiring new mechanism.
4. Polish → cross-artifact consistency and a durable design record.

## Notes

- No new top-level project or dependency; every task lives inside the existing `spaex.behavior.composer` package and its existing test tree.
- Every implementation task in Phase 3 (US1) reuses `invoke.py`'s existing `_call_cli`/`_parse` unchanged — no task modifies the sentinel parsing, the five failure categories, or the CLI-argv/runtime-resolution logic itself.
- If T015/T016 (US2) or T017/T018 (US3) fail, treat that as a defect in Phase 3's implementation to fix, not a signal to add new reproducibility/contradiction-detection machinery — research.md §1/§6 already argue these properties should hold by construction.
