---
description: "Tasks for spec 014: rename to spaex and first PyPI release"
---

# Tasks: Rename to spaex (v4 breaking) and first PyPI release

**Input**: Design documents from [`/specs/014-rename-to-spaex/`](./)
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Checkbox freshness is load-bearing.** When a task is completed, tick its checkbox in the same commit as the task's output, or at the latest in the next commit, before starting the next task. Handoff queries ("what was just done, what remains, what is the next step?") read this file's checkbox state as the primary state document; stale ticks systematically drift the answers toward pending items that are secretly done. See [ADR 0004](../../docs/adr/0004-eager-checkbox-update-rule.md).

**Tests are included** because Spec 013 established the contract-plus-integration test pattern for schema-version bumps in this codebase, and the same pattern applies here.

**Phase / User Story mapping** (task phases correspond to design-doc phases):

| Tasks Phase | Design-doc Phase | User Story |
|---|---|---|
| 1 Setup | 1 Schema payloads v4 (dead code) | shared |
| 2 Foundational | 2 Foundational rename | shared |
| 3 US2 | 3 Migrate v3→v4 | US2 |
| 4 US1 | 4 Self-adopt + 5 Docs sweep | US1 |
| 5 US3 | 6 Release workflow + first PyPI push | US3 |
| 6 Polish | (final polish) | shared |

Ordering places US2 before US1 because Phase 4 (US1 self-adoption) uses `spaex migrate` to produce the v4 shape of the repo's own manifests.

**PR-vs-tasks-phase mapping** (revised per Clarification 2026-09-07 Q1). The task phases below are logical execution units; the shipping order combines some of them:

| PR | Contains | Rationale |
|---|---|---|
| PR #1 | Phase 1 | Schema-payloads-only, dead code. |
| PR #2 | Phase 3 (US2 migrate) | Must land before P2+P4 so self-adopt can use `spaex migrate`. |
| PR #3 | Phase 2 + Phase 4 (foundational rename + self-adoption + docs sweep) | Bundled so `main` never sees a state where the repo's own v3 manifests cannot be read by the v4 loader. |
| PR #4 | Phase 5 (release) | Only ships after the repo is coherent under the new name. |
| PR #5 | Phase 6 (polish + directory rename) | Local-directory rename is the very last action, after the session that runs it is deliberately restarted. |

## Format

`- [ ] TXXX [P?] [Story?] Description with file path`

- `[P]`: parallelizable with other `[P]` tasks in the same phase (different files, no dependency on incomplete tasks).
- `[Story]`: US1, US2, US3 map to the user stories in [spec.md](spec.md).

## Path Conventions

Single-project layout (unchanged from Spec 013). `src/haex_hive/` renames to `src/spaex/` in Phase 2. Tests live under `tests/` throughout.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add v4 schema payloads as dead code and bump the dev version. No behavior change; loader continues to dispatch on v3.

- [ ] T001 Copy [specs/014-rename-to-spaex/contracts/consumer-manifest.v4.schema.json](contracts/consumer-manifest.v4.schema.json) to `src/haex_hive/schema/data/consumer-manifest.v4.schema.json` verbatim.
- [ ] T002 [P] Copy [specs/014-rename-to-spaex/contracts/molecule-manifest.v4.schema.json](contracts/molecule-manifest.v4.schema.json) to `src/haex_hive/schema/data/molecule-manifest.v4.schema.json` verbatim.
- [ ] T003 [P] Copy [specs/014-rename-to-spaex/contracts/publisher-manifest.v4.schema.json](contracts/publisher-manifest.v4.schema.json) to `src/haex_hive/schema/data/publisher-manifest.v4.schema.json` verbatim.
- [ ] T004 [P] Copy [specs/014-rename-to-spaex/contracts/install-lock.v4.schema.json](contracts/install-lock.v4.schema.json) to `src/haex_hive/schema/data/install-lock.v4.schema.json` verbatim.
- [ ] T005 Bump [pyproject.toml](../../pyproject.toml) version from `"3.0.0.dev0"` to `"4.0.0.dev0"` and update the `description` field to reference spaex 4.0 vocabulary. Package `name` stays `"haex-hive"` at this point.

