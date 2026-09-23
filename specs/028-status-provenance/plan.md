# Implementation Plan: Composition Status and Provenance Query

**Branch**: `028-status-provenance` | **Date**: 2026-09-22 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/028-status-provenance/spec.md`

## Summary

Today an operator can only learn what a repo's spaex composition contains by reading `.spaex/manifest.json`, `.spaex/install.lock` and the generated files by hand. This adds two read-only CLI commands: `spaex status`, which summarizes every pinned/installed molecule, what each one's atoms materialized into, the composed constitution, and any drift between manifest/lock/constitution; and `spaex trace <path>`, which answers "which molecule wrote this file" at file granularity (complementing the existing clause-level `spaex constitution trace`). Both commands derive every fact from data already committed to the repository — `.spaex/manifest.json`, `.spaex/install.lock`, `.spaex/constitution.d/`, `.spaex/constitution.md`, and generated artifacts — never from a molecule's own manifest or the local molecule cache, so both work identically in a fresh clone with no network access (2026-09-22 clarification; research.md R1). Both support `--format text|json`, the JSON form carrying a `format_version` for the future GUI (roadmap Phase D) to consume.

## Technical Context

**Language/Version**: Python 3.14 (`requires-python = ">=3.14,<3.15"`, matches the rest of the codebase)
**Primary Dependencies**: None new. Uses only already-imported stdlib (`json`, `re`, `pathlib`, `dataclasses`) and existing internal modules (`spaex.model.consumer_manifest`, `spaex.model.install_lock`, `spaex.behavior.fragment`, `spaex.behavior.emit`, `spaex.behavior.composer.prompt`, `spaex.behavior.composer.clarifications`).
**Storage**: Filesystem only, read-only. `.spaex/manifest.json`, `.spaex/install.lock`, `.spaex/constitution.d/**/*.md`, `.spaex/constitution.md`, `.spaex/composer-prompt.md` (optional), `.spaex/clarifications.json` (optional). No new file is written or read outside this existing set; no local molecule cache or network access (FR-002, research.md R1/R4).
**Testing**: `pytest` (existing suite layout: `tests/unit/`, `tests/integration/`, `tests/behavior/{unit,integration}/`). New tests follow `tests/behavior/integration/test_provenance_trace.py`'s established pattern for `constitution trace` — hand-written `.spaex/` fixtures on disk, no git/molecule resolution needed, since both new commands read the same kind of already-materialized state.
**Target Platform**: Linux/macOS/WSL2 CLI tool (existing spaex target); no OS-specific path assumption (constitution `no-local-absolute-paths` rule).
**Project Type**: Single Python CLI project (existing `src/spaex` package + `tests/`).
**Performance Goals**: SC-001 — under 5 seconds for `spaex status` on this repository's current 8-molecule composition. Both commands are in-process filesystem reads and string/JSON parsing on small inputs (single-digit-to-low-tens of molecules, a few dozen fragment files); no scaling concern comparable to the `behavior` Composer's LLM calls.
**Constraints**: Read-only (FR-002); MUST NOT touch the local molecule cache or network, which rules out reusing `spaex constitution build --check`'s molecule-resolution path as-is (research.md R4). Output MUST be OS-independent and reproducible byte-for-byte for identical repository content (FR-013, research.md R8).
**Scale/Scope**: Bounded by adopted-molecule count and constitution clause count already in play elsewhere in this codebase (single digits to low tens); no new scale dimension.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` (Spec-Kit layer) and the pinned `.spaex/constitution.d/` atoms (spaex policy layer):

