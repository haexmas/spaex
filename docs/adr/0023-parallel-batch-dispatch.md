# ADR 0023: Parallel batch dispatch

**Status**: Accepted
**Date**: 2026-09-17

## Context

ADR 0022's map-reduce composer dispatches one Composer call per batch
sequentially. Dogfooding this project's own real fragment set (27
fragments / 9 molecules, 2 batches + 1 merge) took ~24 minutes wall-clock
end to end; batch-1 alone (6 unrelated molecules bundled together only
because `batching.partition()` groups purely by sorted scoped-id and
byte-size ceiling, with no topic awareness) took 695-1145s across runs,
while batch-2 (18 fragments, one molecule) took 136-213s. Batches are
independent of each other until the merge step - none needs another's
output - so dispatching them sequentially spends wall-clock time summing
independent latencies that could instead overlap.

## Decision

`composer.reduce.compose()` dispatches every batch's initial Composer call
concurrently on the standard library's bounded `ThreadPoolExecutor`;
`subprocess.run` releases the GIL while waiting on the child process, so
threads give real parallelism here without needing `asyncio`, while the
executor's default worker cap prevents one thread and subprocess per batch.
The CLI
runtime is resolved once via the new `invoke.resolve_runtime_name` -
exactly the `shutil.which` scan `invoke_step` already did, extracted so it
can run before any call fires - and forced on every batch from the start,
rather than "learned" from whichever call happens to return first (ADR
0022's phrasing; research.md §4 already specified resolving "before
dispatching any batch call", which this now literally matches). Each
batch's own Shape-B resolution and completeness check (`verify_completeness`,
Spec 026 T020 follow-up) still run sequentially afterward, in fixed batch
order, since those touch the shared `ClarificationsStore`.
`ThreadPoolExecutor.map`'s results preserve argument order regardless of
completion order, so the resulting node order - and therefore byte
reproducibility (SC-003) - does not depend on which batch happens to
answer first.

Concurrent batch calls now append to `$SPAEX_COMPOSER_LOG` from multiple
threads; `invoke.append_composer_log_entry` gained a lock so two threads'
writes can no longer interleave mid-line and corrupt the JSON-lines file.

## Consequences

- A batch's own Shape-A response is no longer guaranteed to skip a sibling
  batch just because it turned out incomplete or a sibling timed out
  first: every batch fires regardless of another's outcome. The safety
  property that matters (an incomplete or contradictory result is never
  published) is unaffected - `verify_completeness`/Shape-B handling still
  runs before anything reaches the merge step - only the "avoid one extra
  LLM call when a sibling is already doomed" optimization is given up in
  exchange for the much larger wall-clock win.
- The merge phase (already few calls at today's scale) stays sequential;
  parallelizing merge-tree levels is a possible follow-up, not part of
  this change.
- Progress lines (`composer: invoking/responded/composed ...`) from
  concurrent batches can now interleave in terminal output; this is a
  cosmetic readability tradeoff, not a correctness one.

## Maintainability follow-up

`invoke.py` and `reduce.py` are cohesive composer-boundary modules but are
already above the repository's 500-line maintainability boundary. This PR
keeps the runtime/parser/logging and reducer/tree state together so the
concurrency change remains one reviewable protocol change. Before the next
non-trivial composer feature, extract runtime/process/JSONL logging concerns
from `invoke.py` and merge-tree mechanics from `reduce.py` into focused
modules, moving their tests with the respective boundaries.