**Checkpoint**: v4 schemas are in the package payload; loader still on v3; tests remain green.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Rename the Python package, CLI binary, config filenames, and env var atomically. After this phase the tree builds under the new name; the loader now dispatches on v4; the repo's own on-disk state (`.haex-hive.json`, `manifest.json` v3) becomes momentarily unreadable until Phase 3 delivers the migrate and Phase 4 self-adopts.

**CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T010 `git mv src/haex_hive src/spaex` and update every `from haex_hive.*` and `import haex_hive.*` import in `src/` and `tests/` to `from spaex.*` / `import spaex.*` in the same commit. Tree MUST still import cleanly (`python -c 'import spaex'`).
- [ ] T011 Update [pyproject.toml](../../pyproject.toml): `[project] name = "spaex"`; `[project.scripts] spaex = "spaex.cli.main:main"` (remove the old `haex` entry); `[tool.setuptools.package-data] spaex = ["schema/data/*.json"]`; `[tool.mypy] packages = ["spaex"]`. `pytest.ini_options` and `[tool.setuptools] package-dir` remain unchanged.
- [ ] T012 [P] Rename config-file and directory constants at every site under `src/spaex/`. `grep -R '\.haex-hive\.json' src/spaex/` and `grep -R '\.haex-hive/' src/spaex/` MUST return zero after this task. Replacements: `.haex-hive.json` → `.spaex.json`, `.haex-hive.json.lock` → `.spaex.json.lock`, `.haex-hive/install.lock` → `.spaex/install.lock`, `.haex-hive/pending/` → `.spaex/pending/`, `.haex-hive/` → `.spaex/`.
- [ ] T013 [P] Rename environment variable `HAEX_HIVE_STATE` → `SPAEX_STATE` at every read site under `src/spaex/`. Fallback default path unchanged. `grep -R 'HAEX_HIVE_STATE' src/spaex/` MUST return zero.
- [ ] T014 Rename version-field references in the model classes: `haex_hive_version` → `spaex_version` in `src/spaex/model/consumer_manifest.py`, `molecule_manifest.py`, `publisher_manifest.py`, `install_lock.py`. Bump each class's version const from `"3"` to `"4"`.
- [ ] T015 Rename `haex_hive_min_version` → `spaex_min_version` in `src/spaex/model/consumer_manifest.py`. Semantic rewrite rules stay in the migrate module; this task only renames the model field.
- [ ] T016 Update `src/spaex/schema/loader.py` so every read path accepts only `spaex_version: "4"` for consumer, publisher, molecule, and install-lock manifests. Any other value raises a diagnostic with refusal key `spaex-version-unsupported` that names `spaex migrate` as the next step. The migrate module remains the only reader that understands older versions.
- [ ] T017 Update `src/spaex/schema/validator.py` (or equivalent) to dispatch on v4 schema files by manifest kind. Remove v3-specific branches from the main path.
- [ ] T018 Convert every v3 test fixture under `tests/` to v4 shape. `grep -R '"haex_hive_version": "3"' tests/` and `grep -R '"haex_hive_min_version"' tests/` MUST return zero. Preserve semantic intent; only field names change.
- [ ] T019 Confirm `pytest -m 'not slow'` is green post-rename. The repo's own `.haex-hive.json` and manifests are still v3 on disk but tests do not read them.

**Checkpoint**: The tool answers to `spaex`, imports as `spaex`, reads v4 manifests only, and every test that constructs its own inputs passes. The repo's own on-disk state is inconsistent until Phase 4.

---

## Phase 3: User Story 2 - `spaex migrate` covers v3 → v4 (Priority: P1)

**Goal**: Extend the migrate chain so `spaex migrate` reads v1/v2/v3 inputs and emits v4 proposals as `.migrated` siblings with adoption instructions.

**Independent Test**: Take a fixture v3 repo (consumer + publisher + one molecule). Run `spaex migrate`. Confirm three `.migrated` sibling files are produced. Adopt them per the printed instructions. Run `spaex install`. Confirm `.spaex/install.lock` validates as v4 and is byte-identical across two runs.

### Tests for User Story 2

