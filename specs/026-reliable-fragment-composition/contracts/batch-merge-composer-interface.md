# Contract: Batch/Merge Composition

Extends `specs/023-behavior-harness/contracts/composer-interface.md`. Everything in that document remains true of every individual call this contract describes — the sentinel format, Shape A/Shape B envelope, build fingerprints, failure categories and exit codes, and determinism aids are unchanged and are not repeated here. This document adds only what changes: composition is now zero or more **batch calls** followed by exactly one **merge call**, both instances of the same existing per-call contract.

## When this contract applies

A fragment set that fits in a single batch (today: below the byte-size ceiling from research.md §2) composes exactly as `composer-interface.md` already describes — one call, one Shape A/B response, no merge step. This is the existing, unmodified path; nothing about it changes. This contract only adds behavior for a fragment set spanning more than one batch.

## Batch call

Identical to `composer-interface.md`'s "Composer input"/"Composer output" contract, with two differences:

1. **Input scope**: `fragments` contains only the batch's own fragments (still sorted by scoped key). `clarifications` contains only currently-valid clarifications whose cited fragments are entirely within this batch.
2. **Shape A output**: the response body is the batch's composed Markdown (modality sections, per-clause citations) **without** the top-level `spaex-composed:source_hash=... build_input_hash=...` header — that header is added once, by the merge step, over the full original fragment set. A batch call never claims to speak for the whole build.

A batch call's Shape B (contradiction/overlap found *within this batch*) is handled by the existing clarification round-trip, scoped to this one batch call, bounded to one round-trip exactly as today (a second Shape B from the same batch call is `invalid-output`).

## Merge call

Runs once, after every batch has produced a `BatchComposition` (a batch that raised and resolved its own clarification contributes its post-resolution composed body, same as today's single-call flow).

**Input**: a JSON document structurally analogous to `ComposerInput`, but:
- `batch_compositions`: the ordered list of each batch's composed Markdown (not raw fragments).
- `clarifications`: only clarifications whose cited fragments span more than one batch (batch-local ones were already resolved and folded into the relevant `BatchComposition`).
- `expected_source_hash` / `expected_build_input_hash`: identical to today's contract — computed over the *entire* original fragment set, unchanged by batching.

**Output**: identical shape to today's Shape A/Shape B, with the `spaex-composed` header now added at this step (over the full-set hashes above). Shape A's body is the fully merged, deduplicated, citation-preserving final document — the same document a single whole-set call would have produced, byte-for-byte given the same runtime and inputs (research.md §6).

The merge call's Shape B (a contradiction spanning two batches) goes through the same one-round-trip-bounded clarification flow as any other call. Once resolved, the merge call is re-invoked once with the answer staged, exactly as `composer-interface.md` already specifies for a single call.

## Runtime consistency

Every batch call and the merge call in one composition attempt use the same resolved CLI runtime (`claude`, `codex`, or `gemini`), chosen once at the start of the attempt via the existing priority-order `shutil.which` resolution. No call in the attempt re-resolves or falls back to a different runtime mid-attempt.

## Failure surface

Unchanged categories (`timeout`, `runtime-error`, `invalid-output`, `quota`, `no-runtime`), unchanged exit codes 30-34. A failure in any single batch call or the merge call aborts the whole attempt the same way a single-call failure does today (FR-004): nothing publishes, the previously published constitution stays byte-unchanged. The diagnostic names which step (`batch-N` or `merge`) failed.

## Diagnostic log

`$SPAEX_COMPOSER_LOG` (default `.spaex/composer.log`) becomes a JSON-lines file: one record per completed step, appended as that step completes (not buffered until the whole attempt finishes), per data-model.md's `ComposerLogEntry`. On failure, every step that completed before the failure has an entry already on disk; the failing step's entry (if it produced any output before failing) is the last one. This is the only change to the failure-log contract; the env var, default path, and "see this file for diagnosis" hint are unchanged.
