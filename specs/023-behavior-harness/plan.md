# Implementation Plan: Behavior Harness

**Branch**: `023-behavior-harness` | **Date**: 2026-09-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/023-behavior-harness/spec.md`

## Summary

Add a behavior-harness layer to spaex. Each atom may contribute constitution fragments (Format C: small YAML header, molecule-scoped id, RFC-2119 Markdown body). At install time, spaex materializes fragments to `.spaex/constitution.d/`, runs a mechanical pre-check for intra-molecule id collisions, then invokes a hybrid Composer (LLM synthesis in the `/speckit-analyze` + `/speckit-clarify` pattern) that produces a single committed artifact `.spaex.md` at the repo root. Agent runtimes discover `.spaex.md` via a one-time global bootstrap block written through each runtime's own global-target resolver. Composer failures fail-fast; project overrides are additive-only; clarifications persist keyed by SHA256 of involved fragment bodies.

The scope is additive (target release 4.2.0). Consumers without behavior fragments in their molecule set are unaffected.

## Technical Context

**Language/Version**: Python 3.11+ (matches existing spaex baseline)
**Primary Dependencies**: uv (project management), litellm (LLM adapter, already in stack for context-budget checks), existing spaex modules from Spec 016 (install-hook boundary) and Spec 017 (molecule store content access), pyyaml (fragment header parsing), pydantic (fragment schema validation, already in stack)
**Storage**: filesystem only. Fragments in `.spaex/constitution.d/<molecule-id>/<fragment-id>.md`. Composed constitution at `<repo-root>/.spaex.md`. Clarifications at `.spaex/clarifications.json` (new file, additive; format defined in `contracts/clarifications-schema.md`). Global bootstrap targets are resolved per runtime: Claude's fixed user file, Codex's `$CODEX_HOME` (default `~/.codex`), and Gemini's configured `~/.gemini/<context.fileName>` (paths per runtime; exact rules surveyed in research.md).
**Testing**: pytest (project standard), fault-injection fixtures for Composer failures (timeout, malformed output, runtime error), fixture repos under `tests/fixtures/023-behavior-harness/` covering hard-conflict Cases A and B from spec User Story 3.
**Target Platform**: Linux, macOS, WSL2 (spaex platform contract). Global bootstrap paths are per-OS but reduce to the same runtime-config conventions.
**Project Type**: CLI tool (single-project layout: `src/spaex/`, `tests/`). No frontend, no service.
**Performance Goals**: Composer completes within 30 seconds for a project with 3 molecules each contributing 1 fragment (per spec SC-001). Mechanical pre-check runs in under 1 second per 100 fragments.
**Constraints**: Reproducibility contract requires `.spaex.md` be byte-identical from identical fragment sets (spec SC-003); Composer output is stabilized through system-prompt pinning + persisted clarifications, and the artifact is committed rather than regenerated on every install.
**Scale/Scope**: MVP targets projects with under 100 total fragments across all pinned molecules. Larger fragment sets are documented as a future perf follow-up in research.md, not blocking for 4.2.0.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluating spec 023 against `spaex Constitution 1.4.1`:

- **Principle I (No Secrets in Git)**: N/A. Behavior fragments and `.spaex.md` carry directives, not secrets. Global bootstrap writes to per-user config files that live outside any project repo. PASS.
- **Principle II (No Local Absolute Paths in Versioned Config)**: `.spaex.md` and `.spaex/constitution.d/` use repo-relative paths. Global bootstrap targets are per-user, per-OS files (`~/.claude/CLAUDE.md`, etc.) that are NOT under version control. No committed absolute paths introduced. PASS.
- **Principle III (Project Identity Is Device-Independent)**: `.spaex.md` is per-project, committed via git. Its content addresses no local paths. PASS.
- **Principle IV (Cross-Repo References Pin Immutable Revisions)**: Fragments are contributed by pinned molecules; molecule pinning (SHA-based) is already governed by Principle IV via existing spaex machinery. This spec does not change how molecules are referenced. PASS.
- **Principle V (External Sources Are Opt-in Per Project)**: Behavior fragments arrive only through molecules explicitly listed in `.spaex.json`'s `compounds[]` allowlist. A project without pinned molecules produces an empty (or absent) `.spaex.md`. Project-local fragments (spec FR-018) are project-authored and thus not "external". PASS.
- **Principle VI (Self-Modifying Instructions Are Review-Gated)**: `.spaex.md` is a committed artifact that changes only through git commit; `spaex install` regenerates it locally but the developer's own commit is the review gate (per User Story 6). This aligns with the existing constitution reserved-paths clause for `.spaex/constitution.md` ("committed content, not an agent-writable cache"). One nuance to acknowledge: `spaex install` overwrites `.spaex.md` in the working tree without a `.migrated` sidecar. This is acceptable because the artifact is content, not schema; the git diff on commit IS the review gate, and every install re-derives from the versioned fragments in `.spaex/constitution.d/`. Add ADR-0012 recording this nuance and reserving the new path `<repo-root>/.spaex.md`. PASS with documented follow-up.
- **Principle VII (Relay Unavailability)**: Spec does not touch the relay. PASS.
- **Principle VIII (No Concealment Instructions)**: Composer output is a constitution intended for the operator's own reading; nothing about the spec instructs agents to hide anything. PASS.

**Development Workflow items:**
- Speckit workflow adherence: this spec goes through `/speckit-specify → /speckit-clarify → /speckit-plan → /speckit-tasks → /speckit-implement`, per constitution and per memory `spaex_speckit_workflow_for_impl`. PASS.
- Phase discipline: the spec targets 4.2.0 additive-minor before the 2026-09-08 roadmap's Phase A (5.0.0 skills externalization). This does not skip any phase-0-to-7 prerequisite; it uses existing Spec 016 and Spec 017 infra and does not depend on any 4.2+ phase artifact. PASS.
- ADR requirement: two ADRs recommended, both landed via this spec's PR:
  - ADR-0012: Reserved paths for behavior-harness (`<repo-root>/.spaex.md`, `.spaex/constitution.d/`, `.spaex/clarifications.json`); the review-gate framing for `.spaex.md` (git diff on commit as gate, no sidecar required).
  - ADR-0013: Global bootstrap contract (paired HTML comment markers with version attribute) as the boundary between spaex-managed content and operator-authored content in user-global instruction files.
- PR-based landing on `main` (branch-protected): confirmed by memory. PASS.

**Verdict**: PASS. No violations require complexity tracking below. Two ADRs are follow-ups within this spec's PR, not gate blockers.

## Project Structure

### Documentation (this feature)

```text
specs/023-behavior-harness/
├── plan.md                 # This file
├── spec.md                 # Feature specification
├── research.md             # Phase 0 output (below)
├── data-model.md           # Phase 1 output
├── quickstart.md           # Phase 1 output
├── contracts/              # Phase 1 output
│   ├── cli-surface.md      # New CLI subcommand contracts
│   ├── fragment-format.md  # Fragment header schema + body conventions
│   ├── spaex-md-format.md  # Composed constitution format
│   ├── bootstrap-block.md  # Global bootstrap block layout + markers
│   ├── clarifications-schema.md  # Persisted clarification storage
│   └── composer-interface.md     # System prompt + failure category surface
├── checklists/
│   └── requirements.md     # Spec-quality checklist (from /speckit-specify)
└── tasks.md                # Phase 2 output (/speckit-tasks, NOT created here)
```

### Source Code (repository root)

Single-project Python layout, additive to existing spaex modules.

```text
src/spaex/
├── behavior/                     # NEW: behavior-harness subsystem
│   ├── __init__.py
│   ├── fragment.py               # Fragment schema (pydantic), header parser
│   ├── materialize.py            # Materialize fragments from molecule store to .spaex/constitution.d/
│   ├── precheck.py               # Mechanical pre-check (intra-molecule id collision, malformed fragments)
│   ├── composer/                 # LLM-based composer subsystem
│   │   ├── __init__.py
│   │   ├── prompt.py             # Canonical system prompt (spaex-shipped, project-overridable)
│   │   ├── invoke.py             # Runtime-agnostic composer invocation (litellm or CLI shell-out)
│   │   ├── clarifications.py     # Persistence keyed by SHA256; load/save/invalidate
│   │   └── failure.py            # Failure category enum, diagnostic formatter
│   ├── emit.py                   # Write .spaex.md at repo root; delete on empty set (per FR-017d)
│   └── bootstrap.py              # Install/upgrade/remove the global bootstrap block per runtime
├── cli/
│   └── behavior_commands.py      # NEW: `spaex constitution build`, `spaex install --global`, etc.
├── install.py                    # EXISTING (Spec 016): extend to invoke behavior.* subsystem
└── ... (existing modules unchanged)

