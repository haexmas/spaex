# Implementation Plan: Reliable Fragment Composition

**Branch**: `026-reliable-fragment-composition` | **Date**: 2026-09-16 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/026-reliable-fragment-composition/spec.md`

## Summary

Replace the Composer's single-shot, whole-fragment-set LLM call with a bounded, deterministic **map-reduce composition**: partition the resolved fragment set into fixed-size batches, compose each batch independently with the existing single-call Composer machinery (reused unchanged), then merge the batches' composed output into one final document with a dedicated merge step that re-checks for cross-batch contradictions before publishing. Batch size stays constant regardless of how many molecules are adopted, so no individual LLM call's input grows unbounded with scale — only the number of batches does, and a bounded pairwise merge tree handles merge inputs that exceed the flat-merge ceiling. The existing single-call path degenerates to "one batch, no merge needed" and is preserved byte-for-byte for the common small case (SC-004).

## Technical Context

**Language/Version**: Python 3.14 (existing `spaex` codebase, `requires-python = ">=3.14,<3.15"`)
**Primary Dependencies**: None new. Reuses `subprocess` (existing CLI shell-out to `claude`/`codex`/`gemini`), the existing `spaex.behavior.composer.*` package.
**Storage**: Filesystem only — `.spaex/composer.log` (extended to hold one entry per internal step, see Key Entities), `.spaex/constitution.md`, `.spaex/constitution.d/`, `.spaex/clarifications.json` (all pre-existing).
**Testing**: pytest, via the existing `InvokeOptions.stub_caller` fault-injection seam (`tests/behavior/fault_injection/`, `tests/behavior/unit/`, `tests/behavior/integration/`) — no real subprocess calls in tests, consistent with the existing suite.
**Target Platform**: Wherever `spaex install` already runs today (Linux/macOS/WSL2 dev machines and CI, per the project's own no-local-absolute-paths constitution principle).
**Project Type**: Single Python library/CLI (existing `spaex` project layout, no new top-level project).
**Performance Goals**: SC-002 — a successful composition completes well under 20 minutes even at scale, reliability prioritized over raw speed; SC-004 — no regression for a fragment set that already composed in one call today.
**Constraints**: FR-011 — one CLI runtime selected once and used for every internal step of a composition run. FR-003/SC-003 — byte-reproducible output for an unchanged fragment set. FR-004 — non-destructive on any failure (existing `orchestrate.py` staging/rollback already provides this at the outer level and needs no redesign, only to keep wrapping the whole multi-step attempt as one unit).
**Scale/Scope**: No fixed ceiling on adopted molecule/fragment count (FR-001, FR-007). Today's confirmed floor: 9 molecules, ~60KB combined fragment content.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Checked against `.specify/memory/constitution.md` (Spec Kit constitution) and the spaex behavior-harness constitution composed at `.spaex/constitution.md`:

- **I. Specifications Are the Product Contract** — spec.md states user-visible behavior (install succeeds reliably), scope, and testable acceptance scenarios. PASS.
- **II. Plans Must Be Traceable** — this plan maps every FR (FR-001..FR-012) to a concrete design element in Phase 0/1 below; no unresolved ambiguity remains post-`/speckit.clarify`. PASS.
- **III. Cross-Artifact Consistency** — Phase 1 artifacts (data-model.md, contracts/) are derived directly from spec.md's entities and the existing composer-interface.md contract they extend, not invented independently. PASS.
- **IV. Tasks Must Be Independently Verifiable** — deferred to `/speckit-tasks`; this plan's Project Structure section identifies the concrete test seams (fault-injection, unit, integration) each task will need. PASS (verifiable at task-generation time).
- **V. Scope Is Explicit** — spec.md's Assumptions section states this feature is scoped to Composer reliability at scale only, not runtime selection or prompt authoring generally. PASS.
- **spaex constitution — graphify-first authoring** (`.spaex/constitution.md`): this plan was produced after consulting the existing `spaex.behavior.composer` package structure and the composer-interface contract directly (see Phase 0 research below) rather than authoring a parallel design blind to the current implementation. PASS.
- **spaex constitution — PR-required-for-main / worktree requirement**: this feature is being authored on branch `026-reliable-fragment-composition` inside a dedicated worktree (`.worktrees/composer-reliable-multi-fragment-merge`), per the general-coding molecule's MUST. PASS.

No violations requiring the Complexity Tracking table.

**Post-Phase-1 re-check**: research.md and data-model.md introduce two new modules (`batching.py`, `reduce.py`) and extend `.spaex/composer.log`'s format. Neither is a new top-level project, a new tracked/versioned config schema (the log stays an ephemeral, gitignored scratch file, not one of the versioned artifacts the self-modifying-instructions-review-gated principle covers), nor a change to any existing MUST-level contract beyond what `contracts/batch-merge-composer-interface.md` documents as additive. PASS, no new violations.

## Project Structure

### Documentation (this feature)

```text
specs/026-reliable-fragment-composition/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── batch-merge-composer-interface.md   # Phase 1 output — extends specs/023-behavior-harness/contracts/composer-interface.md
└── tasks.md             # Phase 2 output (/speckit-tasks, not this command)
```

### Source Code (repository root)

Single existing Python project; no new top-level project. This feature is additive within the existing `spaex.behavior.composer` package:

```text
src/spaex/behavior/
├── composer/
│   ├── invoke.py          # CORE UNCHANGED: _call_cli, _parse, sentinel contract, single-call invocation; log lifecycle gains per-attempt/per-invocation records
│   ├── failure.py          # UNCHANGED: five typed failure categories, exit codes 30-34
│   ├── prompt.py           # EXTENDED: existing compose prompt (unchanged) + new merge-step prompt constant
│   ├── batching.py         # NEW: deterministic fragment→batch partitioning (pure function, no I/O)
│   └── reduce.py           # NEW: batch dispatch + merge orchestration; the only new caller of invoke.py's single-call machinery
└── orchestrate.py          # CHANGED: replace the single `invoke_composer(...)` call with a call into composer/reduce.py's multi-step entry point; _verify_completeness, staging/rollback, emit.py all unchanged

tests/behavior/
├── unit/
│   ├── test_batching.py           # NEW: partitioning determinism, boundary sizes, oversized-molecule failure, single-batch degenerate case
│   ├── test_composer_log_format.py # NEW: attempt truncation, append-only entries, clarification round-trip retention
│   └── test_reduce.py             # NEW: batch dispatch + bounded merge-tree orchestration against stub_caller
├── fault_injection/
│   └── test_reduce_partial_failure.py  # NEW: a later batch/merge step fails after earlier ones succeeded - non-destructive + per-step log preservation
└── integration/
    └── test_composition_scales.py      # NEW: fragment count well beyond one batch composes correctly end-to-end via stub_caller
```

**Structure Decision**: Extend the existing single-project layout (`src/spaex/behavior/composer/`, `tests/behavior/`) with two new modules (`batching.py`, `reduce.py`) and prompt/log additions. No new package, service, or project boundary — this is an internal reliability change to one existing subsystem, consistent with the project's existing single-library structure.

## Complexity Tracking

*No Constitution Check violations. Table not applicable.*
