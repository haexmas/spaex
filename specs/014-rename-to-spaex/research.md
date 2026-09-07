# Research: Rename to spaex

**Feature**: 014-rename-to-spaex
**Phase**: 0
**Purpose**: Ratify the design-source decisions and record the alternatives considered so downstream phases can trace every choice.

The authoritative technical reasoning lives in [docs/plans/2026-09-07-rename-to-spaex-design.md](../../docs/plans/2026-09-07-rename-to-spaex-design.md). This file names each decision compactly with the alternatives evaluated during the planning conversation.

## D1: Layer of the rename

**Decision**: Layer 3 (full breaking change through the schema and env-var surface). PyPI name, Python package, CLI binary, config filename, output dir, schema-version field, min-version field, env var, GitHub repo all rename together.

**Rationale**: A partial rebrand (Layer 1 surface-only or Layer 2 CLI-only) leaves the tool schizophrenic (spaex on the outside, `haex_hive`/`.haex-hive.json` on the inside), generates confusion in every error message and log line, and locks the new PyPI namespace to a name that would still leak the old identity.

**Alternatives**:
- **Layer 1 (PyPI + README only)**: rejected. Not a rebrand, a marketing sticker.
- **Layer 2 (CLI binary too, schema untouched)**: rejected. Users would type `spaex install` but edit `.haex-hive.json` with `haex_hive_version: "3"` in it. Worst of both worlds.

## D2: Migration strategy

**Decision**: Extend the existing migrate chain in `src/spaex/migrate/transform.py` with a `v3_to_v4` transform. Chain order becomes v1→v2→v3→v4. v1→v2 and v2→v3 transformers stay intact.

**Rationale**: The chained transform pattern is established, tested, and cheap to extend. Principle VI's schema-migrations clause requires the `.migrated` sidecar shape, which the existing infrastructure already provides. Cutting the chain to save code buys nothing (pre-user, but private forks and prototypes still exist).

**Alternatives**:
- **Hard cut (no migration path)**: rejected. Pre-user status makes it defensible but not attractive; the incremental cost of one more link is minimal.
- **New standalone migrator**: rejected. Would duplicate proposal-registry, dry-run, and exit-code infrastructure.

## D3: Constitution amendment scope

**Decision**: Prose-only amendment (title and body references from `haex-hive Constitution` and prose mentions of `haex-hive`/`.haex-hive.json` to `spaex Constitution` and `.spaex.json`). Principle text unchanged. Version bump PATCH 1.4.0 → 1.4.1.

**Rationale**: The Governance section defines PATCH as "wording, clarifications, typo fixes, non-semantic refinements." Renaming the tool in prose fits exactly. No principle is removed, added, or materially expanded. Principle V explicitly anticipates the config-filename change ("MAY change across schema majors without altering this principle").

**Alternatives**:
- **MINOR bump (1.5.0)**: rejected. Nothing added to the principle set.
- **Skip the amendment**: rejected. The title itself contains `haex-hive`, and diagnostic tooling that reads the constitution would produce off-brand output.
- **Full principle rewrite**: rejected. Out of scope for a rename; would surface a different decision requiring its own ADR.

## D4: Release workflow

**Decision**: GitHub Actions workflow at `.github/workflows/release.yml`, triggered by `v*` tag push. Build sdist plus wheel with `python -m build`, publish to PyPI via `pypa/gh-action-pypi-publish@release/v1` using OIDC Trusted Publishing. Job runs inside GitHub Environment `pypi`. No PyPI tokens stored anywhere.

**Rationale**: Trusted Publishing is the current PyPA-recommended path (no long-lived tokens, no rotation burden, OIDC-verified provenance). The maintainer registered the pending publisher on 2026-09-07.

**Alternatives**:
- **PYPI_API_TOKEN in GitHub Secrets**: rejected. Token rotation is manual and easy to forget; leaked-token blast radius is significant.
- **TestPyPI first, PyPI after manual promotion**: rejected for first release. Adds a stage without adding safety (the `pypi` environment already gates the publish behind a required-reviewer if the maintainer wants). Reserved as a future addition when release cadence justifies it.
- **`softprops/action-gh-release` step in the workflow**: rejected for MVP. Keeps the workflow minimal; `gh release create v4.0.0 --generate-notes` as a manual post-workflow step is one command.

## D5: Sequencing and PR shape

