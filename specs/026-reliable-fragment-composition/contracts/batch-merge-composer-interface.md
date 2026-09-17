# Contract: Batch/Merge Composition

Extends `specs/023-behavior-harness/contracts/composer-interface.md`. Everything in that document remains true of every individual call this contract describes — the sentinel format, Shape A/Shape B envelope, build fingerprints, failure categories and exit codes, and determinism aids are unchanged and are not repeated here. For a fragment set spanning multiple batches, this document adds the requirement for two or more **batch calls** followed by a bounded merge reduction. A fragment set that fits in one batch keeps the existing one-call path and has no merge call.

## When this contract applies

A fragment set that fits in a single batch (today: below the byte-size ceiling from research.md §2) composes exactly as `composer-interface.md` already describes — one call, one Shape A/B response, no merge step. This is the existing, unmodified path; nothing about it changes. This contract only adds behavior for a fragment set spanning more than one batch.

## Batch call

Identical to `composer-interface.md`'s "Composer input"/"Composer output" contract, with two differences:

1. **Input scope**: `fragments` contains only the batch's own fragments (still sorted by scoped key). `clarifications` contains only currently-valid clarifications whose cited fragments are entirely within this batch.
2. **Shape A output**: the response body is the batch's composed Markdown (modality sections, per-clause citations) **without** the top-level `spaex-composed:source_hash=... build_input_hash=...` header — that header is added once, by the merge step, over the full original fragment set. A batch call never claims to speak for the whole build.

A batch call's Shape B (contradiction/overlap found *within this batch*) is handled by the existing clarification round-trip, scoped to this one batch call, bounded to one round-trip exactly as today (a second Shape B from the same batch call is `invalid-output`).

## Merge call and bounded reduction

For a multi-batch composition, merging starts after every batch has produced a `BatchComposition` (a batch that raised and resolved its own clarification contributes its post-resolution composed body, same as today's single-call flow).

If the serialized merge input fits within the fixed merge-input ceiling from `research.md §3` (a value independent of the batching ceiling in §2, not the same number reused), the reducer performs one N-ary merge call. Otherwise it performs a deterministic pairwise tree reduction: at each level it merges adjacent composed inputs in batch-assignment order, carries an unpaired final input to the next level unchanged, and repeats until one composed input remains. Every pairwise call receives only the two adjacent composed documents plus the applicable clarifications, and every intermediate result preserves all clause citations and the source-fragment membership of its inputs. A pair that cannot fit within the ceiling produces the existing typed pre-LLM `behavior-composer-invalid-output` diagnostic with `reason=input-too-large`; it is not split or silently concatenated.

Each flat or tree merge input is a JSON document structurally analogous to `ComposerInput`, with:
- `batch_compositions`: the ordered list of composed Markdown inputs for that merge node, never raw fragments.
- `clarifications`: only currently-valid clarifications whose cited fragments span the inputs at that node; batch-local answers are already folded into the relevant composition.
- `expected_source_hash` / `expected_build_input_hash`: identical to today's contract — computed over the *entire* original fragment set, unchanged by batching.

**Output**: an intermediate merge returns a headerless, merged, deduplicated, citation-preserving partial document for the next tree level. The root merge returns the identical Shape A/Shape B contract as today's path and adds the `spaex-composed` header over the full-set hashes above. Repeated runs of this deterministic batch/merge pipeline are byte-identical (research.md §6); this contract makes no unsupported byte-for-byte equivalence claim against the legacy single whole-set call.

Any merge node's Shape B (a contradiction spanning its inputs) goes through the same one-round-trip-bounded clarification flow as any other call. Once resolved, that node is re-invoked once with the answer staged, then its resolved output continues up the reduction tree. A second Shape B from the same node is `invalid-output`.

## Runtime consistency

Every batch call and the merge call in one composition attempt use the same resolved CLI runtime (`claude`, `codex`, or `gemini`), chosen once at the start of the attempt via the existing priority-order `shutil.which` resolution. No call in the attempt re-resolves or falls back to a different runtime mid-attempt.

## Failure surface

Unchanged categories (`timeout`, `runtime-error`, `invalid-output`, `quota`, `no-runtime`), unchanged exit codes 30-34. A failure in any single batch call or the merge call aborts the whole attempt the same way a single-call failure does today (FR-004): nothing publishes, the previously published constitution stays byte-unchanged. The diagnostic names which step (`batch-N` or `merge`) failed.

## Diagnostic log

`$SPAEX_COMPOSER_LOG` (default `.spaex/composer.log`) becomes a JSON-lines file: one record per completed invocation, appended as that invocation completes (not buffered until the whole attempt finishes), per data-model.md's `ComposerLogEntry`. The file is truncated exactly once when a fresh attempt starts; clarification re-invocations append a second record for the same logical step and retain the initial questions response. On failure, every invocation that completed before the failure has an entry already on disk; the failing invocation's entry (if it produced any output before failing) is the last one. This is the only change to the failure-log contract; the env var, default path, and "see this file for diagnosis" hint are unchanged.
