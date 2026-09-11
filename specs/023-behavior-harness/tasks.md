---
description: "Tasks for spec 023-behavior-harness"
---

# Tasks: Behavior Harness

**Input**: Design documents from `/specs/023-behavior-harness/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md, all present and committed.

**Checkbox freshness is load-bearing.** Tick the checkbox in the same commit as the task's output, or at the latest in the next commit, before starting the next task. Handoff queries read this file's checkbox state as the primary state document; stale ticks systematically mislead. See [ADR 0004](../../docs/adr/0004-eager-checkbox-update-rule.md).

**Organization**: tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks).
- **[Story]**: Which user story this task belongs to (US1..US6). Setup, Foundational, and Polish phases carry no story label.
- Every task lists an exact file path.

## Path conventions

Single-project Python layout: `src/spaex/`, `tests/behavior/` at repository root. Paths below use those roots.

---

## Phase 1: Setup

**Purpose**: project scaffolding required before any behavior-harness code runs.

- [X] T001 Create the module skeleton at src/spaex/behavior/ with empty __init__.py plus empty stub modules fragment.py, materialize.py, precheck.py, emit.py, bootstrap.py so imports resolve during scaffolding
- [X] T002 [P] Create the module skeleton at src/spaex/behavior/composer/ with empty __init__.py plus empty stub modules prompt.py, invoke.py, clarifications.py, failure.py
- [X] T003 [P] Create the test tree at tests/behavior/ with subdirectories unit/, integration/, fault_injection/, fixtures/ and empty __init__.py files where pytest requires them
- [X] T004 [P] Draft ADR-0012 stub at docs/adr/0012-behavior-harness-reserved-paths.md capturing the reserved-paths update ($<repo-root>/.spaex.md$, .spaex/constitution.d/, .spaex/clarifications.json, .spaex/.stale, .spaex/composer.log) and the "commit-as-review-gate for .spaex.md" framing under Principle VI
- [X] T005 [P] Draft ADR-0013 stub at docs/adr/0013-global-bootstrap-block-contract.md capturing the paired HTML comment markers with version attribute and the target-paths table per runtime
- [X] T006 [P] Add .spaex/.stale and .spaex/composer.log to the project template .gitignore for consumer repos and document that .spaex.md and .spaex/constitution.d/ MUST NOT be gitignored
- [X] T007 Confirm pytest and existing spaex test fixtures work in the fresh worktree by running uv run pytest -q against the current main branch; note baseline pass count as a comparison anchor (baseline: 463 passed, 1 skipped, 9 deselected on 2026-09-11)

**Checkpoint**: module and test scaffolding present, ADR stubs live, imports resolve. Nothing observable to a consumer yet.

---

## Phase 2: Foundational (blocking prerequisites for all user stories)

**Purpose**: fragment schema, materialization, mechanical pre-check, and clarifications-file schema. Every user story depends on this phase.

**⚠️ CRITICAL**: no user-story work begins until this phase is complete.

- [X] T008 [P] Implement the Behavior Fragment pydantic model in src/spaex/behavior/fragment.py per contracts/fragment-format.md and data-model.md §Behavior Fragment (fields id, kind, atom_source, modality enum, tags, body); validators for the id regex and for the reserved `<!-- spaex-` guard (FR-001, FR-007)
- [X] T009 [P] Implement the body_sha256 normalization + hash function in src/spaex/behavior/fragment.py (strip trailing whitespace per line, CRLF→LF, collapse trailing newlines) per research.md §7 (FR-011)
- [X] T010 [P] Unit tests for Fragment schema in tests/behavior/unit/test_fragment_schema.py covering every validation error class from contracts/fragment-format.md §Validation errors (FR-001, FR-007)
- [X] T011 [P] Unit tests for body_sha256 normalization in tests/behavior/unit/test_body_hash_normalization.py including a CRLF-round-trip case (memory feedback_verify_tool_behavior_empirically) (FR-011)
- [X] T011a [P] Extend src/spaex/schema/data/molecule-manifest.v4.schema.json with the typed-atom `constitution_fragments` declaration, preserving the existing v4 manifest fields and validating inline fragment fields per contracts/fragment-format.md
- [X] T011b [P] Extend src/spaex/model/molecule_manifest.py and its parsed model to preserve validated inline `constitution_fragments` keyed by enclosing typed atom
- [X] T011c [P] Add tests/contract/test_molecule_manifest_v4.py coverage for valid inline declarations, parser preservation, and malformed inline fragments
- [X] T012 Implement materialize.py in src/spaex/behavior/materialize.py: read standalone fragments from the Spec 017 molecule-store (molecule_store.get_or_extract), consume parsed inline behavior blocks from `MoleculeManifest`, and write all outputs to a transaction-owned staging tree rather than directly to `.spaex/constitution.d/` (FR-002, FR-003, FR-004)
- [X] T013 [P] Unit tests for materialize in tests/behavior/unit/test_materialize.py covering: standalone fragment atom, typed-atom inline block, project-local fragment routing to _project scope (FR-002, FR-003, FR-004, FR-018 stub)
- [X] T014 Implement mechanical pre-check in src/spaex/behavior/precheck.py: detect intra-molecule id-collision with contradictory modality, detect malformed fragments, require identical normalized bodies before duplicate-id-same-modality dedupe, reject body mismatches, and enforce the project-local bare-id comparison rule; emit typed diagnostics (FR-005, FR-007, FR-020)
- [X] T015 [P] Unit tests for precheck in tests/behavior/unit/test_precheck.py exercising every fragment-format validation error and the intra-molecule collision case (FR-005, FR-007)
- [X] T016 [P] Implement the Constitution Clarification pydantic model + JSON load/save (atomic tmp+rename) in src/spaex/behavior/composer/clarifications.py per contracts/clarifications-schema.md (FR-011, FR-012)
- [X] T017 [P] Unit tests for clarification key derivation in tests/behavior/unit/test_clarification_key.py: sort order, normalization, LF+trim invariance, mismatch detection (FR-011, FR-012, SC-008 unit portion)

**Checkpoint**: fragment authoring and mechanical validation work end-to-end. No composer yet, no emission yet.

---

## Phase 3: User Story 1 - Consumer receives a composed behavior harness after install (Priority: P1) 🎯 MVP

**Goal**: `spaex install` produces `.spaex.md` at the repo root; a runtime that has run the global bootstrap discovers it.

**Independent test**: fixture project with two pinned molecules each contributing one fragment; `spaex install` writes `.spaex.md` with both directives grouped by modality with visible provenance; a mocked runtime session reading its global instruction file discovers `.spaex.md` and loads its content.

- [ ] T018 [US1] Author the canonical Composer system prompt as a string constant in src/spaex/behavior/composer/prompt.py per contracts/composer-interface.md §"Canonical system prompt" (FR-008, FR-010, FR-010a)
- [ ] T019 [US1] Implement Composer invocation in src/spaex/behavior/composer/invoke.py with runtime detection order (direct-API via litellm first, then claude/codex/gemini CLI shell-out); parse Shape A and Shape B responses; enforce SPAEX_COMPOSER_TIMEOUT (research.md §1, §2; contracts/composer-interface.md)
- [ ] T020 [P] [US1] Implement Composer failure categorization + exit codes in src/spaex/behavior/composer/failure.py per research.md §8 (FR-012a; five categories: timeout, runtime-error, invalid-output, quota, no-runtime)
- [ ] T021 [P] [US1] Fault-injection test scaffolding in tests/behavior/fault_injection/conftest.py with a MockComposer fixture that emits configurable failure categories (SC-011)
- [ ] T022 [P] [US1] Fault-injection test tests/behavior/fault_injection/test_composer_timeout.py (SC-011, exit 30)
- [ ] T023 [P] [US1] Fault-injection test tests/behavior/fault_injection/test_composer_malformed.py (SC-011, exit 32)
- [ ] T024 [P] [US1] Fault-injection test tests/behavior/fault_injection/test_composer_runtime_error.py (SC-011, exit 31)
- [ ] T025 [P] [US1] Fault-injection test tests/behavior/fault_injection/test_composer_quota.py (SC-011, exit 33)
- [ ] T026 [P] [US1] Fault-injection test tests/behavior/fault_injection/test_composer_no_runtime.py (SC-011, exit 34)
- [ ] T027 [US1] Implement emission in src/spaex/behavior/emit.py: build `.spaex.md` content from Composer output (Shape A), write atomically (tmp+rename), include verified `source_hash` and `build_input_hash` in the `<!-- spaex-composed:... version="1" -->` header (FR-013, FR-017a, FR-017b, contracts/spaex-md-format.md)
- [ ] T028 [P] [US1] Unit test for emission format in tests/behavior/unit/test_emit_format.py: section order, provenance regex, source_hash header, empty-set behavior (FR-008, FR-017d, contracts/spaex-md-format.md)
- [ ] T029 [US1] Wire the behavior subsystem into src/spaex/install.py as one transaction: materialize into a staging tree, run precheck against the staged tree, run Composer and clarification staging there, then publish `.spaex/constitution.d/`, `.spaex.md`, and `.spaex/clarifications.json` only after every aborting step succeeds; duplicate producers and all failure paths leave tracked files untouched (FR-004, FR-006, FR-008, FR-017c)
- [ ] T030 [P] [US1] Integration test tests/behavior/integration/test_install_end_to_end.py: fixture project with two pinned molecules each contributing one behavior fragment, `spaex install` produces `.spaex.md` with both directives + provenance (SC-001)
- [ ] T031 [P] [US1] Integration test tests/behavior/integration/test_reproducibility.py: run `spaex install` twice on the same fixture, assert byte-identical `.spaex.md` (SC-003)
- [ ] T032 [US1] Implement the Global Bootstrap Block installer in src/spaex/behavior/bootstrap.py: locate target files per research.md §3, install/upgrade/remove within paired HTML comment markers with version attribute (FR-014, FR-015, FR-016, FR-017, contracts/bootstrap-block.md)
- [ ] T033 [P] [US1] Unit test for bootstrap markers in tests/behavior/unit/test_bootstrap_marker.py: parse existing block, version-attribute-driven upgrade, content-outside-block preservation, idempotency (FR-015, FR-016, SC-009)
- [ ] T034 [P] [US1] Integration test tests/behavior/integration/test_bootstrap_discoverability.py: verify a mocked agent session reading its global instruction file after bootstrap loads `.spaex.md` (SC-007 automated portion)
- [ ] T035 [US1] Add the `spaex install --global [runtimes]` CLI subcommand in src/spaex/cli/behavior_commands.py: parse runtime list, invoke bootstrap installer, support --dry-run and --check flags (contracts/cli-surface.md §"spaex install --global")
- [ ] T036 [P] [US1] Add end-of-install hint when a project-level install detects that the global bootstrap has never been run on this machine per FR-017c edge-case documentation (FR-023, edge case "Bootstrap not yet installed")

**Checkpoint**: US1 MVP delivers. A consumer can pin a molecule with fragments, run `spaex install`, get `.spaex.md`, and see any runtime that ran the global bootstrap load it.

---

## Phase 4: User Story 2 - Molecule author declares behavior fragments (Priority: P1)

**Goal**: an author can add a fragment file (standalone or inline) and consumers see it after re-pinning.

**Independent test**: given the fragment-format doc, author writes a fragment; molecule publishes; consumer bumps pin; `spaex install` includes the new directive.

Most authoring machinery lands in Phase 2 (fragment schema + materialize). This phase adds author-focused tests.

- [ ] T037 [P] [US2] Integration test tests/behavior/integration/test_inline_behavior_blocks.py: a typed atom (e.g., speckit_workflow) with an inline `constitution_fragments:` block materializes identically to a standalone fragment atom (FR-003)
- [ ] T038 [P] [US2] Integration test tests/behavior/integration/test_molecule_without_fragments.py: a molecule shipping zero behavior fragments MUST NOT alter the composed constitution (User Story 2 acceptance scenario 3)

**Checkpoint**: US2 authoring surface verified against the format docs.

---

## Phase 5: User Story 3 - Hard conflict aborts install with named provenances (Priority: P2)

**Goal**: both intra-molecule (Case A, mechanical) and cross-molecule (Case B, semantic) contradictions abort install with clear provenance.

**Independent test**: two fixtures cover the two cases; each aborts with exit code 20 (A) or 21 (B) and no tracked file is modified.

- [ ] T039 [P] [US3] Integration test tests/behavior/integration/test_case_a_intra_molecule.py: fixture with one molecule shipping two fragments under the same molecule-scoped id with contradictory modality; `spaex install` exits 20 before Composer runs (FR-005, SC-002 Case A)
- [ ] T040 [P] [US3] Integration test tests/behavior/integration/test_case_b_cross_molecule.py: fixture with two molecules whose fragments the Composer flags as semantically contradictory; declined reconciliation causes exit 21 (FR-005a, FR-010a, SC-002 Case B)
- [ ] T041 [P] [US3] Integration test tests/behavior/integration/test_install_is_non_destructive.py: assert that after each of exit codes 20, 21, 22, 30-34, the fixture repo's tracked files (`.spaex.md`, `.spaex/constitution.d/`, `.spaex/clarifications.json`) are byte-unchanged (FR-006)

**Checkpoint**: US3 conflict paths verified.

---

## Phase 6: User Story 4 - Clarification round resolves ambiguity, answers persist (Priority: P2)

**Goal**: Composer asks once, answer persists, re-asks on material change.

**Independent test**: fixture with a semantically-overlapping fragment pair; first install prompts once; second install with unchanged fragments does not; third install after editing an involved fragment re-asks exactly once.

- [ ] T042 [US4] Wire clarification storage into the Composer loop in src/spaex/behavior/composer/invoke.py: on Shape B, present question to operator, persist answer via clarifications.py, re-invoke Composer with updated input (FR-010, FR-011, contracts/composer-interface.md)
- [ ] T043 [P] [US4] Integration test tests/behavior/integration/test_clarification_persistence.py: three-phase scenario (answer once, no re-ask, re-ask on body change) with a scripted operator (SC-008)

**Checkpoint**: US4 clarification loop verified.

---

## Phase 7: User Story 5 - Project adds additive local behavior fragments (Priority: P3)

**Goal**: project can declare local fragments in `.spaex.json` (inline or file-reference); additive-only enforcement rejects any override attempt.

**Independent test**: fixture with one project-local fragment and zero molecules; `spaex install` produces `.spaex.md` with the project-local fragment. Fixture attempting to override an atom-provided fragment aborts with exit 22.

- [ ] T044 [US5] Extend `.spaex.json` schema parsing in src/spaex/config.py (existing module) to read `constitution.local_fragments[]` inline entries and file-reference entries (FR-018)
- [ ] T045 [US5] Extend src/spaex/behavior/materialize.py to write project-local fragments to `.spaex/constitution.d/_project/<fragment-id>.md` running through identical mechanical pre-check + Composer paths (FR-018, FR-019)
- [ ] T046 [US5] Implement additive-only enforcement in src/spaex/behavior/precheck.py: treat `_project/<fragment-id>` as a distinct emitted identity but reject it when its bare `fragment_id` matches any atom-provided `<molecule-id>/<fragment-id>`, naming every match and the additive-only remedy with exit code 22 (FR-020)
- [ ] T047 [P] [US5] Integration test tests/behavior/integration/test_project_local_fragments.py: local-only fragment appears in `.spaex.md` with `_project` source; override attempt aborts with exit 22 (SC-005, SC-010)

**Checkpoint**: US5 project-local flow verified.

---

## Phase 8: User Story 6 - Cross-machine reproducibility (Priority: P3)

**Goal**: two clones on the same commit produce identical `.spaex.md` without re-running the Composer.

Reproducibility groundwork lands in Phase 3 (T031). This phase adds the fragment-drift-detection test.

- [ ] T048 [US6] Implement source/build-input fingerprint comparison in src/spaex/behavior/emit.py: on `spaex install`, if the on-disk `.spaex.md` header's `source_hash` and `build_input_hash` match the locally computed hashes for current fragments, effective prompt, prompt version, and valid clarifications, skip Composer invocation (FR-009)
- [ ] T049 [P] [US6] Integration test tests/behavior/integration/test_source_hash_skip.py: two runs with identical committed state, second run must not invoke the Composer; changing fragment metadata or the effective prompt must invalidate the matching fingerprint (User Story 6 acceptance scenario 1)
- [ ] T050 [P] [US6] Integration test tests/behavior/integration/test_fragment_drift.py: fragments changed on disk without a Composer run; next `spaex install` detects drift and invokes the Composer (User Story 6 acceptance scenario 3)

**Checkpoint**: US6 reproducibility guarantees verified.

---

## Phase 9: FR-024a add-time plausibility

**Purpose**: separate phase because it touches `spaex add` and `spaex remove`, not `spaex install`.

- [ ] T051 Extend `spaex add` in src/spaex/cli/add.py (existing module) to run the Composer plausibility check after the fragment set changes; on cross-molecule semantic contradiction, print WARN with provenance, write `.spaex/.stale` sidecar summarizing the finding, do NOT abort, do NOT regenerate `.spaex.md` (FR-024a, contracts/cli-surface.md §add/remove)
- [ ] T052 Extend `spaex remove` in src/spaex/cli/remove.py (existing module) identically per FR-024a
- [ ] T053 [P] Integration test tests/behavior/integration/test_add_time_plausibility.py: `spaex add` of a molecule that semantically contradicts an already-pinned one prints WARN, writes `.spaex/.stale`, exits 0; `.spaex.md` byte-unchanged (FR-024a)
- [ ] T054 Extend src/spaex/install.py to read `.spaex/.stale` on start and route through the reconciliation prompt (FR-010a) before writing `.spaex.md`

**Checkpoint**: add-time flow verified; stale flag drives install-time reconciliation.

---

## Phase 10: CLI polish

**Purpose**: user-facing commands beyond `spaex install`.

- [ ] T055 [P] Implement `spaex constitution build` subcommand in src/spaex/cli/behavior_commands.py with --force and --check flags (contracts/cli-surface.md §"spaex constitution build")
- [ ] T056 [P] Implement `spaex constitution trace <query>` subcommand in src/spaex/cli/behavior_commands.py: accept only an exact scoped fragment id `<molecule-id>/<fragment-id>` or a clause-text substring, reject bare fragment ids as ambiguous, and print every provenance record for merged clauses in text/json formats (FR-022, contracts/cli-surface.md §"spaex constitution trace")
- [ ] T057 [P] Integration test tests/behavior/integration/test_provenance_trace.py covering both query modes and text/json output formats (SC-006)
- [ ] T058 [P] Integration test tests/behavior/integration/test_constitution_build_check.py covering `--check` exit codes (SC-003 verification)

**Checkpoint**: full CLI surface delivered.

---

## Phase 11: Polish, docs, migration, release

**Purpose**: ADR finalization, `.spaex/constitution.md` supersession, version bump, changelog.

- [ ] T059 [P] Finalize ADR-0012 at docs/adr/0012-behavior-harness-reserved-paths.md with the full decision text, cross-referencing spec 023 and updating the constitution's §"Reserved paths" clause to include `<repo-root>/.spaex.md`
- [ ] T060 [P] Finalize ADR-0013 at docs/adr/0013-global-bootstrap-block-contract.md with the full decision text, cross-referencing contracts/bootstrap-block.md
- [ ] T061 Update docs/adr/README.md index with entries for 0012 and 0013
- [ ] T062 Update .specify/memory/constitution.md §"Reserved paths" to add `<repo-root>/.spaex.md`, `.spaex/constitution.d/`, `.spaex/clarifications.json`, `.spaex/.stale`, `.spaex/composer.log` and align the PATCH-level version bump per Governance §Amendments
- [ ] T063 Remove or refactor any existing writer of `.spaex/constitution.md` (spec-007 D2/D16) so no orphan path remains; run grep across src/ for `constitution.md` and audit hits (research.md §11)
- [ ] T064 Update quickstart.md's per-release manual verification block references to point at the current test suite
- [ ] T065 [P] Bump `spaex.__version__` to 4.2.0 in pyproject.toml and src/spaex/__init__.py
- [ ] T066 [P] Add CHANGELOG.md entry for 4.2.0 covering behavior-harness additions, listing every new FR by number
- [ ] T067 Run the manual verification checklist from quickstart.md §"Manual verification: cross-runtime discoverability" once (SC-007 real-runtime portion); paste observations into the PR description
- [ ] T068 Run the full spaex test suite (uv run pytest) and confirm the compared baseline from T007 plus every new behavior test passes (SC-001 through SC-011 automated portions)
- [ ] T069 Open the PR against main following memory `atoms_pr_flow_required` conventions; PR description references spec 023 and both ADRs

**Checkpoint**: 4.2.0 ready for review, all acceptance criteria verified.

---

## Dependencies (story-level completion order)

Two groups run largely in parallel; the ORDER within each group is fixed by the phase numbering.

**Blocking pipeline (US1 MVP path)**:

```text
Phase 1 (Setup)
  └─ Phase 2 (Foundational)
       └─ Phase 3 (US1 core + bootstrap)