**Decision**: Six sequential PRs against `main`, no stacked branches. Order:
1. Schema payloads v4 plus version dispatch (loader still on v3).
2. Foundational rename (Python package, CLI binary, constants, env var).
3. Migrate v3→v4 transform.
4. Self-adoption (repo's own manifests migrate).
5. Docs sweep (README, quickstart, CLAUDE.md, AGENTS.md, ADRs).
6. Release workflow plus first PyPI push at `v4.0.0`.

**Rationale**: Matches the Spec 013 cadence (PRs 70-77). Each phase is reviewable in isolation. Linear order prevents merge-conflict churn. Memory `pr_strategy_stacked_phases` confirms phase branches target `main` in this repo, not each other.

**Alternatives**:
- **Single monolithic PR**: rejected. Unreviewable, unbisectable.
- **Stacked branches (each phase branches from the previous)**: rejected. Memory `pr_strategy_stacked_phases` documents why this repo avoids stacked-branch PRs.
- **Parallel phases**: rejected. Guaranteed merge conflicts on ~150 files.

## D6: Dev-environment placement (documentation-only)

**Decision**: FR-043 clarifies in the README that molecules can declare a `dev_environment` atom category (containing `flake.nix`, `Dockerfile`, `devcontainer.json`, `.envrc`, `shell.nix`, etc.) and `spaex install` places those files. No new tool feature; the molecule architecture already permits arbitrary category names.

**Rationale**: The tagline reads "reproducible coding harnesses for any repo and development environment," and this documentation change makes the second half of that promise concrete without new code. Orchestration (`spaex enter`, `spaex shell`, `spaex dev up`) is out of scope for 014, reserved as slot 015.

**Alternatives**:
- **Add orchestration commands to 014**: rejected. Doubles the feature scope; would require its own contracts, tests, and design phase.
- **Silently permit but do not document**: rejected. The tagline promises this capability; not documenting it is a documentation-actual-behavior mismatch.

## D7: Schema `$id` audit deferred to Phase 1

**Decision**: Phase 1 (in the implementation) audits the current v3 schema `$id` values. If they contain absolute URLs like `https://haex-hive.dev/...`, decide per finding: rename to `https://spaex.dev/...` (if the domain is or will be maintained), or make the `$id` relative (`consumer-manifest.v4.schema.json` etc.), whichever matches the current pattern.

**Rationale**: Cannot decide without seeing the current values. Deferring one grep to Phase 1 is cheaper than speculating here.

**Alternatives**:
- **Decide now**: rejected. Requires reading files this phase does not otherwise touch.

## D8: `dev_environment` is not a validated category

**Decision**: The v4 molecule-manifest schema treats `atoms{}` as a `Dict[str, List[str]]` with open category keys, same as v3. `dev_environment` is a recognized-by-convention category; it does not need enumeration in the schema. Existing categories (`constitution`, `slash_commands`, `agents`, `mcps`, etc.) stay unenumerated for the same reason.

**Rationale**: v3 already treats categories as open. Enumerating them at the schema layer would create a bottleneck for adding new categories (which is a feature, not a bug, of the current design).

**Alternatives**:
- **Enumerate categories at the schema layer**: rejected. Would require a schema change on every new category and would push category vocabulary into the schema instead of the community.

## D9: Version-field name choice: `spaex_version` (not `version`)

**Decision**: Rename `haex_hive_version` to `spaex_version` (not to a generic `version`). Same for `spaex_min_version` (not `min_version`).

**Rationale**: Consistent with the current pattern. A generic `version` field would collide with any other tool that reads the same JSON file (e.g., npm's `package.json` or an unrelated tool). The `spaex_` prefix keeps the version identity attached to the tool that owns the schema.

**Alternatives**:
- **`version` / `min_version`**: rejected on collision grounds.
- **`schema_version` / `schema_min_version`**: rejected as vague; two tools with a `schema_version` collide the same way.

## D10: Preserve domain vocabulary (`atoms`, `molecules`, `compounds`)

**Decision**: `atoms{}`, `molecules[]`, `compounds[]` names and semantics stay unchanged in v4.

**Rationale**: These names survived Spec 013's rename and are a stable part of the model. Renaming them again would inflate scope, break every fixture, and re-open a debate that was closed in Spec 013.

**Alternatives**:
- **Rename to align with the "chemistry" branding**: rejected. Terms are already chemistry-themed and are load-bearing in ADR 0009 and Spec 013.

## Open questions

None. Every design-source decision is captured above with alternatives.