- [ ] T020 [P] [US2] Unit tests in `tests/unit/test_migrate_consumer_v3_to_v4.py` for the consumer transform: `haex_hive_version: "3"` becomes `spaex_version: "4"`; `haex_hive_min_version: "3.2.0"` becomes `spaex_min_version: "4.2.0"`; `>=3.2.0` becomes `>=4.0.0`; `~2.0.0` refuses with `unsupported-min-version-constraint("~2.0.0")`.
- [ ] T021 [P] [US2] Unit tests in `tests/unit/test_migrate_publisher_v3_to_v4.py`: `molecules{}` map preserved byte-for-byte modulo the version-field rename; `publisher` field preserved.
- [ ] T022 [P] [US2] Unit tests in `tests/unit/test_migrate_molecule_v3_to_v4.py`: `atoms{}` category map preserved byte-for-byte; `id`, `version`, `priority`, `defaults`, `config_schema` all preserved.
- [ ] T023 [P] [US2] Unit tests in `tests/unit/test_migrate_v3_v4_chain.py`: idempotency on v4 inputs (no proposals); chained transform from v1 or v2 input reaches v4 in one invocation; determinism (two runs with identical input emit bit-for-bit identical output); install.lock inputs are skipped (runtime output, not a migration target).
- [ ] T024 [P] [US2] Integration test in `tests/integration/test_migrate_v3_to_v4_end_to_end.py`: fixture v3 repo (consumer + publisher + one molecule); `spaex migrate` emits `.spaex.json.migrated` and two `manifest.json.migrated` siblings; adopting each and running `spaex install` produces valid `.spaex/install.lock` with `spaex_version: "4"`.

### Implementation for User Story 2

- [ ] T030 [US2] Extend `src/spaex/migrate/transform.py` with `v3_to_v4(parsed, kind)` per the contract in [contracts/spaex-migrate.v3-to-v4.md](contracts/spaex-migrate.v3-to-v4.md). Dispatch by shape (consumer, publisher, molecule). Preserve v1_to_v2 and v2_to_v3 unchanged.
- [ ] T031 [US2] Implement the min-version rewriter for the v3→v4 leg in `src/spaex/migrate/transform.py`: exact `3.X.Y` → `4.X.Y`; lower-bound `>=3.X.Y` → `>=4.0.0`; any other form refuses with `unsupported-min-version-constraint` naming the offending constraint. No proposal for the offending file.
- [ ] T032 [US2] Extend `src/spaex/cli/migrate.py` so the chain reaches v3→v4. On v4 inputs, short-circuit per input (idempotency). Preserve `--dry-run` and `--check` semantics.
- [ ] T033 [US2] Implement filename-target map in `src/spaex/cli/migrate.py`: v3 `.haex-hive.json` produces sibling `.spaex.json.migrated`; publisher and molecule `manifest.json` produce sibling `manifest.json.migrated`; `.haex-hive/install.lock` is skipped.
- [ ] T034 [US2] Update the migrate CLI's printed adoption instructions to reference spaex filenames per [contracts/spaex-migrate.v3-to-v4.md](contracts/spaex-migrate.v3-to-v4.md): `mv .spaex.json.migrated .spaex.json && rm .haex-hive.json` for consumers; `mv manifest.json.migrated manifest.json` for publisher and molecule; `rm -rf .haex-hive/  # regenerated by spaex install` note for runtime state.
- [ ] T035 [US2] Preserve exit-code precedence in `src/spaex/cli/migrate.py`: 2 for hard refusal without any proposal, 1 for mixed proposal-plus-refusal, 0 for success or all-v4 no-op.

**Checkpoint**: `spaex migrate` produces v4 proposals from v3 inputs; the repo's own manifests are still v3 on disk but can now be migrated.

---

## Phase 4: User Story 1 - Operator uses the new brand end to end (Priority: P1) 🎯 MVP

**Goal**: The repo self-adopts to v4 shape, the constitution is amended (prose-only, PATCH bump), the docs are swept, and the ADR lands. Every user-visible surface uses the new name.

**Independent Test**: After Phase 4 completes, `spaex install` on the repo produces byte-identical `.spaex/install.lock` across two runs. `rg 'haex[_-]hive'` and `rg '\bhaex\b'` find no live references in `src/`, `tests/`, `pyproject.toml`, `README.md`. Historical references remain in `docs/adr/`, `docs/plans/`, `specs/` by design.

