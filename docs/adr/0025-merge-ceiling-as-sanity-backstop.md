# ADR 0025: Merge ceiling as a sanity backstop, not a reliability tuning value

**Status**: Accepted
**Date**: 2026-09-17
**Related**: ADR 0022 (map-reduce Composer composition); ADR 0024 (independent
merge ceiling, corrected by this ADR); Spec 026

## Context

ADR 0024 gave the merge phase its own `merge_max_bytes` ceiling (40,000
bytes), independent of the batching ceiling, but explicitly deferred the
actual value to "until merge-specific timing and failure data justifies
revisiting it." That data arrived the same day: a real dogfood build
against this project's own fragment set (4 batches, 27 fragments) needed
its root-level merge - combining two already-merged nodes that together
represent every adopted fragment - to hold roughly 52,000 bytes, comfortably
exceeding the 40KB ceiling.

Investigating *why* surfaced a problem no ceiling value alone fixes: a merge
call does not meaningfully compress its input. One real level-0 merge took
28,770 raw input characters to 28,254 raw output characters - essentially
no compression. ADR 0022/Spec 026 research.md §1's original assumption
("composed text is far smaller than the raw fragments it summarizes, so the
merge step scales sub-linearly") does not hold for this LLM/prompt
combination. Since a pairwise-tree's root node is, by construction, the
union of every leaf, its input size grows with the project's *total*
adopted content, not sub-linearly - so any fixed reliability-tuned ceiling
(the same kind of tight, evidence-based band `DEFAULT_MAX_BATCH_BYTES` uses)
would need re-tuning again every time a project's total content grows past
whatever was last measured, the same failure mode Spec 026 exists to
eliminate for batching.

## Decision

Stop treating `DEFAULT_MERGE_MAX_BYTES` as a reliability-tuned value.
Raise it to 1,000,000 bytes (1MB) and document it as a generous sanity
backstop - guarding only against a genuinely pathological single fragment
set (e.g. vendored or generated content accidentally adopted as a
fragment) - not a per-call reliability guarantee. A merge call's actual
reliability at a given size is left to surface as its own typed failure
(timeout, invalid-output) if and when it happens, the same way any other
Composer call's reliability is discovered, rather than being pre-emptively
guessed at via the ceiling.

Two ways to make the root merge's size actually bounded (not just backed
off) were considered and rejected for now, in favor of this stopgap:
- **Deepen the merge tree beyond what pairwise halving allows**: does not
  help - the root pair's *combined* size is what matters, and pairwise
  merge always operates on exactly two nodes regardless of tree depth.
- **Combine already-composed, already-contradiction-checked batches
  deterministically in code instead of via one final LLM call**: would
  genuinely scale independent of total content, since it would not need
  the LLM to reproduce content it isn't compressing anyway. Rejected here
  as materially larger scope than this fix, not because it is wrong -
  revisit if a project's total adopted content grows enough that even a
  1MB backstop starts binding.

## Consequences

- FR-001/FR-007's "no fixed ceiling" claim now honestly holds only up to
  whatever project size keeps the root merge under the 1MB backstop, not
  unconditionally. A project approaching that scale needs the deterministic-
  combination alternative above, not another ceiling bump.
- A merge call large enough to be genuinely unreliable is no longer
  pre-emptively blocked; it will instead surface as a timeout or
  invalid-output failure when it happens, same as any other Composer call.
- ADR 0024's specific numeric default (40KB) and its "reliability tuning"
  framing are superseded by this ADR; ADR 0024 itself is left unedited as
  the historical record of the independent-ceiling decision, which still
  stands.
