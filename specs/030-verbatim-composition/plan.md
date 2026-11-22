# Implementation Plan: Verbatim Constitution Composition

**Branch**: `030-verbatim-composition` | **Date**: 2026-11-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/030-verbatim-composition/spec.md`

## Summary

spaex writes the composed constitution itself: every fragment body verbatim, in scoped-id order, in a new format version 2. The language model no longer composes. It runs one **check** over numbered fragment lines and returns findings (contradictions or duplicates, each naming passages as fragment id plus line range) or nothing. spaex verifies the named passages, asks the operator about every finding, persists the answer as a **decision** bound to the passages' exact text, and applies it by commenting out the passages that are not kept. The output is a pure function of fragments and decisions, so a rerun, a deleted file or a second machine reproduces it byte for byte without a model call. The map-reduce composer of spec 026, the clause grammar, the citation-based completeness check and the `.stale` plausibility marker are removed; `trace`, `status`, `build --check`, the bootstrap block and the docs move to the fragment-level format.

## Technical Context

**Language/Version**: Python 3.14 (`requires-python = ">=3.14,<3.15"`)

**Primary Dependencies**: None new. Stdlib (`json`, `hashlib`, `re`, `dataclasses`, `pathlib`) and the existing runtime-invocation machinery (`composer/invoke.py`: runtime selection, timeout, log, stub caller).

**Storage**: Files only. Changed: `.spaex/constitution.md` (format version 2, also `.spaex/local/constitution.md`). New: `.spaex/decisions.json` (and `.spaex/local/decisions.json`). Removed on first v2 install: `.spaex/clarifications.json`, `.spaex/.stale`.

**Testing**: `pytest` with the existing layout (`tests/behavior/{unit,integration,fault_injection}`, `tests/cli`); the model is replaced by `InvokeOptions.stub_caller`, the operator by an injected decision callback. `ruff` and `mypy` as configured in `pyproject.toml`.

**Target Platform**: Linux, macOS, WSL2 CLI, unchanged.

**Project Type**: Single Python CLI project (`src/spaex` + `tests/`).

**Performance Goals**: Install with unchanged fragments and decisions does no model call and renders in well under one second for the haex-vault set (about 60 KB). A check on that set is one model call whose output is small, so it is not exposed to the output-length timeouts that motivated spec 026.

**Constraints**: Byte-identical output for equal fragments and decisions (FR-004); no tracked file changes on any failure (FR-019); the model can never change text (FR-003, FR-006); decisions are asked, never defaulted (FR-008).

**Scale/Scope**: Single digits to low tens of molecules, up to about 1000 lines of fragments per consumer. Larger sets are checked in partitions that cover every pair (research R6).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` and the composed `.spaex/constitution.md`.

| Principle / Rule | Status | Notes |
|---|---|---|
| Specifications are the product contract | PASS | spec.md with clarified decisions (session 2026-11-22). |
| Plans are traceable | PASS | Every FR maps to a research decision: FR-001–004 → R1, R2; FR-005 → R5; FR-006, FR-007 → R3, R4; FR-008–011 → R7, R8; FR-012 → R9; FR-013 → R10; FR-014 → R2; FR-015, FR-016 → R11, R12; FR-017 → R13; FR-018 → R14. |
| Work in a dedicated worktree on a topic branch, PR required for `main` | PASS | `.worktrees/030-verbatim-composition`; spec, plan and tasks go in as a docs PR, code in separate PRs. |
| Conventional commits, version bump follows semver | PASS | Code PR uses a breaking-change commit; the release process proposes the major version (R14). |
| Amendments mirror fragments in the same commit | PASS | No fragment or constitution change in this feature. |
| Phasing discipline | PASS | Foundation, then one user story per PR (tasks.md). |
| Cross-repo references pin immutable revisions | PASS | Consumers (atoms, haex-vault) are updated by their own PRs after release, with pinned SHAs. |
| No local absolute paths, no secrets | PASS | Nothing written outside `.spaex/`. |

Post-design re-check: PASS. The breaking change is intentional and documented (ADR 0028, contracts).

## Project Structure

### Documentation (this feature)

```text
specs/030-verbatim-composition/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── spaex-md-format-v2.md
│   ├── check-interface.md
│   ├── decisions-schema.md
│   └── cli-surface-delta.md
└── tasks.md
```

### Source Code (repository root)

```text
src/spaex/behavior/
├── render.py              # NEW  render / parse / verify the v2 document (R1, R2)
├── passages.py            # NEW  Passage, locate, validate ranges (R3)
├── decisions.py           # NEW  store, keys, invalidation, checked state (R5, R8)
├── composer/
│   ├── check.py           # NEW  CheckInput, findings parser, single and pairwise runs (R4, R6)
│   ├── prompt.py          # CHANGED  CHECK_PROMPT replaces the compose and merge prompts
│   └── invoke.py          # CHANGED  parser is a parameter of invoke_step
├── orchestrate.py         # CHANGED  render, check, ask, decide, publish
├── emit.py                # CHANGED  header v2, hashes, atomic write of rendered text
├── fragment.py            # unchanged
├── precheck.py            # unchanged (identical-body dedupe stays)
└── (removed)              # composer/reduce.py, composer/clarify.py, composer/clarifications.py,
                           # composer/completeness.py, clauses.py, stale.py
src/spaex/cli/
├── behavior_commands.py   # CHANGED  build, --check, --force, trace
├── install.py, add.py     # CHANGED  no plausibility mode, no .stale
src/spaex/report/          # CHANGED  compose.py (summary), staleness.py (state)
src/spaex/install/local_publish.py   # CHANGED  same pass for the local document
docs/adr/0028-verbatim-composition.md  # NEW, supersedes 0022–0025
tests/behavior/…           # new unit and integration tests; obsolete ones removed
```

**Structure Decision**: Single project. The composer package keeps only what talks to the model; everything that decides text lives in `render.py`, `passages.py` and `decisions.py`, which have no model dependency and are unit-testable without a stub.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| Line-range passages instead of whole fragments | Fragments hold 10 to 30 rules; a duplicate is one rule. | Excluding whole fragments would drop unrelated rules, which is the defect this spec removes. |
| Decisions bound to passage text, not to line numbers | Line numbers move when a fragment changes elsewhere. | Line-bound decisions would be asked again after every unrelated edit. |
