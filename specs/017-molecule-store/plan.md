# Implementation Plan: Molecule tree materialization store

**Branch**: `017-molecule-store` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/017-molecule-store/spec.md`

**Related**:
- Design source: [docs/plans/2026-09-08-spec-017-molecule-store-design.md](../../docs/plans/2026-09-08-spec-017-molecule-store-design.md) (PR #85 merged 2026-09-08, includes review-driven refinements)
- Originating decision: [Spec 007's D15](../../docs/plans/2026-08-28-spec-007-unified-manifest-design.md#d15-storage-layout-hybrid-content-addressed-store) (2026-08-28) — this spec implements the unbuilt half of D15, scoped down (no content-integrity hashing, lazy materialization).
- Blocking dependency for: [specs/016-molecule-install-hooks/](../016-molecule-install-hooks/) — Spec 016's hook_runner needs `get_or_extract()` to obtain a real directory for subprocess execution.

## Summary

Add `get_or_extract(repo_dir, revision, molecule_path, state_root) -> Path`: materializes a molecule's tree from an already-cloned bare git repository onto local disk, via `git archive <revision> -- <molecule_path>` piped into Python's stdlib `tarfile` (not the external `tar` binary). Cached indefinitely under `SPAEX_STATE/molecule-store/<source-digest>/<revision>/<molecule-path>/`, keyed by the canonical full 40-hex SHA. Extraction is atomic (temp-dir + rename) and lock-protected, with manual tar-member path-containment validation (rejecting `..` escapes, symlink/hardlink escapes, and absolute-path link targets unconditionally) since Python 3.10/3.11 lack `tarfile`'s `filter="data"`. `constitution/resolve.py`'s per-molecule manifest and constitution-body reads migrate onto this new capability; publisher-root-manifest reads and `cli/add.py`'s validation reads are explicitly unchanged. No content-integrity hashing (deferred, no current consumer). Target spaex 4.1.0, landing before Spec 016's hook_runner implementation.

Ships as **one PR against `main`** — design doc already landed separately (PR #85); this PR is spec/plan/tasks artifacts only, matching the established pattern from Spec 016 (design → speckit chain → implementation, each its own PR).

## Technical Context

**Language/Version**: Python 3.10+ (unchanged baseline; the plan's path-containment approach explicitly accounts for `tarfile.extractall(filter=...)` being 3.12+-only, so 3.10/3.11 support is not merely nominal but load-bearing for this feature's own safety design).
**Primary Dependencies**: `jsonschema>=4.18` (unchanged, unrelated to this feature). No new runtime dependencies — extraction uses only `subprocess` (to invoke `git archive`) and the stdlib `tarfile` module, deliberately avoiding a dependency on the external `tar` binary.
**Storage**: Local filesystem cache under `SPAEX_STATE/molecule-store/<source-digest>/<revision>/<molecule-path>/`, sibling to the existing `SPAEX_STATE/repos/<digest>/` bare-clone cache. No new consumer-repo-visible files — nothing in this spec is copied into any consumer's `.spaex.json` or `.spaex/`.
**Testing**: pytest, pytest-subprocess (unchanged from Spec 013 baseline). New tests use real, small git repositories created on the fly (matching `tests/unit/test_resolve.py`'s existing `_publish`/`_clone`/`_init_repo` fixture-helper pattern) plus crafted-tar-member tests built directly with Python's `tarfile` module (no need for a real git repo to construct a malicious tar stream — a `tarfile.TarInfo`-based fixture is more precise and portable for exercising specific member types).
**Target Platform**: Linux, macOS, WSL2. Python-only wheel (`py3-none-any`) — the `tarfile`-over-external-`tar` decision exists specifically to keep this true.
**Project Type**: Python CLI + library (single-project layout, unchanged from Spec 013).
**Performance Goals**: N/A as an explicit target; SC-002's "no additional remote-repository access on a cache hit" is the only measurable performance-adjacent property, verified functionally (call-count assertion) rather than by timing.
**Constraints**: No external `tar` binary dependency. No content-integrity hashing (explicitly deferred). No proactive/eager materialization. Must not regress any currently-passing `tests/unit/test_resolve.py` scenario (User Story 4, SC-004).
**Scale/Scope**: One new module, one migrated existing module (`constitution/resolve.py`), zero CLI surface changes (this spec introduces no new command-line flags or user-visible commands — `get_or_extract` is an internal capability consumed by other code, not exposed directly).

## Constitution Check

Verified against `.specify/memory/constitution.md` v1.4.1 (all eight NON-NEGOTIABLE principles). Same evaluation approach as Spec 016's plan.md, re-run for this feature's actual surface.

| Principle | Status | Notes |
|---|---|---|
| I. No Secrets in Git | PASS | Feature touches no secrets. Materialized directories may contain arbitrary publisher-authored content, but that content is not secret material spaex itself introduces. |
| II. No Local Absolute Paths in Versioned Config | PASS | The local cache path (`SPAEX_STATE/molecule-store/...`) is never written into any versioned/committed file — it is a local-only cache path, analogous to the existing `SPAEX_STATE/repos/` cache. The 2026-09-08 clarification (refuse absolute-path symlink targets unconditionally) is itself an extra, voluntary application of this principle's spirit to publisher-authored tree content, even though that content is not "config" in the principle's literal sense. |
| III. Project Identity Is Device-Independent | N/A | Feature does not touch project-identity resolution. |
| IV. Cross-Repo References Pin Immutable Revisions | PASS | Cache identity is keyed on the canonical full 40-hex SHA (FR-006), never a symbolic or short ref — directly reinforces this principle at the caching-layer boundary. |
| V. External Sources Are Opt-in Per Project | PASS | This feature does not change what is opted into; it only changes how already-opted-into content is materialized locally. No new external source is introduced. |
| VI. Self-Modifying Instructions Are Always Review-Gated | PASS | Materialized content includes constitution fragments (already review-gated via the existing pin-and-assemble flow, unchanged in effect by this spec) and, eventually, hook scripts (Spec 016's concern, not this spec's). This spec only changes the mechanism of reading bytes, not the trust/review boundary around what those bytes are permitted to do. |
| VII. Relay Unavailability Never Blocks Local Work | N/A | No relay involvement. |
| VIII. No Concealment Instructions in Agent Output | N/A | Feature produces no agent-facing output of its own; unrelated to constitution-assembly's existing concealment-instruction check (`validate_no_concealment_instructions`, untouched by this migration). |

**Gate result**: PASS. No violations, no exemptions requested. Complexity Tracking section is empty.

## Project Structure

### Documentation (this feature)

```text
specs/017-molecule-store/
├── plan.md              # This file
├── spec.md              # Feature specification (with 2026-09-08 clarification)
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output (materialization request/result, cache key, error taxonomy)
├── contracts/            # Phase 1 output
│   ├── get-or-extract.md               # Function contract: signature, pre/post-conditions, error cases
│   └── tar-member-validation.md        # Path-containment validation rules, worked examples
├── quickstart.md         # Phase 1 output (materialize a molecule end-to-end, verify safety rejections)
├── checklists/
│   └── requirements.md   # Speckit-generated spec-quality checklist
└── tasks.md              # Phase 2 output (/speckit-tasks command; NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/spaex/
├── git/
│   ├── show.py                 # UNCHANGED — publisher-root-manifest reads keep using this
│   ├── publisher_fetch.py      # UNCHANGED — bare-clone tier this spec builds on top of (repo_dir input)
│   ├── revparse.py             # UNCHANGED — full_sha() reused correctly this time (return value captured)
│   ├── remote.py               # UNCHANGED
│   └── molecule_store.py       # NEW — get_or_extract(), tar-member validation, atomic publish, locking
├── constitution/
│   └── resolve.py              # MODIFIED — per-molecule manifest + constitution-body reads migrate to molecule_store.get_or_extract()
├── util/
│   └── errors.py               # MODIFIED — adds MoleculeTreeExtractionError
└── install/
    └── manifest_lock.py        # UNCHANGED — ManifestLockContext reused as-is by molecule_store.py