```

**Independent story branches (can start after Phase 2)**:

- Phase 4 (US2), authoring surface, mostly test-only
- Phase 5 (US3), conflict tests (Case A depends on precheck from Phase 2; Case B depends on Composer from Phase 3)
- Phase 6 (US4), clarification flow (depends on Composer from Phase 3)
- Phase 7 (US5), project-local fragments (depends on precheck + materialize + Composer)
- Phase 8 (US6), reproducibility (depends on emit from Phase 3)
- Phase 9 (FR-024a), add-time flow (depends on Composer from Phase 3)

**Polish and CLI (after all user-story phases)**:

- Phase 10 (CLI polish)
- Phase 11 (docs, ADRs, migration, release)

## Parallel-execution examples

Within Phase 2 (Foundational) most tasks are parallelizable:

```text
Run T008, T009, T010, T011, T013, T015, T016, T017 in parallel;
T012 depends on T008; T014 depends on T012.
```

Within Phase 3 (US1) the fault-injection tests are all parallelizable:

```text
Run T022, T023, T024, T025, T026 in parallel after T021.
```

## Implementation strategy

MVP for 4.2.0 is delivered by completing Phase 1, Phase 2, and Phase 3. That yields:

- Fragment authoring (Phase 2 delivers the schema and materialization)
- Composed constitution (`.spaex.md`) written by `spaex install`
- Global bootstrap installable per runtime
- End-to-end and reproducibility tests

Phases 4-8 harden the delivery by covering the remaining user stories with tests and edge behaviors. Phase 9 adds the add-time UX polish (FR-024a). Phase 10 rounds out the CLI. Phase 11 handles docs, version, migration, and PR.

The critical path is Phase 1 → Phase 2 → Phase 3 → Phase 11. All other phases can begin as soon as their dependencies from the critical path complete. Where scheduling requires trimming, Phase 4 (US2 test-only) is the safest cut without weakening the MVP because Phase 2 already provides the machinery.
