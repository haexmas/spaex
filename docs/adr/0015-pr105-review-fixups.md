# ADR 0015: Correct Fidelity Regressions from PR #105's Fragment Split

**Status**: Accepted
**Date**: 2026-09-11
**Related**:
[Spec 023](../../specs/023-behavior-harness/);
`.specify/memory/constitution.md`;
`.specify/memory/manifest.json`;
ADR 0014 (introduced the fragment split this ADR corrects)

## Context

PR #105 (ADR 0014) split this repo's own constitution into 18 standalone
behavior fragments. A post-merge code review compared every fragment
against its source bullet in `constitution.md` and found:

- `.specify/memory/manifest.json` was bumped to version `1.4.2`, but the
  root publisher `manifest.json` was never updated and still declared
  `1.4.1` for this molecule. `resolve.py`'s publisher/molecule version
  equality check (`MissingAtomManifestError`) would hard-fail install for
  every consumer the moment either manifest is resolved at a revision
  containing PR #105's commit.
- Several fragments dropped normative detail present in their source bullet
  (`external-sources-opt-in-per-project`: the required pinned-entry format
  and its cross-reference to Principle VI; `self-modifying-instructions-review-gated`:
  the concrete `spaex migrate` example and the review-gate/sidecar-swap
  sentence; `conventional-commit-messages`: the specific `1.2.0` version
  cutoff, replaced with a vague self-referential phrase).
- `constitution-enforcement-tooling` turned a conditional, not-yet-true
  statement ("CI, once introduced under Phase 7, validates...") into an
  unconditional present-tense MUST, which is currently false: CI today
  runs only `pytest` and `ruff check .`.
- `constitution-supersedes-spec-preferences` picked up an escalation clause
  that isn't in its own source bullet (the Governance section's
  "the principle wins by default") — it was carried over from the
  Development Workflow bullet, which `speckit-workflow-adherence` already
  fragments correctly on its own.
- ADR 0014 cited a "data-model.md's migration-awareness note" that does not
  exist in `data-model.md`.
- `constitution.md`'s own Development Workflow section still said "the 7
  principles above", a pre-existing stale count; the document defines 8
  (I-VIII), as ADR 0014 itself counts correctly.

## Decision

Fix each item above in place: re-sync both `manifest.json` files to
`1.4.3`, restore the dropped normative detail in the four affected
fragments, restore the CI bullet's Phase-7 conditional, trim the borrowed
escalation clause, drop the broken ADR 0014 citation, and correct "7" to
"8" in `constitution.md`. None of these change what any principle
requires; they restore what PR #105's fragment split unintentionally
dropped, added, or left stale. Per this constitution's own version-bump
rules, this is a PATCH-level correction (wording/clarification/typo
fixes, no principle content change).

## Consequences

- `.spaex.md` composed from this molecule after a future `spaex install`
  will match `constitution.md`'s actual text again, with no unconditional
  CI claim it can't back up and no orphaned cross-fragment duplication.
- The publisher/molecule manifest version mismatch that would have broken
  every consumer's install once resolved is fixed before it reaches any
  such revision.