tests/
├── behavior/                     # NEW subdirectory mirrors src/spaex/behavior/
│   ├── unit/
│   │   ├── test_fragment_schema.py
│   │   ├── test_precheck.py
│   │   ├── test_clarification_key.py
│   │   └── test_bootstrap_marker.py
│   ├── integration/
│   │   ├── test_install_end_to_end.py       # Fixture repos, full install → .spaex.md flow
│   │   ├── test_case_a_intra_molecule.py    # User Story 3 Case A
│   │   ├── test_case_b_cross_molecule.py    # User Story 3 Case B
│   │   ├── test_project_local_fragments.py  # User Story 5
│   │   ├── test_reproducibility.py          # User Story 6 byte-identity (SC-003)
│   │   ├── test_provenance_trace.py         # SC-006 (`spaex constitution trace`)
│   │   ├── test_bootstrap_discoverability.py # SC-007 (mocked CLI-level runtime read of .spaex.md)
│   │   ├── test_clarification_persistence.py # SC-008 (answer once, no re-ask unchanged, re-ask on body change)
│   │   ├── test_add_time_plausibility.py    # FR-024a (add/remove warns, writes .stale, doesn't regen .spaex.md)
│   │   └── test_install_is_non_destructive.py # FR-006 (any abort leaves tracked files unchanged)
│   ├── fault_injection/
│   │   ├── test_composer_timeout.py
│   │   ├── test_composer_malformed.py
│   │   ├── test_composer_runtime_error.py
│   │   └── test_composer_quota.py
│   └── fixtures/
│       ├── molecule_with_one_fragment/
│       ├── molecule_pair_case_a/
│       ├── molecule_pair_case_b/
│       ├── project_local_only/
│       └── ...
└── ... (existing tests unchanged)

