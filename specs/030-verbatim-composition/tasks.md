# Tasks: Verbatim Constitution Composition

**Input**: Design documents from `/specs/030-verbatim-composition/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. Success criteria SC-001 to SC-008 are verified by automated tests with the stub caller and an injected operator callback, following the project rule "leave exactly one runnable check behind for any non-trivial logic".

**Organization**: Grouped by user story. US1 to US3 are P1, US4 and US2-adjacent migration are P2, US5 is P3. The three P1 stories ship together in one code PR (the old composer cannot coexist with the new orchestration); US4 and US5 follow as small PRs.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: user story the task belongs to (US1–US5)

## Implementation notes (from reading the pipeline)

- `orchestrate.run` today does materialize → precheck → fingerprints → compose (single call or map-reduce) → clarification round → completeness → `_commit_behavior_artifacts`. The new run keeps materialize, precheck and the commit transaction, and replaces the middle.
- `_commit_behavior_artifacts` backs up and restores the composed file and the clarifications file; it must back up and restore `decisions.json` the same way, and delete `clarifications.json` and `.stale` inside the transaction.
- Header parsing (`emit._parse_header`) already accepts any numeric version; only `emit_composed` pins `"1"`.
- `composer/invoke._parse` is fixed to the compose envelope; `invoke_step` needs a parser parameter so the check can reuse runtime selection, timeouts and the JSON-lines log.
- `report/staleness.check_constitution_staleness` and `cli/behavior_commands._managed_artifact_paths` list the files a build touches; both need `decisions.json`.

---

## Phase 1: Setup

- [ ] T001 Write `docs/adr/0028-verbatim-composition.md` (context: measured condensing and nondeterminism; decision: spaex renders, model checks, operator decides, exclusions as comments; consequences: longer file, breaking format; supersedes ADRs 0022 to 0025) and mark ADRs 0022 to 0025 "Superseded by 0028"
- [ ] T002 [P] Add a "Superseded for `version="2"` by specs/030" note at the top of `specs/023-behavior-harness/contracts/spaex-md-format.md` and `composer-interface.md`, and at the top of `specs/026-reliable-fragment-composition/contracts/batch-merge-composer-interface.md`

---

## Phase 2: Foundational (blocks every story)

- [ ] T003 [P] Create `src/spaex/behavior/passages.py`: `Passage`, `locate(fragment, text)` (exactly one line-aligned occurrence or `None`), `validate_range(fragment, start, end)` rejecting unknown fragment, out-of-range, blank, and ranges that split a fenced code block, `text_of(...)`, `text_hash(...)`; unit tests `tests/behavior/unit/test_passages.py` (fence cases, blank, duplicate occurrence, CRLF normalization)
- [ ] T004 [P] Create `src/spaex/behavior/decisions.py`: `Decision`, `DecisionStore` with `checked`, `load`/`save` (atomic, schema_version 1, errors with restore hint), `finding_key(passages)`, `valid_decisions(store, fragments)` (drops decisions whose passage text no longer occurs exactly once), `build_input_hash(...)`; unit tests `tests/behavior/unit/test_decisions.py` (key stability, invalidation after unrelated edit keeps the decision, after passage edit drops it)
- [ ] T005 Create `src/spaex/behavior/render.py`: `render(fragments, decisions, preamble)` per `contracts/spaex-md-format-v2.md` (blocks in scoped-id order, exclusion comments with `-->` neutralized, merged overlapping exclusions), `parse(text)`, `verify(fragments, decisions, text)` reconstructing bodies from the parsed document; unit tests `tests/behavior/unit/test_render.py` (byte identity of bodies, headings/lists/fences preserved, modality attribute, `-->` inside an excluded passage, overlapping exclusions, verify catches a dropped line and an altered line)
- [ ] T006 [P] Replace the prompts in `src/spaex/behavior/composer/prompt.py`: add `CHECK_PROMPT` and `CHECK_PROMPT_VERSION = "3"` per `contracts/check-interface.md`; keep `load_effective_prompt` and `effective_prompt_sha256`; update `tests/behavior/unit/test_prompt_normalization.py`
- [ ] T007 Create `src/spaex/behavior/composer/check.py`: `CheckInput.to_json()` (numbered lines), `Finding`, `parse_check_result(raw, fragments)` (sentinel envelope, `no_findings` or `findings`, passage validation via `passages.py`, `invalid-output` on anything unusable), and `run_check(...)` for one call; make `invoke_step` in `composer/invoke.py` take a `parse` callable (default: the current compose parser during the transition); unit tests `tests/behavior/unit/test_check_parse.py`

**Checkpoint**: render, passages, decisions and the check parser work without any orchestration change.

---

## Phase 3: User Story 1 — The agent reads the authors' rules (Priority: P1)

**Goal**: the composed file contains every fragment verbatim.

**Independent Test**: install a set with one 32-rule fragment and a stub that returns `no_findings`; compare bodies byte for byte.

- [ ] T008 [US1] Rewrite the middle of `orchestrate.run` in `src/spaex/behavior/orchestrate.py`: after precheck, load decisions, run the check when needed (no `no_findings` shortcut yet; stub returns it), render with valid decisions, `render.verify`, then `_commit_behavior_artifacts` writing the rendered text; fragment-count fast paths and the empty-set path stay as they are
- [ ] T009 [US1] Update `src/spaex/behavior/emit.py`: `emit_rendered(text, target, ...)` replaces `emit_composed`'s header echo checks (the header is now written by `render`), version `"2"`, atomic write; keep `read_header_hashes`, `remove_if_exists`
- [ ] T010 [US1] Integration test `tests/behavior/integration/test_verbatim_composition.py`: 32-rule fragment unchanged, every fragment once, structure intact, `_project` scope fragments included, spec 029 preamble position (SC-001)

---

## Phase 4: User Story 2 — Installing again changes nothing (Priority: P1)

**Goal**: no model call and identical bytes when nothing changed; deleted file regenerates.

- [ ] T011 [US2] In `orchestrate.run`, skip the model when `decisions.checked` equals the current `source_hash` and check prompt hash (research R5); record `checked` after a completed check
- [ ] T012 [US2] Replace/extend `tests/behavior/integration/test_reproducibility.py` and `test_source_hash_skip.py`: three installs byte-identical, 0 stub calls after the first, deleted `constitution.md` regenerates identical with 0 calls, changing one fragment limits the diff to its block (SC-002, SC-003, SC-006)

---

## Phase 5: User Story 3 — Findings are decided by the operator (Priority: P1)

**Goal**: contradictions and duplicates are asked, decided and applied by exclusion.

**Independent Test**: seeded contradiction and duplicate, injected decisions.

- [ ] T013 [US3] Operator interaction in `orchestrate.py` (or a small `behavior/ask.py`): print kind, summary, passages (fragment, lines, text) and numbered options (research R7); blank or non-TTY aborts with exit 21 and the hint; injectable `operator_decision` callback replaces `operator_answer`
- [ ] T014 [US3] Apply decisions: build `Decision` from the answer, persist through `_commit_behavior_artifacts` (back up and restore `decisions.json`, remove `clarifications.json` and `.stale` inside the transaction), render exclusions; drop findings with a valid decision
- [ ] T015 [P] [US3] `tests/behavior/integration/test_findings_decisions.py`: contradiction and duplicate each asked with both passages; keep-1 comments out passage 2 unchanged; keep-all comments out nothing and is not asked again; passage edit asks again; unrelated edit does not; non-interactive exits 21 with no file changed; unusable check output exits 32 with no file changed; check unavailable exits with its category and no file changed (SC-004, SC-005)
- [ ] T016 [US3] Remove the plausibility mode: drop `abort_on_contradiction` and the `.stale` writing from `orchestrate.run`, `cli/install.py`, `cli/add.py`, `install/write_and_reinstall.py`, `install/local_publish.py`; `add`/`remove` ask like install; update `tests/behavior/integration/test_add_time_plausibility.py` and `tests/cli/test_add*.py` accordingly
- [ ] T017 [US3] Large sets: partition by molecule with the existing size limit and run the check for every batch and every pair of batches (parallel dispatch), merging findings by key; `tests/behavior/unit/test_check_pairs.py` and an update of `tests/behavior/integration/test_composition_scales.py`

---

## Phase 6: User Story 4 — Existing repos move over once (Priority: P2)

- [ ] T018 [US4] `constitution build --check` in `src/spaex/cli/behavior_commands.py`: no model call; compares the file with a fresh render and the `checked` state; messages "out of date", "version 1", "not checked"; `--force` reruns the check; add `decisions.json` to `_managed_artifact_paths`; update `tests/behavior/integration/test_constitution_build_check.py`
- [ ] T019 [P] [US4] `tests/behavior/integration/test_v1_migration.py`: version 1 file replaced in one install, old `clarifications.json` and `.stale` removed, findings asked anew, second install changes nothing (SC-007)
- [ ] T020 [P] [US4] `src/spaex/report/staleness.py`: stale when the file is missing, version is not 2, text differs from a fresh render, or `checked` does not match; update `tests/behavior/integration/test_status_drift.py`

---

## Phase 7: User Story 5 — The tools keep working (Priority: P3)

- [ ] T021 [US5] `spaex constitution trace` in `behavior_commands.py` on `render.parse` (scoped id, molecule id, phrase; line range; excluded marking; JSON fields per `contracts/cli-surface-delta.md`); update `tests/behavior/integration/test_provenance_trace.py` and `test_trace_path.py`
- [ ] T022 [P] [US5] `src/spaex/report/compose.py` and `src/spaex/cli/status.py`: `ConstitutionSummary` with `fragment_count`, `fragments_by_molecule`, `decision_count`, `excluded_passage_count`; remove `clause_counts`; update `tests/behavior/integration/test_status.py`
- [ ] T023 [P] [US5] Local scope: confirm `install/local_publish.py` uses the same run with `.spaex/local/decisions.json`; extend `tests/behavior/integration/test_local_behavior.py` (project document byte-identical, local findings asked among local fragments)
- [ ] T024 [P] [US5] Bootstrap block: add the sentence about `spaex-excluded` comments to `src/spaex/behavior/bootstrap.py`, bump its marker version, update `specs/023-behavior-harness/contracts/bootstrap-block.md` and `tests/behavior/unit/test_bootstrap_marker.py`, `tests/behavior/integration/test_bootstrap_discoverability.py`

---

## Phase 8: Polish and cross-cutting

- [ ] T025 Remove retired code and tests: `composer/reduce.py`, `composer/clarify.py`, `composer/clarifications.py`, `composer/completeness.py`, `composer/batching.py` pieces no longer used, `clauses.py`, `stale.py`, the compose and merge prompts; delete `tests/behavior/unit/test_reduce.py`, `test_clarification_key.py`, `test_completeness_check.py`, `test_emit_format.py` (rewrite for v2), `tests/behavior/fault_injection/test_reduce_partial_failure.py`, `test_composer_incomplete_output.py`; keep and adapt the other fault-injection tests to the check
- [ ] T026 [P] Docs: update `README.md`, `docs/` pages that describe composition, `specs/023-behavior-harness/contracts/cli-surface.md` pointers, and add the migration note (first install asks findings anew)
- [ ] T027 Run `uv run pytest -q`, `uv run ruff check .`, `uv run mypy src`; run `spaex install` on a copy of haex-vault and record the findings it reports and the result of `git diff --stat .spaex/` in the PR description (quickstart 7)
- [ ] T028 Open the code PR with a `feat!:` commit (BREAKING CHANGE paragraph: format version 2, decisions file, retired plausibility mode, `status` JSON keys) so release-please proposes the next major version

---

## Dependencies and execution order

- Phase 1 and 2 first; T003, T004, T006 in parallel, T005 after T003 and T004, T007 after T003 and T006.
- US1 (T008 to T010) needs T005, T007; US2 needs US1; US3 needs US1 (T011 may follow); T016 can be done with T013 to T015.
- US4 and US5 need US1 to US3; within a phase, [P] tasks are independent.
- T025 last in the code PR, after the new tests pass.

## PR plan

1. Docs PR: spec, plan, tasks (this directory), T001, T002.
2. Code PR A: T003 to T007 (foundation, no behavior change).
3. Code PR B: T008 to T017, T025 (switch-over; the breaking change).
4. Code PR C: T018 to T024, T026 to T028.
