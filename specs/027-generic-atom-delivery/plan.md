# Implementation Plan: Generic Atom-Category Delivery and Removal

**Branch**: `027-generic-atom-delivery` | **Date**: 2026-09-18 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/027-generic-atom-delivery/spec.md`

## Summary

Today `spaex install` only materializes files for the `behavior` atom category (into `.spaex/constitution.d/` + composed `.spaex/constitution.md`); every other declared `atoms` category is inert. This feature generalizes materialization to two new kinds: **exclusive** generic categories (any key besides `behavior`/`skill`/`skills`/`nix_packages`; single owner, verbatim delivery, refused on cross-molecule path collision, cleaned up on `spaex remove`) and one fixed **composable** category, `nix_packages` (multiple molecules each contribute a package-identifier fragment; `spaex install`/`spaex remove` merge the currently-active set deterministically into a generated file, regenerating rather than deleting it while other contributors remain). The reference/driving use case is a Nix devShell: a base molecule ships an exclusive `flake.nix`/`.envrc`/`.gitignore` skeleton, and per-language molecules (python, rust, ...) each contribute their toolchain via `nix_packages` instead of shipping competing `flake.nix` files. This required extending `install-lock.v4.schema.json`'s path pattern to admit bare repo-root filenames for the exclusive case (ADR 0026), since Nix/direnv/Git require those files at the literal repo root — the first time spaex's ownership tracking reaches outside a dot-directory.

## Technical Context

**Language/Version**: Python 3.14 (`requires-python = ">=3.14,<3.15"`, matches the rest of the codebase)
**Primary Dependencies**: `jsonschema` (schema validation, existing), `pyyaml` (existing) — no new runtime dependency; composition (research.md §2) is plain stdlib (`json`, `hashlib`, `sorted`/`set`), no LLM/subprocess involvement
**Storage**: Filesystem only — `install.lock` (existing JSON file, schema extended), generated `.spaex/generated/nix-packages.json` (new), consumer-repo-root files (new: first non-dot-directory writes)
**Testing**: `pytest` (existing suite layout: `tests/contract/`, `tests/integration/`, presumably `tests/unit/` — new contract tests for the extended `install-lock.v4.schema.json` pattern and new integration tests for install/remove of exclusive + composable categories, mirroring existing `behavior`-atom test structure)
**Target Platform**: Linux/macOS/WSL2 CLI tool (existing spaex target — no path in this feature may assume one OS's layout, per the `no-local-absolute-paths` constitution rule)
**Project Type**: Single Python CLI project (existing `src/spaex` package + `tests/`)
**Performance Goals**: N/A beyond existing `spaex install`/`spaex remove` responsiveness — composition here is in-process list/set operations on small inputs (package identifier lists), not a scaling concern like the `behavior` Composer's LLM calls
**Constraints**: Must preserve existing install-transaction atomicity (Spec 008) and byte-reproducibility guarantees (FR-005) without modification to their mechanism — this feature's writes participate in the existing transaction, it does not introduce a second one
**Scale/Scope**: Bounded by adopted-molecule count already in play elsewhere in this codebase (single digits to low tens); no new scale dimension

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` (Spec-Kit layer) and the pinned `.spaex/constitution.d/` atoms (spaex policy layer):

