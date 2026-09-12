# ADR 0012: Reserved Paths for the Behavior Harness

**Status**: Accepted
**Date**: 2026-09-11
**Related**:
[Spec 023](../../specs/023-behavior-harness/);
[Spec 023 plan](../../specs/023-behavior-harness/plan.md);
`.specify/memory/constitution.md`; ADR 0018

## Context

Spec 023 produces one committed composed-constitution artifact plus several
sidecar files. The complete spaex-owned project state is kept under `.spaex/`:

- `.spaex/manifest.json`, the consumer manifest
- `.spaex/manifest.json.lock`, the advisory manifest lock
- `<repo-root>/.spaex/constitution.md`, the composed constitution artifact
- `.spaex/constitution.d/`, the materialized per-molecule fragment tree
- `.spaex/clarifications.json`, persisted operator answers to Composer questions
- `.spaex/.stale`, sidecar flag written by `spaex add`/`spaex remove` when the
  add-time plausibility check surfaces a cross-molecule semantic contradiction
- `.spaex/composer.log`, raw Composer response log for diagnostics

Because `<repo-root>/.spaex/constitution.md` is regenerated on every `spaex install` from
the versioned fragments in `.spaex/constitution.d/`, we need to reconcile this
with Principle VI ("Self-Modifying Instructions Are Review-Gated"): what is
the review gate for a file the tool overwrites every install?

## Decision

The paths above are the canonical spaex layout. The Spec-Kit constitution is
not a spaex output and remains at `.specify/memory/constitution.md`.
Generated constitution content is review-gated as a normal proposed git diff;
it is not a schema migration.

## Consequences

spaex state has one discoverable owner directory. Atomic publication preserves
the manifest and active advisory lock while replacing generated outputs.

## Alternatives considered

Keeping a root-level manifest or composed Markdown file was rejected because
it split ownership across unrelated paths and coupled spaex to Spec Kit's
directory layout.
