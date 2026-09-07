# Implementation Plan: Rename to spaex (v4 breaking) and first PyPI release

**Branch**: `014-rename-to-spaex` | **Date**: 2026-09-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/014-rename-to-spaex/spec.md`

**Related**:
- Design source: [docs/plans/2026-09-07-rename-to-spaex-design.md](../../docs/plans/2026-09-07-rename-to-spaex-design.md)
- Preceding feature: [specs/013-add-cli-and-molecule-rename/](../013-add-cli-and-molecule-rename/) (landed 2026-09-06)

## Summary

Full Layer-3 rebrand from `haex-hive` to `spaex`. Every user-visible surface renames in one coordinated feature: PyPI package, Python package, CLI binary, config file, output directory, schema version field, min-version field, environment variable, GitHub repo. Schema bumps from v3 to v4 (structural shape unchanged, only version-field name and value change). Migrate chain extended with `v3_to_v4`. Repo self-adopts. Constitution amended for prose references only (PATCH 1.4.0 → 1.4.1). First PyPI release under the new name at `4.0.0`, published via GitHub Actions and OIDC Trusted Publishing.

Ships as **five sequential PRs against `main`** (revised per Clarification 2026-09-07 Q1). The task-file's six phases map onto the PRs as:

1. PR #1: tasks-Phase 1 (schema payloads v4, dead code).
2. PR #2: tasks-Phase 3 (v3→v4 migrate transform, promoted ahead of the foundational rename so the self-adopt step can use it).
3. PR #3: tasks-Phase 2 + tasks-Phase 4 combined (foundational rename + self-adoption + docs sweep). Bundled to keep `main` coherent at every merge boundary.
4. PR #4: tasks-Phase 5 (release workflow, first PyPI push at `v4.0.0`).
5. PR #5: tasks-Phase 6 (polish, GitHub-repo rename, memory sweep, local-directory rename as the very last step).

Full technical detail in the design source; this plan restates it in Speckit shape.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: `jsonschema>=4.18` (unchanged)
**Storage**: Local filesystem. JSON manifests (`.spaex.json`, `manifest.json`, `.spaex/install.lock`).
**Testing**: pytest, pytest-subprocess (unchanged from Spec 013)
**Target Platform**: Linux, macOS, WSL2. Python-only wheel (`py3-none-any`).
**Project Type**: CLI tool (single project layout: `src/spaex/`, `tests/`)
**Performance Goals**: N/A. Rename introduces no perf-sensitive path.
**Constraints**:
- Byte-identical `.spaex/install.lock` across two consecutive `spaex install` runs (Spec 008 SC-003 preserved).
- No live `haex_hive` or `haex-hive` reference in `src/`, `tests/`, `pyproject.toml`, `README.md`, `CLAUDE.md`, `AGENTS.md` after Phase 6.
- Migration transform must be deterministic given identical inputs (Principle VI).
**Scale/Scope**: ~150-170 files touched. Blast radius sized in the design source (approx. 693 `haex_hive` identifier occurrences, 1587 `haex-hive` occurrences, 319 schema-version-field occurrences, 152 `HAEX_HIVE` env occurrences).

## Constitution Check

Gate: MUST pass before Phase 0. Re-checked after Phase 1.

### Principle-by-principle assessment

- **I. No Secrets in Git (NON-NEGOTIABLE)**: Not engaged. Rename touches no secret material.
- **II. No Local Absolute Paths in Versioned Config (NON-NEGOTIABLE)**: Not engaged. Rename does not add or change any path handling.
- **III. Project Identity Is Device-Independent (NON-NEGOTIABLE)**: Not engaged.
- **IV. Cross-Repo References Pin Immutable Revisions (NON-NEGOTIABLE)**: Not engaged. Rename does not change the reference format.
- **V. External Sources Are Opt-in Per Project (NON-NEGOTIABLE)**: **Anticipated by the principle text.** Principle V explicitly states: "the concrete field name is bound to the `.haex-hive.json` schema version and MAY change across schema majors without altering this principle." Renaming `.haex-hive.json` to `.spaex.json` and `atoms[]`-style allowlist field references to the v4 shape are exactly the case the principle authorizes. **PASS.**
- **VI. Self-Modifying Instructions Are Always Review-Gated (NON-NEGOTIABLE)**: **Directly engaged by the migrate work.** Principle VI's schema-migrations clause (added v1.3.0) requires (a) `.migrated` sidecar output, (b) reviewable diff, (c) deterministic given identical inputs, (d) `--dry-run`/`--check` support. Spec FR-020 through FR-027 commit to exactly this shape (`v3_to_v4` extends the existing chain that already implements the pattern for v1→v2 and v2→v3). **PASS.**
- **VII. Relay Unavailability Never Blocks Local Work (NON-NEGOTIABLE)**: Not engaged. No relay in this project.
- **VIII. No Concealment Instructions in Agent Output (NON-NEGOTIABLE)**: Not engaged.

### Development-workflow discipline

- **Sequenced phases**: Spec's six phases sequence the rename linearly. Matches the Spec 013 cadence and the design source's phasing discipline. **PASS.**
- **ADR for the rename decision**: FR-045 commits to adding an ADR (next free number, likely 0011) in Phase 5 alongside the docs sweep. **PASS.**
- **PR flow to `main`**: All six phases land through PRs against `main`. Matches Spec 013 pattern. **PASS.**
- **Conventional Commits v1.0.0**: The v4 breakage is signaled with the `!` marker on the primary feat commit (e.g., `feat!: rename to spaex, v4 manifest vocabulary`) plus a `BREAKING CHANGE:` footer. **PASS.**
- **Rebase-merge or merge-commit only, no squash-merge**: Follow existing repo practice. **PASS.**

### Constitution amendment scope

`.specify/memory/constitution.md` is itself rewritten as part of Phase 4 (self-adoption). Under Governance:
- (a) ADR: covered by FR-045.
- (b) Constitution file update: covered by FR-031.
- (c) Version bump: **PATCH 1.4.0 → 1.4.1** because the amendment is purely wording (tool-name references and title), not semantic (no principle removed, added, or materially expanded).

The Sync Impact Report block at the top of the constitution is updated with the amendment metadata.

### Gate result: PASS

No principle violations. No unjustified deviations. Proceed to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/014-rename-to-spaex/
├── plan.md                # This file
├── research.md            # Phase 0 output (decision log ratifying design-doc choices)
├── data-model.md          # Phase 1 output (v4 manifest shapes)
├── quickstart.md          # Phase 1 output (install + adopt walkthrough under the new name)
├── contracts/             # Phase 1 output
│   ├── spaex-cli.md
│   ├── spaex-migrate.v3-to-v4.md
│   ├── consumer-manifest.v4.schema.json
│   ├── molecule-manifest.v4.schema.json
│   ├── publisher-manifest.v4.schema.json
│   ├── install-lock.v4.schema.json
│   └── release-workflow.md
├── checklists/
│   └── requirements.md    # Written by /speckit-specify
└── tasks.md               # Phase 2 output (/speckit-tasks command)
```

