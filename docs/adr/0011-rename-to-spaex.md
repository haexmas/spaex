# ADR 0011: Rename `haex-hive` to `spaex` and Ship v4 Manifest Vocabulary

**Status**: Accepted
**Date**: 2026-09-07
**Related**:
[Design source](../plans/2026-09-07-rename-to-spaex-design.md);
[Spec 014](../../specs/014-rename-to-spaex/);
[Spec 013 v3 vocabulary](../../specs/013-add-cli-and-molecule-rename/) (predecessor);
`.specify/memory/constitution.md` §Governance, §Principle V, §Principle VI;
Slot 015 placeholder [multi-environment declaration + orchestration](../plans/2026-09-07-slot-015-multi-environment-placeholder.md)

## Context

Two forces converged on 2026-09-07:

**Scope realignment**. The project's name embedded a `hive` metaphor implying
multi-device swarm. That vision was previously split out into a separate
project (`holzi`). What remains here is deliberately narrower: one repo, one
device, a reproducible coding harness. The `hive` metaphor no longer describes
the tool and would mislead new adopters.

**Distribution readiness**. Spec 013 landed the last big piece of the v3
vocabulary and the `add`/`remove` CLI. The tool is now usable end to end. To
distribute it as `pipx install spaex`, we need to burn the PyPI namespace we
actually intend to keep — not the `haex-hive` name we already knew we wanted
to drop.

## Decision

Rename every user-visible surface from `haex-hive` to `spaex` in one
coordinated feature (Spec 014):

- PyPI package name `haex-hive` → `spaex`.
- Python package `src/haex_hive/` → `src/spaex/`.
- CLI binary `haex` → `spaex`.
- Config filename `.haex-hive.json` → `.spaex.json` (and its `.lock` variant).
- Output directory `.haex-hive/` → `.spaex/`.
- Schema-version field `haex_hive_version: "3"` → `spaex_version: "4"`.
- Min-version field `haex_hive_min_version` → `spaex_min_version`.
- Environment variable `HAEX_HIVE_STATE` → `SPAEX_STATE`.
- GitHub repository `haexmas/haex-hive` → `haexmas/spaex`.

The name **spaex** is a portmanteau of `spec` (from spec-kit, on which the
project's workflow discipline rests) and `haex` (the maintainer's handle,
preserved as identity continuity). Confirmed available on PyPI and GitHub on
2026-09-07.

The schema shape does **not** change. v4 is structurally identical to v3;
only the two field renames above land in the schema. This preserves every
existing schema constraint (compounds/molecules/atoms vocabulary, SHA pinning,
category-open atoms map, npm/pip-shape install.lock).

The migrate chain gains a `v3_to_v4` transform, chained after the existing
v1→v2 and v2→v3 links. Consumers on v3 run `spaex migrate`, adopt the
`.spaex.json.migrated` sibling, and delete their legacy `.haex-hive.json`.

## Consequences

**Breaking change**. Every v3 consumer must migrate. Because the tool has no
external users on 2026-09-07 (memory: `haex_hive_pre_user`), the migration
UX is defensive rather than user-facing-critical.

**Constitution amendment**. `.specify/memory/constitution.md` is amended
1.4.0 → 1.4.1 (PATCH) for the prose rename. Principle text is unchanged.
Principle V explicitly anticipated this class of change ("the concrete field
name is bound to the `.haex-hive.json` schema version and MAY change across
schema majors without altering this principle"), so the amendment is a
formality on the meta-text, not a principle rewrite.

**PR sequencing** (see Clarification 2026-09-07 Q1 in spec 014). Five PRs
against `main`:
1. Schema payloads v4 (dead code).
2. v3→v4 migrate transform (must land before self-adopt).
3. Foundational rename + self-adoption + docs sweep (bundled so `main` never
   sees a state where the repo's own v3 manifests cannot be read by the v4
   loader).
4. Release workflow + first PyPI push at `v4.0.0`.
5. Polish + GH-repo rename + local-directory rename.

## Alternatives considered

- **Layer 1 surface-only rename** (PyPI name + README, everything else keeps
  `haex-hive`): rejected. The tool would be schizophrenic. Every error message,
  log line, config file, and env var would still read `haex-hive`. Worst of
  both worlds.
- **Layer 2 CLI-only rename** (schema stays v3): rejected. Users would type
  `spaex install` while editing `.haex-hive.json` with `haex_hive_version: "3"`.
  Still schizophrenic, just under a nicer binary name.
- **Hard cut without a migration path**: rejected. The chained migrate
  pattern (v1→v2→v3 established under Spec 013) is cheap to extend with a
  v3→v4 link and protects private forks/prototypes that live on v3.
- **MINOR constitution bump (1.5.0)**: rejected. Nothing was added to the
  principle set; the amendment is purely wording, which is PATCH per the
  Governance section's rules.
- **Fold dev-environment orchestration into 014**: rejected (per
  Clarification Q3). Multi-environment vocabulary and orchestration verbs
  (`spaex enter`, `spaex shell`, etc.) are a separate feature story deserving
  their own design; reserved as Slot 015.

## Follow-ups

- Local repository directory rename `/home/haex/Projekte/haex-hive` →
  `/home/haex/Projekte/spaex` (Phase 6 task T076). Explicitly deferred to
  after all PRs merge and the session is deliberately restarted — renaming
  the cwd out from under a running shell breaks the shell.
- Memory-file sweep in the operator's Claude Code memory directory (rename
  `haex_hive_*.md` → `spaex_*.md`). Also Phase 6.
- Slot 015 (multi-environment declaration + orchestration): design not yet
  started, opened when the maintainer has a concrete first use case.
