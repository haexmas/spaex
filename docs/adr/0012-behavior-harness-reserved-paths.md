# ADR 0012: Reserved Paths for the Behavior Harness

**Status**: Draft (finalized under Spec 023 Phase 11 T059)
**Date**: 2026-09-11
**Related**:
[Spec 023](../../specs/023-behavior-harness/);
[Spec 023 plan](../../specs/023-behavior-harness/plan.md);
`.specify/memory/constitution.md` §Reserved paths, §Principle VI

## Context

Spec 023 introduces a behavior-harness layer that produces one committed
composed-constitution artifact plus several sidecar files. The constitution
already reserves `.spaex/constitution.md` as "committed content, not an
agent-writable cache" (§Reserved paths, v1.3.0). Spec 023 supersedes that
single-file path with a set of new paths:

- `<repo-root>/.spaex.md`, the composed constitution artifact
- `.spaex/constitution.d/`, the materialized per-molecule fragment tree
- `.spaex/clarifications.json`, persisted operator answers to Composer questions
- `.spaex/.stale`, sidecar flag written by `spaex add`/`spaex remove` when the
  add-time plausibility check surfaces a cross-molecule semantic contradiction
- `.spaex/composer.log`, raw Composer response log for diagnostics

Because `<repo-root>/.spaex.md` is regenerated on every `spaex install` from
the versioned fragments in `.spaex/constitution.d/`, we need to reconcile this
with Principle VI ("Self-Modifying Instructions Are Review-Gated"): what is
the review gate for a file the tool overwrites every install?

## Decision

TBD (this stub reserves the ADR number and captures the paths and framing;
final decision text lands in T059 with the full Spec 023 PR).

Working answer, subject to refinement:

- Update `.specify/memory/constitution.md` §Reserved paths to list the five
  new paths above, superseding the single `.spaex/constitution.md` entry.
- Frame the git diff on `<repo-root>/.spaex.md` at commit time as the review
  gate for Principle VI compliance. No sidecar `.migrated` file is needed
  because the artifact is content, not schema; every install re-derives from
  the versioned fragments, so the review happens on human-readable content.

## Consequences

TBD in T059.

## Alternatives considered

TBD in T059.
