# Implementation Plan: Molecule install-hooks in `spaex install`

**Branch**: `016-molecule-install-hooks` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/016-molecule-install-hooks/spec.md`

**Related**:
- Design source: [docs/plans/2026-09-08-spec-016-molecule-install-hooks-design.md](../../docs/plans/2026-09-08-spec-016-molecule-install-hooks-design.md) (411 lines, PR #83 merged 2026-09-08)
- Preceding: [specs/014-rename-to-spaex/](../014-rename-to-spaex/) (established v4 vocabulary)
- Foundational: [specs/007-unified-manifest-v2/](../007-unified-manifest-v2/) (atom-category model)
- Foundational: [specs/008-install-transaction/](../008-install-transaction/) (staging-generation-then-publish machinery)
- **Blocking dependency, landed after this plan was first written**: [specs/017-molecule-store/](../017-molecule-store/) (`spaex.git.molecule_store.get_or_extract()`, merged 2026-09-09) — surfaced mid-implementation of this spec as a missing prerequisite (no code existed to materialize a molecule's tree onto real disk for a subprocess to execute against). This plan's Project Structure and T009/T013 were amended 2026-09-09 to consume its landed store MVP. Execution-time script containment remains required; Spec 017's resolver migration (T016–T021) is still pending and is not a prerequisite for hook materialization.

## Summary

Add an optional `install_hook` field to molecule-manifest v4. `spaex install` invokes each declared hook as a normal subprocess (arbitrary code execution, consumer-user permissions, full env inheritance) after atom materialization and before publishing the install.lock generation. Per-molecule `on_failure: "abort" | "warn"` selects between Spec-008 transaction rollback and continue-with-`hook_status`-recorded semantics. Global `--no-install-hooks` opt-out. Additive, backwards-compatible schema addition; existing molecules without the field remain valid. Target spaex 4.1.0 (MINOR bump). Concrete downstream unblock: graphify-first-authoring 1.0.3 lets three current consumers (haex-crdt, specifyr, holzi) stop maintaining a manual `.gitignore` line per repo.

This PR contains **only the Speckit design artifacts** for the feature. The
implementation, tests, documentation updates, and Molecule version changes
are follow-up work after this specification/planning PR is reviewed.

## Technical Context

**Language/Version**: Python 3.10+ (unchanged from Spec 013/014 baseline)
**Primary Dependencies**: `jsonschema>=4.18` (unchanged). No new runtime dependencies. `subprocess` from stdlib.
**Storage**: Local filesystem. Extended JSON payloads: `molecule-manifest.v4.schema.json` gains optional `install_hook` definition; `.spaex/install.lock` per-molecule record gains optional `hook_status` field. No new files or directories.
**Testing**: pytest, pytest-subprocess (unchanged from Spec 013). Hook execution tests use real subprocess spawning against fixtures under `tests/`.
**Target Platform**: Linux, macOS, WSL2. Python-only wheel (`py3-none-any`).
**Project Type**: Python CLI + library (single-project layout established by Spec 013).
**Performance Goals**: N/A (interactive CLI tool; hook duration is molecule-author's responsibility, not spaex's).
**Constraints**: No additional runtime dependencies. Hook stdio inherited from spaex process (no `capture_output=True`). Interactive prompts MUST work in TTY environments. `EOFError` fallback expected in CI.
**Scale/Scope**: One published molecule with an install_hook at feature-landing (graphify-first-authoring 1.0.3); ecosystem scales with adoption. FR-010's priority-based ordering is inherently O(n log n) sort of resolved molecules, negligible for realistic n (< 100).

## Constitution Check

Verified against `.specify/memory/constitution.md` v1.4.1 (all eight NON-NEGOTIABLE principles).

| Principle | Status | Notes |
|---|---|---|
| I. No Secrets in Git | PASS | Feature does not touch git history. Full env inheritance (FR-013) may expose the operator's environment secrets to the hook subprocess, but reading is not committing; principle I forbids commit only. Documented as an inherent property of the pin-based trust model. |
| II. No Local Absolute Paths in Versioned Config | PASS | Consumer-facing artifacts (`.spaex.json`, molecule manifest, install.lock) contain no local paths. Molecule-cache absolute paths are computed internally at runtime, never committed. |
| III. Project Identity Is Device-Independent | N/A | Feature does not touch project-identity resolution. |
| IV. Cross-Repo References Pin Immutable Revisions | PASS | `install_hook.script` is molecule-directory-relative, resolved against the pinned publisher-cache tree (immutable per 40-hex SHA). FR-014 canonicalises the resolved path and enforces cache-containment. |
| V. External Sources Are Opt-in Per Project | PASS | Hook execution is opt-in via `spaex add --revision <sha>` (adoption is the opt-in). Consumer can globally opt out of hook execution via `--no-install-hooks` (FR-026). |
| VI. Self-Modifying Instructions Are Always Review-Gated | PASS | Hook CAN in principle modify agent instructions in the consumer repo (CLAUDE.md, AGENTS.md), but the review gate is the `spaex add --revision <sha>` pin decision itself. The consumer explicitly reviewed and pinned the publisher's SHA, which includes the full molecule cache (including install.py). Molecule authors modifying agent instructions inherit the same review gate as any other atom that ships instruction content. |
| VII. Relay Unavailability Never Blocks Local Work | N/A | No relay involvement. |
| VIII. No Concealment Instructions in Agent Output | N/A | Feature does not produce agent output. |

**Gate result**: PASS. No violations, no exemptions requested. Complexity Tracking section is empty.

## Project Structure

### Documentation (this feature)

```text
specs/016-molecule-install-hooks/
├── plan.md              # This file
├── spec.md              # Feature specification (with 2026-09-08 clarifications)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (InstallHook, ResolvedMolecule, install.lock record)
├── contracts/           # Phase 1 output
│   ├── molecule-manifest-v4-install-hook.schema.json  # Schema fragment for install_hook
│   ├── install-lock-v4-hook-status.schema.json        # Schema fragment for hook_status
│   └── cli-flags.md                                    # --no-install-hooks flag contract
├── quickstart.md        # Phase 1 output (adopt a molecule with install_hook, end-to-end)
├── checklists/
│   └── requirements.md  # Speckit-generated spec-quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks command; NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/spaex/
├── model/
│   ├── molecule_manifest.py         # Extend: InstallHook dataclass, MoleculeManifest.install_hook: InstallHook | None
│   └── consumer_manifest.py         # No change (spec explicitly does not modify consumer-manifest v4)
├── schema/
│   └── data/
│       ├── molecule-manifest.v4.schema.json  # Extend: new install_hook property under type=object
│       └── install-lock.v4.schema.json       # Extend: optional hook_status enum on per-molecule record
├── constitution/
│   └── resolve.py                   # Extend resolver: retain hook-only molecules, priority sort,
│                                     #   expose repo_dir/molecule_path (Spec 017 lands 2026-09-09;
│                                     #   this spec consumes spaex.git.molecule_store
│                                     #   for lazy hook materialization)
├── install/
│   ├── manifest_lock.py             # No change
│   └── hook_runner.py               # NEW: calls molecule_store.get_or_extract(), subprocess
│                                     #   invocation, execution-time molecule containment,
│                                     #   on_failure application
├── util/
│   └── path_containment.py          # NEW: canonicalise + strict descendant check for hook target
└── cli/
    ├── add.py                       # New flag: --no-install-hooks (propagated to install subroutine)
    ├── install.py                   # Orchestrate hooks before publication; reuse install-failed key
    └── remove.py                    # New behavior: WARN on removal of a molecule that declared install_hook

