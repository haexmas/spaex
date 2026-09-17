# ADR 0024: Independent merge ceiling for map-reduce composition

**Status**: Accepted
**Date**: 2026-09-17
**Related**: ADR 0022 (map-reduce Composer composition); Spec 026

## Context

PR #147's dogfooding exposed that the merge phase's input is composed
Markdown, not the raw fragment JSON used by batching. Two individually
valid batches can therefore produce composed bodies whose combined merge
payload exceeds the batching ceiling. Reusing one ceiling for both phases
also means retuning batch-call reliability silently retunes merge-call fit.

## Decision

`BatchingLimits` has a separately configured `merge_max_bytes` field. The
reducer uses this value for both flat-merge fit checks and pairwise merge
fit checks; `max_bytes` remains exclusively the batching ceiling. The
default merge ceiling is 40,000 bytes (`DEFAULT_MERGE_MAX_BYTES`) until
merge-specific timing and failure data justifies revisiting it.

## Consequences

- Batch and merge reliability can be tuned independently.
- Existing callers that configure `max_bytes` retain control over batch
  partitioning without unintentionally changing merge behavior.
- Merge-specific dogfooding data is still needed before changing the
  initial default.