### Tests for User Story 1

- [ ] T040 [P] [US1] Contract test in `tests/contract/test_consumer_manifest_v4.py`: valid v4 shape passes; `spaex_version: "3"` fails; unknown top-level property fails; duplicate molecule id within one compound's `molecules[]` fails.
- [ ] T041 [P] [US1] Contract test in `tests/contract/test_molecule_manifest_v4.py`: `atoms{category: [paths]}` shape passes; empty category array fails; cross-category path overlap fails (via runtime check); missing `priority` fails.
- [ ] T042 [P] [US1] Contract test in `tests/contract/test_publisher_manifest_v4.py`: `molecules{}` map passes; missing `spaex_version` fails; legacy `haex_hive_version` key fails.
- [ ] T043 [P] [US1] Contract test in `tests/contract/test_install_lock_v4.py`: `molecules[]` array passes with `moleculeEntry` items; unknown root property fails; retired top-level fields (`generated_by`, `constitution`, `participating_roots`, `generation_inputs`) rejected.
- [ ] T044 [P] [US1] Integration test in `tests/install/integration/test_install_lock_byte_identical_v4.py`: `spaex install` on a fixture repo twice; assert byte-identical `.spaex/install.lock` output.
- [ ] T045 [P] [US1] Integration test in `tests/install/integration/test_install_refuses_v3_after_rename.py`: v3 `.haex-hive.json` or `manifest.json` refuses with `spaex-version-unsupported` diagnostic naming `spaex migrate`.

### Implementation for User Story 1 (self-adoption)

- [ ] T050 [US1] Run `spaex migrate` against the repo root. Adopt every `.migrated` sibling: `mv .spaex.json.migrated .spaex.json`, `rm .haex-hive.json`; `mv manifest.json.migrated manifest.json` for the publisher-root manifest; same for `.specify/memory/manifest.json`. Commit in one atomic change.
- [ ] T051 [US1] Rewrite `.specify/memory/constitution.md`: change the title from `# haex-hive Constitution` to `# spaex Constitution`; update all 18 prose references to `haex-hive`, `haex`, and `.haex-hive.json` to the new names. Principle text (invariants) MUST be byte-identical to the pre-rename version except for prose references. Diff review confirms.
- [ ] T052 [US1] Bump constitution version in the file's version line at the bottom from `**Version**: 1.4.0` to `**Version**: 1.4.1` and update `**Last Amended**`. Update the Sync Impact Report block at the top of the constitution with an entry: version change 1.4.0 → 1.4.1 (PATCH: rename to spaex prose amendment); modified sections list; ADR reference to `docs/adr/0011-rename-to-spaex.md`.
- [ ] T053 [US1] Delete legacy `.haex-hive/` directory in the repo root (runtime state). Run `spaex install` locally.
- [ ] T054 [US1] Run `spaex install` a second time. Confirm byte-identical `.spaex/install.lock` output vs. the first run. Commit the resulting `.spaex/install.lock`.

### Implementation for User Story 1 (docs sweep)

- [ ] T055 [P] [US1] Rewrite [README.md](../../README.md) per spec FR-041 through FR-044 and the plan's README-Rewrite section. Header: `# spaex — reproducible coding harnesses for any repo and development environment`. What-it-is paragraph. Verb list. Generic atom-categories-are-open paragraph per the updated FR-043 (Spec 014 makes no naming commitment for environment-config files; forward-reference Spec 015 for multi-environment declaration and orchestration). Install paragraph with `pipx install spaex`. Migration-from-v3 paragraph. Multi-device vision as one line pointing at holzi.
- [ ] T056 [P] [US1] Sweep every remaining `haex-hive`, `haex_hive`, `haex`, `HAEX_HIVE`, `.haex-hive` reference in `.github/workflows/*.yml`, `pyproject.toml` (if any survived), any root-level docs (`CLAUDE.md`, `AGENTS.md` if they appear). Live references MUST be gone. Historical references in `docs/adr/`, `docs/plans/`, `specs/` remain.
- [ ] T057 [US1] Add [docs/adr/0011-rename-to-spaex.md](../../docs/adr/0011-rename-to-spaex.md) with the standard ADR template. Records the rename decision, links [Spec 014](spec.md), notes the PATCH constitution bump, and lists Follow-ups: Slot 015 (dev-env orchestration), memory-file sweep.
- [ ] T058 [US1] Run full test suite: `pytest -m 'not slow'`. Confirm green.