docs/adr/
├── 0012-behavior-harness-reserved-paths.md   # NEW
└── 0013-global-bootstrap-block-contract.md   # NEW
```

**Structure Decision**: Single-project Python layout, `src/spaex/behavior/` as a new subsystem alongside the existing modules. This mirrors how Spec 016 (`src/spaex/hooks/`) and Spec 017 (`src/spaex/molecule_store/`) landed. `src/spaex/cli/behavior_commands.py` adds the new subcommands under the existing CLI aggregator. Tests colocate under `tests/behavior/` with three categories (unit, integration, fault_injection) reflecting the spec's SC coverage.

## Complexity Tracking

*No constitution violations require justification.* The two ADRs (0012, 0013) are documentation of decisions already made, not exceptions.

## Migration Notes (integration with existing infrastructure)

- **Spec 007 `.spaex/constitution.md` supersession**: the existing consumer-side `.spaex/constitution.md` (spec-007 D2/D16, reserved path per constitution §Reserved paths v1.3.0) served the same role as this spec's `.spaex.md`. Since spaex has no external users (memory `spaex_pre_user`), the transition is a straight rename plus content-migration: `.spaex/constitution.md` is deprecated and removed, `.spaex.md` at repo root becomes the single composed constitution artifact. The reserved-paths clause in the constitution is updated by ADR-0012 to reflect the new path. Existing spec-007 machinery that writes `.spaex/constitution.md` is refactored in `src/spaex/behavior/emit.py`; no orphan writers remain.
- **Spec 016 install-hook integration**: fragment materialization (`src/spaex/behavior/materialize.py`) plugs into the install-hook boundary as a new phase (not an install-hook itself, because install-hooks are per-molecule side effects; fragment materialization is orchestration). The mechanical pre-check runs BEFORE any Spec 016 install-hooks so a hard conflict aborts before side effects run.
- **Spec 017 molecule-store integration**: fragment content is read from the materialized molecule tree via `molecule_store.get_or_extract` (per memory `spaex_git_content_access_architecture`) rather than `git_show.show_bytes`, because fragments live in a real directory that the tree walks over.

## Rollout Sequence

4.2.0 is a MINOR bump that adds the behavior-harness without breaking any existing consumer. Rollout stages:

1. Land the code with ADR-0012 + ADR-0013 in the same PR.
2. Bump `spaex.__version__` to 4.2.0 in a follow-up chore commit on the same branch.
3. `haexmas/atoms` publishes its first molecule that carries a behavior fragment (candidate: `speckit-strict` or `graphify-first-authoring`), pinned to the 4.2.0 SHA.
4. Consumer projects that pin the new molecule version see the harness materialize; consumers that do not are unaffected.
5. Follow-up spec 024 (proposed) covers contextual-scope semantics (`scope: contextual`, `when: "..."`) and the exact `--global` CLI-flag surface for bootstrap install/upgrade/remove.