tests/
├── unit/
│   ├── test_molecule_store.py           # NEW — get_or_extract() core behavior, caching, error cases
│   ├── test_molecule_store_safety.py    # NEW — crafted-tar-member path-containment/escape tests (US3)
│   ├── test_molecule_store_concurrency.py  # NEW — concurrent-request and interruption-recovery tests (US2)
│   └── test_resolve.py                  # MODIFIED — existing tests must keep passing unchanged; new tests added for the migration's error-contract translations and canonical-SHA usage
└── integration/
    └── (none anticipated — this feature's surface is fully exercisable via unit tests against real small git repos; no CLI-level integration test needed since there is no new CLI surface)
```

**Structure Decision**: Single-project layout (Option 1), matching Spec 013/014/016's established layout. `molecule_store.py` placed in `git/` rather than `install/`, following `publisher_fetch.py`'s existing precedent of combining git-subprocess invocation with atomic-directory-publish-and-locking in one module — both modules produce a real, cached, on-disk representation of remote git content; `install/`'s modules (`manifest_lock.py`, `generation.py`, `overlay.py`, `delta.py`) are instead scoped to the Spec-008 install-transaction machinery for the CONSUMER's own `.spaex/` directory, a different concern this feature does not touch.

## Complexity Tracking

_No Constitution violations. Section intentionally empty._

## Phase 0: Research

The design doc (PR #85, including its review-driven refinements) and the finalized spec (including the 2026-09-08 clarification) resolve every material decision. Phase 0's research.md restates the resolved decisions with rationale/alternatives, per the standard template, plus two decisions newly settled during this planning pass (module placement; error-class reuse verification) that were left open by the design doc.

Output: [research.md](./research.md)

## Phase 1: Design & Contracts

**Prerequisites**: research.md complete.

1. **Data model** ([data-model.md](./data-model.md)):
   - `MaterializationKey`: (source repository identity, canonical revision, molecule path) triple — the cache identity.
   - `MaterializationResult`: the returned `Path`, plus internal bookkeeping needed for the atomicity/locking contract (temp-dir naming, lock-file naming).
   - Error taxonomy: `MoleculeTreeExtractionError` (new) alongside reused `MissingAtomManifestError`, `ContributionFileNotFoundError`, `PinnedRevisionNotFoundError` — which failure conditions map to which.

2. **Contracts** ([contracts/](./contracts/)):
   - `get-or-extract.md`: full function contract (signature, preconditions, postconditions, every distinguishable failure case and which exception type it raises).
   - `tar-member-validation.md`: the path-containment validation algorithm specified precisely enough to implement identically regardless of who writes the code — order-dependent validation, absolute-path-target refusal, relative-escape refusal, worked examples of accept/reject for each case in User Story 3's acceptance scenarios.

3. **Quickstart** ([quickstart.md](./quickstart.md)):
   - End-to-end example: a tiny publisher repo, a call to `get_or_extract`, inspection of the returned directory; then a crafted-malicious-tree example demonstrating each safety refusal from User Story 3.

4. **Agent context update**:
   - No root `CLAUDE.md` exists in this repository (confirmed during Spec 016's planning) — this step is a no-op, as it was for Spec 016.

Output: data-model.md, contracts/*, quickstart.md.

## Phase 2 handoff

After Phase 1 completes, run `/speckit-tasks` to generate the dependency-ordered `tasks.md`. Task decomposition should follow the User Story priority order (P1: US1 core materialization, P1: US3 safety — these two are tightly coupled and likely land together as the MVP — then P2: US2 concurrency, P2: US4 constitution-resolve migration), with the new `molecule_store.py` module and its tar-validation helper as prerequisites shared by both P1 stories.

**Do NOT create `tasks.md` in this command.**