| Principle / Rule | Status | Notes |
|---|---|---|
| I. Specifications Are the Product Contract | PASS | spec.md covers scope, constraints, acceptance scenarios; both raised clarifications resolved before planning. |
| II. Plans Must Be Traceable | PASS | Every FR in spec.md maps to a research.md decision and a data-model.md entity below; no unresolved ambiguity carried into this plan. |
| III. Cross-Artifact Consistency Is Required | PASS (ongoing) | FR-006a's wording was corrected in spec.md during planning (composition mechanism, not the `behavior` Composer) to keep spec and research.md consistent — see research.md §2. |
| IV. Tasks Must Be Independently Verifiable | Deferred to `/speckit.tasks` | Not yet generated; this plan's contracts/data-model give each future task an observable outcome to verify against. |
| V. Scope Is Explicit | PASS | spec.md's Non-Goals + Assumptions explicitly bound scope (no multi-environment vocabulary, no package-version conflict resolution, no store GC). |
| `adrs-for-principle-affecting-decisions` (MUST) | PASS | ADR 0026 recorded for the repo-root write-boundary widening — the one decision here that materially affects spaex's existing trust/ownership model. |
| `phasing-discipline` (MUST) | PASS | Builds on the map-reduce Composer (Spec 026), which is merged to `main` and in daily use for this repo's own `spaex install` — not building ahead of an unstable prerequisite. Explicitly does *not* reuse that Composer's LLM mechanism for package composition (research.md §2), avoiding a false dependency on it. |
| `no-local-absolute-paths` (MUST NOT) | PASS | All new paths (`flake.nix`, `.envrc`, `.gitignore`, `.spaex/generated/nix-packages.json`) are repo-relative; no OS-specific absolute path is introduced by this design. |
| `version-bump-rules-follow-semver` (MUST) | N/A | This feature does not amend either constitution document; no version bump applies. |

No violations requiring Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/027-generic-atom-delivery/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── generic-atom-delivery.md
└── tasks.md              # Phase 2 output (/speckit.tasks — not yet created)
```

### Source Code (repository root)

```text
src/spaex/
├── model/
│   ├── molecule_manifest.py   # Existing category-overlap validation — extend to classify
│   │                           # exclusive vs. `nix_packages` category kinds (data-model.md
│   │                           # GenericAtomCategory) instead of treating all non-behavior
│   │                           # categories as inert.
│   └── install_lock.py        # Existing install.lock read/write — extend `paths` handling
│                               # for the bare-root-filename case (ADR 0026, research.md §5)
│                               # and for one path having multiple owning molecule ids
│                               # (ComposedFile).
├── install/
│   ├── generic_atoms.py        # NEW — materializes exclusive-category DeliveredFile entries
│   │                           # (verbatim write, overwrite-unowned per FR-006, path-overlap
│   │                           # refusal per FR-003), analogous to how behavior/materialize.py
│   │                           # handles the `behavior` category today.
│   └── nix_packages.py         # NEW — reads active PackageFragments, composes ComposedFile
│                           # per research.md §2, writes/regenerates/deletes
│                           # `.spaex/generated/nix-packages.json` per FR-006a/FR-006b.
├── cli/
│   └── install.py             # Existing `run()` orchestration — call the two new
│                               # materializers alongside the existing behavior pipeline;
│                               # existing install-transaction wrapping (Spec 008) covers
│                               # the new writes without modification.
└── schema/data/
    └── install-lock.v4.schema.json   # Extend `paths` pattern per research.md §5 (ADR 0026).

tests/
├── contract/    # New: install-lock.v4 schema accepts bare-root filenames for exclusive
│                # entries, still rejects them for behavior/skill/skills/nix_packages paths.
├── integration/ # New: adopt/install/remove for exclusive-category files (single molecule,
│                # two-molecule collision-refused case) and for nix_packages (two
│                # contributors, partial removal, last-contributor removal) — mirrors
│                # existing behavior-atom integration test structure.
└── unit/        # New: composition function (research.md §2) — sortedness, dedup,
                 # order-independence from adoption sequence.
```

**Structure Decision**: Single existing Python project (`src/spaex` + `tests/`); no new top-level project or directory structure. Two new modules under `src/spaex/install/` mirror the existing `src/spaex/behavior/` split (a dedicated home for the new materialization logic rather than growing `cli/install.py` directly), consistent with how `behavior/materialize.py` is already separated from `cli/install.py` today.

## Complexity Tracking

*(No Constitution Check violations — table intentionally omitted.)*
