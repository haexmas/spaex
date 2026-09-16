# ADR 0022: Map-reduce Composer composition for reliability at scale

**Status**: Accepted
**Date**: 2026-09-16

## Context

Spec 023's Composer sends the entire adopted fragment set as one
non-interactive LLM call, reasoning about every fragment's overlaps and
contradictions and producing one long, strictly-formatted, fully-cited
document in a single turn. Against this project's own real fragment set (9
adopted molecules, ~60KB composer input), 4 of 5 real `spaex install`
attempts timed out even at a 600s budget, and the one attempt that did
return a response silently dropped 9 fragments (correctly caught by the
existing FR-012b completeness check, which aborted rather than publishing
incomplete output). The single-shot, whole-fragment-set approach does not
scale past what fits reliably in one LLM turn, and Spec 026's FR-001/FR-007
explicitly reject any fixed molecule/fragment-count ceiling.

## Decision

Composition becomes map-reduce. `batching.partition()` groups the
canonically-sorted fragment set by molecule into fixed-size `Batch`es
(bounded by a fragment-count guard and a serialized-byte ceiling, never
splitting one molecule's fragments across batches); an oversized molecule
group fails before any LLM call with the existing typed
`behavior-composer-invalid-output` diagnostic (`reason=input-too-large`),
never silently truncated. `composer.reduce.compose()` dispatches one
Composer call per batch, reusing `invoke.py`'s `_call_cli`/`_parse`
machinery and the sentinel/Shape A/Shape B contract completely unchanged,
then reduces the batches' composed output (each stripped of its
placeholder header) with a bounded merge phase: one flat N-ary merge when
the merge input fits the same byte ceiling, otherwise a deterministic
pairwise tree with odd-node carry-forward, repeated until one
header-bearing root document remains. One CLI runtime is resolved from the
first call and forced for every later call in the attempt (FR-011). A
fragment set that fits in a single batch keeps the exact, unmodified
single-call path (`orchestrate.py` never enters `reduce.py` at all),
preserving byte-for-byte behavior for the common case (SC-004).

New entities: `Batch` (fragments + batch-local clarifications assigned to
one call), `BatchComposition` (one batch's composed, headerless output),
and `MergeNodeInput` (two or more composed inputs plus whichever
clarifications span exactly those inputs, feeding one merge call). Shape-B
handling is generalized from the original whole-build-only round trip into
`composer.clarify.resolve_step_clarifications`, callable once per batch or
merge node, each bounded to one re-invocation exactly as before.
`$SPAEX_COMPOSER_LOG` becomes JSON-lines, one record per completed
invocation (`step`, `invocation`, `phase`, `raw_output`, `outcome`),
truncated once per attempt and appended thereafter, so a later step's
failure can never erase an earlier step's evidence.

## Consequences

- No fixed ceiling on adopted molecule/fragment count: growing the
  fragment set adds more (bounded) batches and, past the merge-input
  ceiling, more (bounded) tree levels — never a larger single call.
- The shared clarification round-trip helper lives in a new
  `spaex.behavior.composer.clarify` module rather than directly in
  `orchestrate.py`: `orchestrate.py` imports `reduce.py` for the
  multi-batch entry point, so a reverse import from `reduce.py` back into
  `orchestrate.py` would be circular. `orchestrate._resolve_clarifications`
  now delegates to `clarify.resolve_step_clarifications` for the legacy
  path, unchanged in behavior.
- Occasional manual retry remains the accepted recovery path on a genuine
  failure (FR-010); this feature does not add automatic retry or
  self-healing.
