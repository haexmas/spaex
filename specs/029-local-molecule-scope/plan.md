# Implementation Plan: Local (Per-Developer) Molecule Scope

**Branch**: `029-local-molecule-scope` | **Date**: 2026-10-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/029-local-molecule-scope/spec.md`

## Summary

Add a second adoption scope, `local`, next to today's project scope. A developer adopts molecules for themselves with `spaex add --local`; the adoption is recorded in an uncommitted overlay at `.spaex/local/manifest.json`, and everything local scope installs is kept out of git automatically: files under `.spaex/local/` via a self-ignoring `.gitignore` (`*`), repo-root files via a per-worktree, marker-delimited block in git's per-clone `info/exclude` (research R1, R7). Local scope publishes its own `.spaex` generation that re-stages every project file byte-for-byte, inside the same rollback context as the project publication, so a local-only change never rewrites the committed install lock (R2). Local behavior fragments are composed by the existing orchestrator into a separate `.spaex/local/constitution.md` that agents read after the project constitution via a version-3 bootstrap block (R5, R6). Project scope wins every conflict: duplicate adoptions are shadowed, and writes to project-owned or git-tracked paths are refused before anything is written (R8, R9).

## Technical Context

**Language/Version**: Python 3.14 (`requires-python = ">=3.14,<3.15"`)

**Primary Dependencies**: None new. Stdlib (`json`, `pathlib`, `subprocess` via the existing git helpers, `dataclasses`) and existing internal modules: `model/consumer_manifest.py`, `model/install_lock.py`, `cli/install.py`, `constitution/publish.py`, `io/transaction.py`, `behavior/orchestrate.py`, `behavior/bootstrap.py`, `install/generic_atoms.py`, `install/nix_packages.py`, `install/hook_runner.py`, `integrations/speckit.py`, `report/compose.py`, `report/trace.py`, `constitution/show.py`.

**Storage**: Files only. New: `.spaex/local/{manifest.json, install.lock, constitution.d/, constitution.md, generated/, .gitignore}` and a spaex-owned block in `$(git rev-parse --git-path info/exclude)`. Unchanged: every project-scope file.

**Testing**: `pytest` with the existing layout. Integration tests use the `haex_add_helpers` fixture (`tests/conftest.py`: `make_publisher`, `make_consumer`, `run_add`, `run_remove`); behavior tests stub `behavior_orchestrate.invoke_composer` as in `tests/behavior/integration/test_project_local_fragments.py`. Local-scope git tests run `git init` in `tmp_path` (the `git_binary` fixture).

**Target Platform**: Linux, macOS, WSL2 CLI. No OS-specific paths; the exclude file is located through `git rev-parse --git-path`, never constructed by hand.

**Project Type**: Single Python CLI project (`src/spaex` + `tests/`).

**Performance Goals**: Install without a local overlay does no extra work beyond one `is_file()` check (SC-002 byte-identity also implies no extra git calls). With an overlay: one extra `git ls-files` and one `git rev-parse` per install; local behavior composition costs one composer pass over local fragments only.

**Constraints**: Project outputs byte-identical with and without an overlay (SC-002); deterministic outputs in both scopes (FR-015); consistent publication of both scopes (FR-016); no edits to committed ignore files (FR-005); local hook side effects are checked at the repository boundary (FR-014).

**Scale/Scope**: Same molecule counts as project scope (single digits to low tens per checkout).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` (Spec Kit layer) and the composed `.spaex/constitution.md` (spaex policy layer):

