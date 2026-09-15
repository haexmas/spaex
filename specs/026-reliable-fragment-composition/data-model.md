# Data Model: Reliable Fragment Composition

All entities below are process-internal to one `spaex install` composition attempt unless marked "persisted." No new persisted schema is introduced; the two new persisted-adjacent artifacts (the log format in §5 and the merge contract in `contracts/`) extend existing paths rather than adding new files.

## Fragment *(existing, unchanged)*

A single behavior directive contributed by one molecule. Fields (`molecule_id`, `fragment_id`, `atom_source`, `modality`, `tags`, `body`, `body_sha256`) are unchanged from Spec 023. This feature only changes how fragments are grouped for composition, never their own shape.

## Batch *(new, process-internal)*

An ordered, deterministic grouping of fragments assigned to one composer call.

| Field | Type | Notes |
|---|---|---|
| `batch_id` | `str` | Deterministic, e.g. `"batch-1"`, `"batch-2"`, assigned in the same sorted order as the fragments (never depends on wall-clock or randomness — required for FR-003). |
| `fragments` | `tuple[Fragment, ...]` | A contiguous slice of the canonically-sorted fragment list. All of a given molecule's fragments always land in the same batch (a molecule's fragments are never split across batches). |
| `clarifications` | `tuple[Clarification, ...]` | The subset of the build's currently-valid clarifications whose cited fragments all fall inside this batch — a clarification about fragments spanning two batches is not meaningful at batch level and is only relevant to the merge step (see MergeInput). |

**Validation rules**: Every fragment in the canonical fragment set appears in exactly one batch. Batch assignment, given the same fragment set, is byte-identical across runs (pure function of sorted fragment list + fixed size ceiling from research.md §2).

## BatchComposition *(new, process-internal)*

The result of composing one `Batch` — either it produced a composed partial document, or it raised a clarification that was resolved before this batch's composition could proceed.

| Field | Type | Notes |
|---|---|---|
| `batch_id` | `str` | Matches the source `Batch`. |
| `body` | `str` | The composed Markdown for this batch's fragments only (same per-clause citation format as today's final document, minus the top-level `spaex-composed` header — that header belongs only to the final merged document). |
| `runtime` | `RuntimeDescriptor` | *(existing type, reused)* Which CLI runtime answered — must be identical across every `BatchComposition` and the eventual merge in one build (FR-011). |

## MergeInput *(new, process-internal)*

The input to the merge step: every batch's composed output, assembled once all batches have completed.

| Field | Type | Notes |
|---|---|---|
| `batch_compositions` | `tuple[BatchComposition, ...]` | Ordered by `batch_id` for determinism. |
| `cross_batch_clarifications` | `tuple[Clarification, ...]` | Currently-valid clarifications whose cited fragments span more than one batch — not resolvable at batch level, carried forward to the merge call. |
| `expected_source_hash` / `expected_build_input_hash` | `str` | *(existing fields, reused)* Computed once over the *entire* original fragment set exactly as today — the merge step's output carries the same header contract as a single-call composition, so downstream verification (`emit.py`'s hash check, FR-012b's completeness check) needs no changes. |

## ComposerLogEntry *(new, persisted at `$SPAEX_COMPOSER_LOG`)*

One JSON-lines record per internal step, appended immediately as that step completes (see research.md §5).

| Field | Type | Notes |
|---|---|---|
| `step` | `str` | `"batch-1"`, `"batch-2"`, ..., or `"merge"`. |
| `raw_output` | `str` | The step's raw LLM response, exactly as `invoke.py` receives it today (unchanged capture point). |
| `outcome` | `str` | `"composed"`, `"questions"`, or the failure category name if this step is the one that ultimately aborted the build. |

**Validation rules**: Entries are append-only within one build attempt; a fresh `spaex install` invocation starts a fresh log (existing `_write_composer_log` truncate-on-open behavior, applied per entry instead of once).

## Composed Constitution *(existing, unchanged shape)*

The final published `.spaex/constitution.md`. Unchanged: same header (`spaex-composed:source_hash=... build_input_hash=... version="1"`), same modality section ordering, same per-clause provenance citation format. This feature changes how the document is produced, never its shape or the checks (`emit.py`, `_verify_completeness`) that validate it.

## Clarification *(existing, unchanged)*

Unchanged fields and persistence (`ClarificationsStore`, keyed by cited-fragment body hashes). This feature changes *which step* (a specific batch, or the merge) a clarification question originates from, never how a clarification is recorded, invalidated, or excused from the completeness check.