| Principle / Rule | Status | Notes |
|---|---|---|
| I. Specifications Are the Product Contract | PASS | spec.md covers scope, constraints, acceptance scenarios; the one raised clarification (atom grouping, research.md R1) is resolved before planning. |
| II. Plans Must Be Traceable | PASS | Every FR in spec.md maps to a research.md decision and a data-model.md entity; the one ambiguity research.md surfaced during planning (FR-007's constitution-staleness reuse, R4) is resolved and reflected back into spec.md's Assumptions. |
| III. Cross-Artifact Consistency Is Required | PASS (ongoing) | spec.md's "Constitution freshness" Assumption was corrected during planning to name the actual local-only recomputation (research.md R4) instead of implying reuse of `constitution build --check`'s molecule-resolving path. |
| IV. Tasks Must Be Independently Verifiable | Deferred to `/speckit-tasks` | Not yet generated; this plan's contracts/data-model give each future task an observable outcome (a CLI exit code and output shape) to verify against. |
| V. Scope Is Explicit | PASS | spec.md's Assumptions explicitly bound scope (no GUI, no `--check`-style gating exit code, no new install-lock fields, no atom-category names surfaced). |
| `graphify-first-authoring` (MUST) | PASS | Consulted before naming new modules; research.md R6 records three evaluated-and-rejected candidates (`constitution/show.py`, `behavior/bootstrap.py`'s `install()`, `install/delta.py`) and R5 reuses `constitution trace`'s existing clause parser instead of writing a second one. |
| `general-coding` size/reuse rules (MUST/SHOULD) | PASS | New modules are single-purpose (composition report, file trace, offline staleness check); none is expected to approach the 500-LoC boundary. No speculative abstraction introduced beyond what R1-R6 require. |
| Repository-local worktree + topic branch (MUST) | PASS | This plan is authored on branch `028-status-provenance` inside the `.worktrees/spec-status-provenance` linked worktree, not the primary checkout. |
| `pr-required-for-main` (MUST) | PASS (pending) | Work lands via PR per the standing workflow; not yet opened at planning time. |
| `no-local-absolute-paths` (MUST NOT) | PASS | All new/reused paths (`.spaex/manifest.json`, `.spaex/install.lock`, `.spaex/constitution.d/`, `.spaex/constitution.md`, generated artifact paths) are repo-relative; JSON output explicitly excludes absolute paths (FR-013, research.md R8). |
| `adrs-for-principle-affecting-decisions` (MUST) | N/A | No decision here materially changes a spaex Core Principle; this is a new read-only reporting surface, not a boundary or trust-model change (contrast Spec 027's ADR 0026, which widened the write boundary — this feature adds no write at all). |
| `phasing-discipline` (MUST) | PASS | Implements roadmap Phase C, which the 2026-09-21 roadmap update marks as no longer gated by Phase B (presets, dropped) or by any unstable prerequisite; Spec 027 (the only prerequisite this design draws on, for the composed-artifact bucket) is merged and in daily use. |
| `version-bump-rules-follow-semver` (MUST) | N/A | This feature does not amend either constitution document; no version bump applies. |

No violations requiring Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/028-status-provenance/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── status-and-trace-cli.md
└── tasks.md              # Phase 2 output (/speckit-tasks — not yet created)
```

### Source Code (repository root)

```text
src/spaex/
├── behavior/
│   ├── clauses.py              # NEW — `TracedClause`/`parse_clauses`, promoted from
│   │                            # `cli/behavior_commands.py`'s private `_TracedClause`/
│   │                            # `_parse_clauses` (research.md R5). `constitution trace`
│   │                            # imports from here afterward; behavior unchanged (FR-016).
│   ├── emit.py                  # Existing `compute_source_hash`, `read_header_hashes` —
│   │                            # reused unmodified by `report/staleness.py`.
│   ├── composer/prompt.py       # Existing `load_effective_prompt`, `effective_prompt_sha256`
│   │                            # — reused unmodified.
│   └── composer/clarifications.py  # Existing `load`, `invalidate` — reused unmodified.
├── model/
│   ├── consumer_manifest.py     # Existing — add public `flatten_compound_pins(manifest)`,
│   │                             # promoted from `cli/behavior_commands.py`'s private
│   │                             # `_load_molecule_pins` (research.md R5 addendum).
│   │                             # `constitution trace` imports it from here afterward;
│   │                             # `ConsumerManifest`/`CompoundEntry` themselves unchanged.
│   └── install_lock.py          # Existing — add public `path_owners(lock)` returning
│                                 # `path -> (molecule_id, ...)` (research.md R2 addendum),
│                                 # shared by `report/compose.py` (US1) and `report/trace.py`
│                                 # (US2). `InstallLock`/`MoleculeEntry` themselves unchanged.
├── report/                      # NEW package — read-only composition reporting, mirrors
│   │                            # the existing `constitution/`, `behavior/`, `install/`
│   │                            # domain-package split (research.md R6).
│   ├── __init__.py
│   ├── compose.py               # NEW — builds `CompositionReport`: molecule union
│   │                            # (manifest ∪ lock), `AtomGrouping` per molecule
│   │                            # (research.md R1), `ConstitutionSummary` (via
│   │                            # `behavior/clauses.py`), drift findings (research.md R3).
│   ├── staleness.py             # NEW — local-only constitution freshness recomputation
│   │                            # (research.md R4): reads `.spaex/constitution.d/` fragments
│   │                            # off disk, recomputes `source_hash`/`build_input_hash` via
│   │                            # existing `behavior/emit.py` + `composer/prompt.py` +
│   │                            # `composer/clarifications.py` functions, compares against
│   │                            # `read_header_hashes`. No molecule resolution.
│   └── trace.py                 # NEW — builds the `path -> [molecule_id, ...]` map from
│                                 # `InstallLock.molecules[].paths` (research.md R2); resolves
│                                 # a `spaex trace` query (file or directory) against it.
├── cli/
│   ├── status.py                # NEW — `run_status`, `run_trace`: argparse handlers,
│   │                             # `--format text|json` dispatch, exit-code mapping
│   │                             # (contracts/status-and-trace-cli.md), mirrors
│   │                             # `behavior_commands.py`'s existing
│   │                             # build-record-then-render split
│   │                             # (`_emit_trace_result`/`_render_clause`/`_render_clause_text`).
│   ├── behavior_commands.py     # Existing `run_constitution_trace` — updated to import
│   │                             # `TracedClause`/`parse_clauses` from `behavior/clauses.py`
│   │                             # instead of defining them locally; no behavior change.
│   └── main.py                  # Existing `_build_parser`/`main` — add `status` and `trace`
│                                 # top-level subparsers and their dispatch, alongside
│                                 # `constitution`/`install`/`add`/`remove`.
└── util/exit_codes.py           # Existing registry — no new codes (research.md R7 reuses
                                  # `SUCCESS`, `VALIDATION_REFUSE`, `INCOMPLETE_TRANSACTION`, `USAGE`,
                                  # and the bare `1` "no match" convention already used by
                                  # `constitution trace`).

tests/
├── unit/           # NEW: `report/compose.py`'s atom-grouping and drift-detection logic in
│                   # isolation (hand-built `ConsumerManifest`/`InstallLock` fixtures);
│                   # `report/staleness.py`'s fingerprint recomputation against hand-written
│                   # `.spaex/constitution.d/` fixtures.
├── behavior/
│   ├── unit/       # NEW: `behavior/clauses.py` after the R5 extraction — same test content
│   │               # as today's private-function coverage, now importing the public module.
│   └── integration/
│       ├── test_provenance_trace.py   # Existing `constitution trace` coverage — MUST pass
│       │                               # unmodified after the R5 extraction (SC-007).
│       ├── test_status.py             # NEW: `spaex status` end-to-end via `spaex.cli.main`,
│       │                               # hand-written `.spaex/` fixtures mirroring
│       │                               # `test_provenance_trace.py`'s style — molecule
│       │                               # listing, atom grouping, constitution summary, each
│       │                               # of the four drift cases (SC-005), `--format json`
│       │                               # byte-identity across repeated runs (SC-004), fresh
│       │                               # checkout without a molecule cache (SC-006).
│       └── test_trace_path.py         # NEW: `spaex trace <path>` end-to-end — single owner,
│                                       # shared-path/constitution-hint case, directory query,
│                                       # no-match case, path-form normalization (FR-011),
│                                       # path-outside-repo refusal.
```

**Structure Decision**: Single existing Python project (`src/spaex` + `tests/`); no new top-level project or directory structure. One new domain package, `src/spaex/report/`, holds the read-only reporting logic (parallel to `constitution/`, `behavior/`, `install/`); one new CLI module, `src/spaex/cli/status.py`, follows the existing `behavior_commands.py` build-then-render convention. `behavior/clauses.py` is a small extraction from existing code, not new logic, undertaken specifically to avoid a second composed-clause parser (research.md R5).

## Complexity Tracking

*(No Constitution Check violations — table intentionally omitted.)*