| Principle / Rule | Status | Notes |
|---|---|---|
| I. Specifications Are the Product Contract | PASS | spec.md states scope, constraints, acceptance scenarios; the scope-defining question ("user-wide" = per developer, per checkout) was clarified with the operator before specifying. |
| II. Plans Must Be Traceable | PASS | Every FR maps to a research decision: FR-001–003 → R13; FR-004, FR-016 → R2; FR-005 → R1, R7; FR-006 → R8; FR-007, FR-008 → R5, R6; FR-009 → R12; FR-010 → R9; FR-011 → R4; FR-012 → R13; FR-013 → R10; FR-014 → R11; FR-015 → R2, R4; FR-017 → R3. |
| III. Cross-Artifact Consistency | PASS | Planning narrowed FR-013 (one Spec Kit policy per checkout, R10); spec.md edge case and FR-013 were updated in the same change. |
| IV. Tasks Independently Verifiable | Deferred to `/speckit-tasks` | quickstart.md and the contract give each task an observable outcome. |
| V. Scope Is Explicit | PASS | Out of scope: global per-user scope, promote-to-project command, team policy forbidding local adoptions, publisher-side consumption of local generated outputs. |
| `graphify-first-authoring` (MUST) | PASS | research.md R14: no existing exclude writer; `install/overlay.py` is an unrelated stub, so the new module is `install/local_scope.py`; `_preserved_project_local_files` and `ConsumerManifest` compound parsing are extended/extracted, not duplicated. |
| `general-coding` size and reuse (MUST/SHOULD) | WATCH | `cli/install.py` is already 1060 LoC, above the 500-LoC boundary. New scope logic goes into `install/local_scope.py` and `install/git_exclude.py`; `cli/install.py` only gains call sites. Splitting `cli/install.py` is a separate refactor, not mixed into this behavior change. |
| Worktree + topic branch (MUST) | PASS | Authored on `029-local-molecule-scope` in the linked worktree `.worktrees/spec-local-scope`. |
| `pr-required-for-main` (MUST) | PASS (pending) | Spec and plan land via PR; implementation follows in a second PR after merge (operator decision). |
| `self-modifying-instructions-review-gated` (MUST) | PASS | Local adoptions only happen through an explicit operator command (`spaex add --local`); spaex never rewrites the overlay on its own (shadowed entries are reported, not removed, R9). The committed constitution is unaffected. |
| `external-sources-opt-in-per-project` (MUST NOT) | PASS | The overlay is a per-checkout allowlist for one project; nothing is inherited without an explicit adoption, and a checkout without an overlay is unchanged. |
| `no-local-absolute-paths` (MUST NOT) | PASS | Every recorded path is repo-relative; the exclude file path is resolved at runtime and never committed. |
| `no-secrets-in-git` (MUST NOT) | PASS | No key material involved; local outputs are excluded from git by construction. |
| `cross-repo-refs-pin-immutable-revisions` (MUST) | PASS | Local compounds require the same 40-hex revision pin (R3). |
| `adrs-for-principle-affecting-decisions` (MUST) | PASS | New write boundary (git's `info/exclude`, outside the working tree) and an uncommitted adoption scope are recorded in ADR 0027 (`docs/adr/0027-local-molecule-scope.md`, status Proposed). |
| `phasing-discipline` (MUST) | PASS | Builds on Specs 023, 024, 027, 028, all merged and in daily use. |
| `version-bump-rules-follow-semver` (MUST) | N/A | Neither constitution document is amended. The new CLI flags are additive (minor release); `status`/`trace` JSON `format_version` 1 → 2 is called out in the release notes. |

No violations requiring Complexity Tracking. The `cli/install.py` size note is a pre-existing condition, handled by keeping new logic out of it.

## Project Structure

### Documentation (this feature)

```text
specs/029-local-molecule-scope/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── local-scope-cli.md
├── checklists/
│   └── requirements.md
└── tasks.md              # /speckit-tasks, in the implementation PR
```

### Source Code (repository root)

```text
src/spaex/
├── paths.py                       # + local_dir(), local_manifest_path(), local_lock_path(),
│                                  #   local_constitution_path()
├── schema/data/
│   └── local-manifest.v1.schema.json   # NEW (R3)
├── model/
│   ├── consumer_manifest.py       # extract shared compound parsing/serialization (R3)
│   └── local_manifest.py          # NEW: LocalManifest from_json/to_json_bytes
├── install/
│   ├── local_scope.py             # NEW: load overlay, split resolved molecules into
│   │                              #   project/local/shadowed, preflight invariants (R8–R10),
│   │                              #   stage .spaex/local/** files, build local lock
│   ├── git_exclude.py             # NEW: read/rewrite the per-worktree spaex block in
│   │                              #   info/exclude; ponytail ceiling note (R7)
│   ├── generic_atoms.py           # accept an owner-scope set; refuse local→project overlap
│   ├── nix_packages.py            # compose local contributions into .spaex/local/generated/
│   └── hook_runner.py             # pass SPAEX_SCOPE (R11)
├── constitution/
│   ├── publish.py                 # stage both scopes in one generation; orphan deletion per scope
│   └── show.py                    # append local document (R13)
├── behavior/
│   ├── orchestrate.py             # parameterize output root + fragment set for local pass (R5)
│   ├── emit.py                    # local preamble
│   └── bootstrap.py               # BLOCK_VERSION 3 + text; outdated-block hint (R6)
├── integrations/speckit.py        # local-scope existing_lock; exclusion paths from CLI manifests (R10)
├── report/compose.py, trace.py    # scope labels, shadowed list, format_version 2 (R13)
├── cli/
│   ├── add.py, remove.py          # --local flag, overlay mutation, refusals; keep
│   │                              #   skill_installation intact (dataclasses.replace)
│   ├── install.py                 # call sites only: load overlay, preflight, local pass
│   ├── status.py                  # render scope
│   └── main.py                    # wire --local flags
└── util/errors.py                 # LocalAdoptionShadowedError, LocalPathConflictError,
                                   #   LocalManifestInvalidError, LocalExcludeMalformedError

tests/
├── unit/
│   ├── test_local_manifest.py     # schema + parsing round-trip, invalid overlay
│   ├── test_git_exclude.py        # block create/update/remove, foreign text untouched,
│   │                              #   malformed block refusal, per-worktree keys
│   ├── test_local_hook_side_effects.py # tracked/project-owned refusal, untracked capture
│   └── test_local_scope_preflight.py   # shadowing, project-owned and tracked-path refusal,
│                                       #   speckit conflict
├── contract/
│   └── test_local_manifest_v1.py  # schema contract
├── integration/
│   ├── test_local_scope_add_remove.py  # add/remove --local end to end: git status clean,
│   │                                   #   project outputs byte-identical, cleanup (SC-001/2/5)
│   └── test_local_scope_crash_safety.py # SPAEX_CRASH_AFTER: both scopes roll back together
└── behavior/integration/
    ├── test_local_behavior.py      # local constitution composed separately, preamble,
    │                               #   project document unchanged (stubbed composer)
    └── test_status_local_scope.py  # status/trace/constitution show labels, format_version 2
```

**Structure Decision**: Single existing project. Two new focused modules under `install/` (`local_scope.py`, `git_exclude.py`) and one model (`local_manifest.py`) hold all new logic; existing modules gain parameters (output root, scope) rather than parallel copies.

## Complexity Tracking

*(No Constitution Check violations — table intentionally omitted.)*