**Checkpoint**: Repo self-adopted to v4. Constitution amended (PATCH 1.4.1). README and ADR reflect the new brand. `rg 'haex[_-]hive' src/ tests/ pyproject.toml README.md` returns zero. MVP complete: an operator on this branch can use spaex end to end.

---

## Phase 5: User Story 3 - Public availability via pipx (Priority: P2)

**Goal**: First PyPI release of `spaex 4.0.0` via GitHub Actions and OIDC Trusted Publishing. `pipx install spaex` succeeds from PyPI.

**Independent Test**: On a machine with `pipx` and Python 3.10+, run `pipx install spaex`. Confirm `spaex --version` reports `4.0.0`. Run `spaex --help`. In an empty directory, create a minimal `.spaex.json` and run `spaex install`. Confirm normal end-to-end behavior.

- [ ] T060 [US3] Create [.github/workflows/release.yml](../../.github/workflows/release.yml) per [contracts/release-workflow.md](contracts/release-workflow.md). Include the `build` and `publish` jobs, the `pypi` environment reference, and `id-token: write` permission.
- [ ] T061 [US3] Verify PyPI Trusted Publisher pending-publisher config is in place for project `spaex`, owner `haexmas`, repository `spaex`, workflow filename `release.yml`, environment `pypi`. (Maintainer confirmed 2026-09-07; T061 is a spot-check before tagging.)
- [ ] T062 [US3] On `main` (after PR merges land), bump [pyproject.toml](../../pyproject.toml) version from `"4.0.0.dev0"` to `"4.0.0"`. Commit as `chore(release): 4.0.0`.
- [ ] T063 [US3] `git tag v4.0.0 && git push origin v4.0.0`. Workflow triggers.
- [ ] T064 [US3] If the `pypi` GitHub Environment has a required-reviewer gate, approve the publish job in the GitHub Environments UI. Wait for the publish job to complete.
- [ ] T065 [US3] Confirm PyPI project page at `https://pypi.org/project/spaex/` shows `spaex 4.0.0` with sdist plus wheel artifacts.
- [ ] T066 [US3] On a scratch machine or fresh venv: `pipx install spaex`; confirm `spaex --version` reports `4.0.0`; run through the [quickstart.md](quickstart.md) Adopt-a-molecule flow against a fixture publisher.
- [ ] T067 [US3] On `main`, bump [pyproject.toml](../../pyproject.toml) version from `"4.0.0"` to `"4.0.1.dev0"`. Commit as `chore(release): open 4.0.1 cycle`.
- [ ] T068 [US3] Create GitHub Release: `gh release create v4.0.0 --generate-notes`. Confirm the release page renders correctly at `https://github.com/haexmas/spaex/releases/tag/v4.0.0`.

**Checkpoint**: `pipx install spaex` works from PyPI. First release is live and reproducible.

---

## Phase 6: Polish and cross-cutting concerns

**Purpose**: Verify success criteria, sweep memory files, walk the quickstart end to end.