### Source Code (repository root, post-rename)

```text
src/spaex/                 # renamed from src/haex_hive/ in Phase 2
├── cli/
│   ├── main.py
│   ├── add.py
│   ├── remove.py
│   ├── install.py
│   ├── migrate.py
│   └── constitution/
├── model/
│   ├── consumer_manifest.py
│   ├── molecule_manifest.py
│   ├── publisher_manifest.py
│   ├── install_lock.py
│   └── molecule_id.py
├── schema/
│   ├── loader.py
│   ├── validator.py
│   └── data/
│       ├── consumer-manifest.v4.schema.json     # added in Phase 1
│       ├── molecule-manifest.v4.schema.json     # added in Phase 1
│       ├── publisher-manifest.v4.schema.json    # added in Phase 1
│       ├── install-lock.v4.schema.json          # added in Phase 1
│       └── visibility-marker.v1.schema.json     # unchanged (Spec 008)
├── constitution/
│   └── publish.py
├── install/
│   ├── manifest_lock.py
│   └── write_and_reinstall.py
├── migrate/
│   ├── transform.py                             # v1→v2→v3→v4 chain
│   └── registry.py
└── git/
    └── publisher_fetch.py

tests/
├── contract/
├── integration/
├── install/integration/
├── cli/
└── unit/

.github/workflows/
├── spec-007-ci.yml         # existing, mechanical rename of internal path references
└── release.yml             # added in Phase 6

pyproject.toml              # name=spaex, entry-point spaex, package spaex
README.md                   # rewritten in Phase 5
CLAUDE.md                   # updated in Phase 5
AGENTS.md                   # updated in Phase 5
docs/adr/0011-rename-to-spaex.md   # added in Phase 5
.specify/memory/constitution.md    # amended prose in Phase 4, version 1.4.1
```

**Structure Decision**: Single-project CLI layout (unchanged from Spec 013). Only the top-level Python package renames from `haex_hive` to `spaex`.

## Complexity Tracking

No Constitution Check violations to justify. Table intentionally omitted.