tests/
├── contract/
│   └── test_molecule_manifest_install_hook_schema.py  # NEW: schema accept/reject cases for install_hook + hook_status
├── integration/
│   ├── test_install_hook_execution.py                 # NEW: full spaex install flow with real subprocess hooks
│   ├── test_install_hook_failure_policy.py            # NEW: abort vs warn semantics, rollback verification
│   ├── test_install_hook_opt_out.py                   # NEW: --no-install-hooks skip behavior
│   ├── test_install_hook_multi_molecule.py            # NEW: priority ordering, hook-only molecule survival
│   └── test_install_hook_idempotency.py               # NEW: repeat spaex install, hook-only-transaction case
└── unit/
    ├── test_manifest_install_hook_parser.py           # NEW: MoleculeManifest.from_json populates InstallHook | None
    ├── test_path_containment.py                       # NEW: canonical target and symlink cases
    └── test_hook_runner.py                            # NEW: store inputs, failures, execution containment
```

**2026-09-09 amendment (corrected during PR #88 review)**: consume the landed [Spec 017](../017-molecule-store/) store MVP for lazy materialization, using `repo_dir` + `molecule_path` instead of an assumed pre-populated `cache_dir`. Retain `util/path_containment.py` and T011/T012: the store validates archive members against the temporary extraction root, which contains the molecule subtree. A committed `mol/install.py -> ../sibling/install.py` can pass extraction validation but resolve outside the returned molecule directory after publication when the sibling is cached. Cache hits also return without revalidation. Therefore the hook runner MUST canonicalise and check its script against the returned molecule directory immediately before execution (FR-014/FR-015), on both fresh extraction and cache hits. These checks enforce different boundaries. Spec 017's pending constitution-resolver migration likewise retains a read-time check (FR-018, T018/T021); it does not make this hook check redundant.

**Structure Decision**: Single-project layout (Option 1), matching Spec 013/014 established layout. No new top-level directories; all changes are additions within existing `src/spaex/` module tree and mirroring `tests/`.

## Complexity Tracking

_No Constitution violations. Section intentionally empty._

## Phase 0: Research

Design already brainstormed in PR #83; research.md captures the resolved decisions with pointers, not fresh research tasks. Genuinely open questions were resolved in the /speckit-clarify pass (env-inheritance decision recorded in Clarifications section of spec.md). No `NEEDS CLARIFICATION` markers remain.

Output: [research.md](./research.md)

## Phase 1: Design & Contracts

**Prerequisites**: research.md complete.

1. **Data model** ([data-model.md](./data-model.md)):
   - `InstallHook` dataclass: interpreter (str), script (repo-relative path str), args (list[str]), on_failure (Literal["abort", "warn"]).
   - `MoleculeManifest.install_hook: InstallHook | None` field; `from_json()` parser rules (absent → None; present with omitted `on_failure` → explicitly "abort", never rely on JSON-Schema default).
   - `ResolvedMolecule` extension: expose `install_hook`, `source_url`, `revision` (40-hex), `repo_dir` (local bare clone) and `molecule_path` (publisher-declared path) — passed to Spec 017's `molecule_store.get_or_extract()` on demand rather than a pre-populated `cache_dir` — and `effective_priority` (int). Hook-only molecules MUST remain in the resolved collection.
   - `install.lock` per-molecule record: add optional `hook_status: Literal["ok", "failed", "skipped"] | None`. Present exactly when the molecule declares `install_hook`.

2. **Contracts** ([contracts/](./contracts/)):
   - `molecule-manifest-v4-install-hook.schema.json`: JSON Schema fragment defining the `install_hook` object (mergeable into existing molecule-manifest v4 schema).
   - `install-lock-v4-hook-status.schema.json`: JSON Schema fragment for the `hook_status` field addition to install-lock v4.
   - `cli-flags.md`: `--no-install-hooks` flag contract on `spaex add` and `spaex install`, with propagation semantics between the two commands.

3. **Quickstart** ([quickstart.md](./quickstart.md)):
   - Minimal end-to-end example: publisher molecule with a trivial install_hook, consumer adopting it via `spaex add`, expected artefacts after execution. Serves as the post-implementation acceptance-scenario documentation for User Story 1.

4. **Agent context update**:
   - Update `CLAUDE.md` between `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers to point to this plan file.

Output: data-model.md, contracts/*, and a post-implementation quickstart;
there is no root `CLAUDE.md` in this repository to update.

## Phase 2 handoff

After Phase 1 completes, run `/speckit-tasks` to generate the dependency-ordered `tasks.md`. Task decomposition should follow the User Story priority order (P1 → P4), with cross-cutting infrastructure tasks (schema extension, InstallHook dataclass, hook_runner module, path-containment helper) as prerequisites of the P1 story tasks.

**Do NOT create `tasks.md` in this command.**