- [ ] T070 [P] Grep sweep: `rg 'haex[_-]hive' src/ tests/ pyproject.toml README.md .github/` and `rg '\bhaex\b' src/ tests/ pyproject.toml README.md .github/` MUST return zero. Historical references in `docs/adr/`, `docs/plans/`, `specs/` are documented as exempt in [spec.md](spec.md) SC-006 and remain untouched.
- [ ] T071 [P] Memory-file sweep: rename `~/.claude/projects/-home-haex-Projekte-haex-hive/memory/haex_hive_*.md` files to `spaex_*.md`; update `MEMORY.md` index entries; update memory-file content that references `haex-hive` to `spaex`. Directory path itself (`-home-haex-Projekte-haex-hive`) is a Claude Code implementation detail keyed by the working directory; unchanged.
- [ ] T072 Walk [quickstart.md](quickstart.md) end to end against a scratch project on a fresh machine (or a container). Every command works as documented. Every refusal-key row in the table is reachable via the documented failure mode. Any wording drift is fixed in the same task.
- [ ] T073 [P] Confirm [SC-001](spec.md) through SC-010 are all satisfied. If any fails, open a follow-up task in this file (do not silently pass).
- [ ] T074 GitHub-repo rename: through the GitHub UI, rename `haexmas/haex-hive` → `haexmas/spaex`. GitHub configures the redirect automatically. Update the repo description to reference the current identity.
- [ ] T075 Merge the feature branch. Per Clarification 2026-09-07 Q1, land as **five PRs** against `main` (see the PR-vs-tasks-phase mapping above). Delete the feature branch after landing.
- [ ] T076 **RUN AFTER SESSION CLOSE**: Rename the local repository directory: `mv /home/haex/Projekte/haex-hive /home/haex/Projekte/spaex`. Also copy the Claude Code memory directory: `cp -r ~/.claude/projects/-home-haex-Projekte-haex-hive ~/.claude/projects/-home-haex-Projekte-spaex`. Then open a new shell in the new path. Do NOT run this task while any shell, IDE, Claude Code session, or file watcher has the old directory as its cwd; renaming the cwd out from under a running process breaks it. Per Clarification 2026-09-07 Q2.

---

## Dependencies and Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies; can start immediately.
- **Foundational (Phase 2)**: depends on Setup; blocks all user-story work.
- **US2 (Phase 3)**: depends on Foundational.
- **US1 (Phase 4)**: depends on Foundational AND on US2 (because T050 uses `spaex migrate`). This is a deliberate deviation from strict story-independence; the rename is inherently structural and the self-adopt step needs the migrate to exist.
- **US3 (Phase 5)**: depends on US1 (release cannot ship until the repo is coherent under the new name). Also depends on the previous PRs having landed on `main`.
- **Polish (Phase 6)**: depends on US1, US2, US3.

### Parallel opportunities

- **Phase 1**: T002, T003, T004 all `[P]` (different files).
- **Phase 2**: T012, T013 `[P]` (different concerns: filenames vs env var).
- **Phase 3**: T020-T024 all `[P]` (different test files).
- **Phase 4 tests (T040-T045)**: all `[P]`. T055 (README) and T056 (misc-file sweep) `[P]`.
- **Phase 6**: T070, T071, T073 `[P]`.

### Within each user story

- Tests are written before implementation and MUST fail against the pre-implementation tree (Phase 3 tests fail without T030-T035; Phase 4 tests fail without T050-T057).
- Contracts before adoption: schemas (Phase 1) exist before Phase 2's loader change.
- Foundational rename before any user story: Phase 2 completes fully before Phase 3 starts.

## Implementation Strategy

### MVP scope

**Phase 1 + Phase 2 + Phase 3 + Phase 4** deliver the MVP: renamed, self-adopted, migrate available. `pipx install .` from a checkout works even if PyPI is not yet published.

### Suggested PR sequence (six phase-PRs per design source)

1. Phase 1 tasks (T001-T005) → PR #1.
2. Phase 2 tasks (T010-T019) → PR #2.
3. Phase 3 tasks (T020-T035) → PR #3.
4. Phase 4 tasks (T040-T058) → PR #4. This is the "brand end to end" PR.
5. Phase 5 tasks (T060-T068) → PR #5 (release setup + first push).
6. Phase 6 tasks (T070-T075) → PR #6 (polish, memory sweep, GH repo rename).

Each PR targets `main`, not the previous phase branch (memory `pr_strategy_stacked_phases`).

### Parallel work strategy

Within a phase, tasks marked `[P]` can be batched across sub-agents or worked on in parallel by different developers. Between phases, work is sequential.

## Notes

- `[P]` tasks operate on different files with no dependency on incomplete tasks.
- `[Story]` label maps a task to a user story for traceability.
- User Story 1 depends on User Story 2 by construction (see Phase dependencies above).
- The v3→v4 transform is pure and deterministic per Principle VI (T030 contract).
- The constitution amendment is prose-only PATCH 1.4.0 → 1.4.1 (T051, T052).
- Historical references in `docs/adr/`, `docs/plans/`, `specs/` remain by design as historical record; the SC-006 sweep is scoped to live code, tests, and top-level docs only.
