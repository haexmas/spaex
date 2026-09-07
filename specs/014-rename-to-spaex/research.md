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

**Decision (updated per Clarification 2026-09-07 Q1)**: Five sequential PRs against `main`, no stacked branches. Order:
1. Schema payloads v4 plus version dispatch (loader still on v3). Design-doc Phase 1.
2. Migrate v3→v4 transform (added by extending the chain). Design-doc Phase 3, promoted ahead of the foundational rename so the self-adopt step in the next PR can invoke `spaex migrate`.
3. **Foundational rename plus self-adoption (combined)**. Design-doc Phases 2 + 4 in one PR. Bundling is required: Phase 2 alone leaves the repo's own v3 manifests unreadable by the new v4 loader, breaking `main`. Bundling P2+P4 keeps `main` coherent at every merge boundary. Docs sweep (former Phase 5) rides in the same PR since it also touches `haex-hive`/`haex` references.
4. Release workflow plus first PyPI push at `v4.0.0`. Design-doc Phase 6.
5. Polish, GH-repo rename, memory-file sweep, local-directory rename. Design-doc Phase 7 equivalent.

**Rationale**: Matches the Spec 013 cadence (PRs land against `main`, not on top of each other). Bundling the foundational rename with the self-adopt is the only way to keep `main` in a coherent state, because the loader's v4-only dispatch (Phase 2) and the repo's own manifest migration (Phase 4) form an atomic pair.

**Alternatives**:
- **Six separate PRs** (original design-source ordering): rejected per Q1 clarification. `main` would be in a broken state between the P2 and P4 merges.
- **Single monolithic PR**: rejected. Unreviewable, unbisectable.
- **Stacked branches (each phase branches from the previous)**: rejected. Memory `pr_strategy_stacked_phases` documents why this repo avoids stacked-branch PRs.
- **Parallel phases**: rejected. Guaranteed merge conflicts on ~150 files.

## D6: Environment-config placement (generic, no naming commitment)

**Decision (updated per Clarification 2026-09-07 Q3)**: FR-043 says only that molecule authors can declare any atom category name they want and `spaex install` places declared files. Spec 014 makes **no** commitment to a specific category name (`dev_environment`, `dev-environment`, `dev_env`, `devenv`, ...) for environment-config files. Multi-environment vocabulary (dev/staging/prod), consumer-side selection, and orchestration are all Spec 015 scope.

**Rationale**: The 2026-09-07 clarification surfaced that "dev environment" is one of several environments a repo might need (dev, staging, prod, ...), and orchestration ("bring the repo up in environment X") is a bigger product intent that deserves its own design. Committing to a single-environment category name in 014 would either be premature (locking in a name that Slot 015 wants to change) or misleading (implying multi-env support that does not exist yet). The generic form keeps the README honest: the schema is open, publishers can experiment, Spec 015 will formalize.

**Alternatives**:
- **Commit to `dev_environment`**: rejected per Q3. Locks in a name before the multi-env story is designed.
- **Drop FR-043 entirely**: rejected. The tagline mentions "development environment"; leaving no README paragraph would be a promise-behavior mismatch. Generic form preserves the promise without over-committing.
- **Add multi-env vocabulary directly to 014**: rejected. Turns a rename spec into a rename-plus-feature spec; risks landing neither well.

## D7: Schema `$id` audit deferred to Phase 1

**Decision**: Phase 1 (in the implementation) audits the current v3 schema `$id` values. If they contain absolute URLs like `https://haex-hive.dev/...`, decide per finding: rename to `https://spaex.dev/...` (if the domain is or will be maintained), or make the `$id` relative (`consumer-manifest.v4.schema.json` etc.), whichever matches the current pattern.

**Rationale**: Cannot decide without seeing the current values. Deferring one grep to Phase 1 is cheaper than speculating here.

**Alternatives**:
- **Decide now**: rejected. Requires reading files this phase does not otherwise touch.

## D8: Atom-category keys stay open

**Decision**: The v4 molecule-manifest schema treats `atoms{}` as a `Dict[str, List[str]]` with open category keys, same as v3. No category name is enumerated. Existing categories (`constitution`, `slash_commands`, `agents`, `mcps`, etc.) are conventions, not schema-enforced.

**Rationale**: v3 already treats categories as open. Enumerating them at the schema layer would create a bottleneck for adding new categories (a feature, not a bug, of the current design). Per D6, Spec 014 makes no naming commitment for environment-config categories in particular; those live under whatever convention Spec 015 lands.

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
