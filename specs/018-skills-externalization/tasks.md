---

description: "Task list for consumer-controlled external skill installation"
---

# Tasks: External Skill References

**Input**: Design documents from `specs/018-skills-externalization/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Required by the feature specification and the repository's TDD
workflow. Contract and integration tests are written before implementation.

**Scope**: This task list covers the clarified Phase-A delta: structured
`external_skills` references, the consumer-owned `skill_installation` policy,
and explicit skill-management commands. It does not implement a skills
registry, copy skill files through normal spaex materialization, or build the
later UI phases.

## Phase 1: Setup and artifact alignment

**Purpose**: Make the design artifacts agree before code changes begin.

- [x] T001 Update `specs/018-skills-externalization/plan.md` with the
  structured reference shape, consumer-owned `skill_installation` policy, and
  explicit skill-management lifecycle.
- [x] T002 [P] Synchronize the data model and manifest contract in
  `specs/018-skills-externalization/data-model.md` and
  `specs/018-skills-externalization/contracts/molecule-manifest-external-skills.v1.md`,
  plus `contracts/consumer-manifest-skill-installation.v1.md`.

## Phase 2: Foundational contract work

**Purpose**: Define the schema and runtime boundary shared by all user stories.

- [x] T003 [P] Add structured-reference contract tests in
  `tests/contract/test_molecule_manifest_external_skills.py` for repository,
  full revision SHA, repository-relative path, uniqueness, invalid values, the
  acceptance without a hook (including reference-only molecules), and retired `skill`/`skills` categories.
- [x] T004 [P] Add parser tests in `tests/unit/test_external_skills_parser.py`
  for immutable ordered `ExternalSkillReference` values and backwards
  compatibility when the field is absent.
- [x] T005 Extend
  `src/spaex/schema/data/molecule-manifest.v4.schema.json` with the structured
  `external_skills` object and validation rules while removing the existing
  hook requirement and preserving open atom categories.
- [x] T006 Extend `src/spaex/model/molecule_manifest.py` with a frozen
  `ExternalSkillReference` value object and immutable tuple parsing.

**Checkpoint**: The manifest contract and parser expose structured references,
but no installer side effect is implemented yet.

## Phase 3: User Story 1 - Declare an external skill without copying it (P1)

**Goal**: Preserve repository, revision, and path provenance without treating a
skill as a spaex-delivered atom.

**Independent Test**: Parse and validate a structured reference; confirm it is
available in `MoleculeManifest.external_skills` and absent from atom paths.

### Tests for User Story 1

- [x] T007 [US1] Extend `tests/unit/test_external_skills_parser.py` with
  declaration-order and frozen-value assertions for multiple references.
- [x] T008 [US1] Add a regression fixture in
  `tests/integration/test_external_skill_materialization.py` proving that
  `external_skills` does not enter the materialized file list or
  `install.lock` paths.

### Implementation for User Story 1

- [x] T009 [US1] Update related resolver typing so structured references remain
  metadata only and are not added to materialized paths or install-lock paths.
- [x] T010 [US1] Update `specs/018-skills-externalization/quickstart.md` and
  `README.md` with a co-located `haexmas/atoms` source example using a full
  revision SHA and repository-relative skill path.

**Checkpoint**: User Story 1 is independently testable without Node, registry
access, or skill materialization by spaex.

## Phase 4: User Story 2 - Reject retired skill atom categories (P1)

**Goal**: Prevent publishers from silently continuing to deliver skills through
the old `atoms.skill` or `atoms.skills` categories.

**Independent Test**: Schema validation rejects both retired categories and
continues accepting unrelated open category names.

### Tests and implementation for User Story 2

- [x] T011 [P] [US2] Keep the retired-category and open-category cases in
  `tests/contract/test_molecule_manifest_external_skills.py` explicit and
  independently readable.
- [x] T012 [US2] Run the existing CLI, resolver, and orphan-deletion fixtures
  that previously used `atoms.skills`, preserving their generic-category
  intent in `tests/cli/`, `tests/unit/`, and `tests/integration/`.

**Checkpoint**: User Story 2 is independently testable through contract and
compatibility tests.

## Phase 5: User Story 3 - Let the consumer choose the installation mechanism (P2)

**Goal**: Let the consumer explicitly choose and operate an external skill
installer while spaex remains neutral about the provider's installer choice.

**Independent Test**: A fixture molecule is installed normally and only reports
pending external skills; an explicit skill-install command persists a
consumer-selected policy and invokes a fake adapter with the structured
references.

### Tests for User Story 3

- [x] T014 [P] [US3] Add consumer-manifest contract tests in
  `tests/contract/test_consumer_manifest_skill_installation.py` for policy
  modes, required managed fields, adapter/scope/agent validation, unknown fields,
  and absent-policy behavior.
- [x] T015 [US3] Add CLI integration tests in
  `tests/integration/test_skill_installation_commands.py` proving that normal
  `spaex install` reports pending references without installing and that the
  explicit command persists the consumer policy. Cover disabled mode, prompt
  cancellation/EOF, non-interactive refusal, managed execution, persistence
  failure before adapter launch, configure without removal, and adapter failure.

### Implementation for User Story 3

- [x] T016 [US3] Extend `src/spaex/schema/data/consumer-manifest.v4.schema.json`
  and `src/spaex/model/consumer_manifest.py` with the consumer-owned
  `skill_installation` policy.
- [x] T017 [US3] Add explicit `spaex skills install` and
  `spaex skills configure` command handling in `src/spaex/cli/skills.py`;
  first install prompts only in an interactive session and later configuration
  changes do not remove installed skills implicitly.
- [x] T018 [US3] Add a consumer-selected adapter boundary in
  `src/spaex/skills/installer.py`; keep `skillsmd`, the Vercel CLI, and manual
  installation as adapter choices rather than provider behavior.
- [x] T019 [US3] Pass `SPAEX_MOLECULE_MANIFEST` to the selected adapter in
  `src/spaex/skills/installer.py`, pointing to the original pinned manifest.
  Test this in `tests/integration/test_skill_installation_commands.py` without
  a serialized reference copy. Preserve unrelated Spec 016 hook behavior.

**Checkpoint**: User Story 3 is independently testable with a local fixture;
the real adapter command remains a consumer-selected choice.

## Phase 6: Polish and validation

**Purpose**: Validate the clarified design and leave the task state accurate.

- [x] T020 [P] Update `specs/018-skills-externalization/checklists/requirements.md`
  and `specs/018-skills-externalization/quickstart.md` with the final
  structured-reference and manifest-path acceptance evidence.
- [x] T021 Run focused contract, parser, skill-command, and integration tests;
  then run the full pytest suite, Ruff, mypy, and `git diff --check`. Record
  the exact evidence in this file before marking the tasks complete.
- [x] T022 Review the final diff against `.spaex/constitution.md` and
  `.specify/memory/constitution.md`, confirm no new runtime registry
  dependency was introduced, and update `specs/018-skills-externalization/tasks.md`
  checkboxes in the same commit as each completed task.

## User Story 3 validation evidence (2026-09-23)

- `uv run pytest -q tests/contract/test_consumer_manifest_skill_installation.py`:
  24 passed.
- `uv run pytest -q tests/integration/test_skill_installation_commands.py`:
  13 passed.
- `uv run pytest -q` (full suite): 831 passed, 1 skipped, 5 deselected.
- `uv run ruff check .`: passed.
- `uv run mypy src`: passed (88 source files).
- `git diff --check`: passed.
- Constitution review: `.specify/memory/constitution.md` Principles I-V are
  satisfied (spec/plan/tasks/contracts stay consistent; every task maps to an
  executable test). `.spaex/constitution.md`'s composed MUST/SHOULD clauses
  were checked against the diff; none is contradicted. No new runtime
  dependency was added: `src/spaex/skills/installer.py` and
  `src/spaex/cli/skills.py` use only the Python standard library and existing
  spaex internals (no registry client, no Node/uv/skillsmd dependency).
- Repository-wide `uv run ruff format --check .` still reformats files
  unrelated to this change (same pre-existing condition recorded in the
  Phase 2-4 review, PR #125); no unrelated formatting applied here either.

## Dependencies and execution order

- Phase 1 precedes Phase 2 because schema and parser work must use the
  clarified artifact contract.
- Phase 2 blocks all user-story implementation.
- User Story 1 and User Story 2 can proceed in parallel after Phase 2.
- User Story 3 depends on the structured manifest model from User Story 1 but
  does not depend on User Story 2's category migration fixtures.
- Phase 6 follows all desired user-story work.

## Parallel opportunities

- T002, T003, and T004 can be prepared in parallel after T001.
- T007 and T011 can be prepared in parallel after the foundational tests.
- T014 and T015 can be written in parallel before T016.
- T019 can proceed in parallel with the final implementation review.

## Implementation strategy

1. Land the clarified design and task breakdown for review.
2. Implement the manifest contract and parser first.
3. Implement consumer policy, explicit commands, and the adapter manifest-path
   contract with local integration fixtures.
4. Run the complete validation gates and update task checkboxes eagerly.

The MVP is User Story 1 plus User Story 3: structured references can be
declared and installed through an explicit consumer adapter without spaex materializing skill
content. User Story 2 remains a required compatibility guard for the release.

## Design review validation (PR #125)

- T001/T002 completed: spec, plan, contracts, examples, and dependent roadmap
  text agree on hookless declarations and explicit consumer installation.
- Review fixes define policy-mode behavior, non-interactive refusal, and the
  adapter's original-manifest environment contract. Runtime implementation
  tasks remain open; these checks do not prove the planned commands exist.
- `uv run pytest -q`: 627 passed, 1 skipped, 5 deselected.
- `uv run ruff check .`: passed.
- `uv run mypy src`: passed (72 source files).
- Seven JSON documentation examples parsed; the proposed reference schema
  accepted the quickstart and rejected empty/duplicate lists, opaque strings,
  branch revisions, path traversal, blank repositories, and installer fields.
- `git diff --check`: passed.
- Repository-wide `uv run ruff format --check .`: 100 existing files would be
  reformatted; none is part of this review fix. No unrelated formatting applied.
