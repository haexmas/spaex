# Research: Reliable Fragment Composition

## §1. Composition strategy

**Decision**: Map-reduce composition. Partition the resolved, canonically-sorted fragment list into fixed-size batches; compose each batch independently with the *existing, unmodified* single-call Composer machinery (`invoke.py`'s `_call_cli`/`_parse`, same sentinel/Shape A/Shape B contract); then run one additional **merge** call whose input is the batches' composed bodies (not raw fragments) and whose job is to combine them into one final document while re-checking for contradictions that span batch boundaries. The merge call reuses the same sentinel-wrapped Shape A/Shape B response contract, so it can surface a cross-batch contradiction as a normal Shape B clarification question through the existing round-trip.

**Rationale**:
- Keeps every individual LLM call's input bounded by batch size, not by total adopted molecule count. Batch size is fixed at design time; growing the fragment set adds more batches, not larger ones. This directly satisfies FR-001/FR-007 (no fixed ceiling on scale) without any single call's input growing without bound.
- The merge call's input (already-composed, citation-bearing bullet lists) is far smaller and more compact than the raw fragment set it summarizes, so even the merge step scales sub-linearly with total fragment count. At today's confirmed scale (9 molecules), a plausible batch size (see §2) yields 2-3 batches and a merge input of a few KB, not 60KB.
- Reuses `invoke.py`'s `_call_cli`/`_parse` machinery for every batch call and the merge call: the sentinel format and five typed failure categories (`failure.py`) remain unchanged; only the per-invocation log lifecycle is extended. This satisfies FR-009 (no new silent-degradation surface) almost for free, since the existing machinery's guarantees carry over unchanged to every step.
- Cross-batch contradiction detection is preserved by construction: the merge step's input is the union of every batch's composed clauses (with full provenance), so a contradiction between a fragment in batch 1 and a fragment in batch 3 is visible to the merge call exactly as it would be to a single whole-set call today. This satisfies FR-005 without any special-casing.

**Alternatives considered**:
- **Sequential/incremental accumulation** (fold molecules in one at a time, each step re-composing "everything so far + one more molecule"): rejected. The *last* step's input still grows linearly with total molecule count — the same failure mode we are escaping, just deferred to the final fold instead of eliminated. Map-reduce's batch calls stay bounded regardless of position; only the merge input grows, and it grows far more slowly (composed text, not raw fragments).
- **One LLM call per molecule, no merge, client-side concatenation**: rejected outright — this is exactly the "silent degradation to raw fragment concatenation" FR-012a already forbids project-wide. Cross-molecule contradiction detection (FR-005) would be lost entirely, since no LLM call would ever see two different molecules' fragments together.
- **Increase timeout further / reduce fragment set as the standing answer**: rejected as a durable fix — it's what this feature exists to move past (per Assumptions in spec.md: no fixed ceiling, per operator direction). Still valid as an interim mitigation, already available today via `SPAEX_COMPOSER_TIMEOUT`.

## §2. Batch sizing

**Decision**: Batch by a fixed **fragment-count ceiling with a byte-size fallback**, not by molecule count. Sort canonical fragments by scoped key (already the existing sort for determinism), then greedily fill batches up to a fixed fragment-count limit *or* a fixed serialized-size limit, whichever is reached first, never splitting a single molecule's fragments across two batches (a molecule's own fragments must be composed together so within-molecule semantics stay intact for the batch call).

If one molecule's complete fragment group is itself larger than the serialized-size ceiling, the no-splitting rule makes it impossible to form a valid bounded batch. Partitioning therefore stops before any LLM call and returns the existing typed `behavior-composer-invalid-output` diagnostic with `reason=input-too-large`, the molecule's scoped identifier, the measured serialized size, and the configured ceiling. No `Batch` is emitted for that molecule, and no raw fragment fallback is permitted.

**Rationale**: A pure molecule-count-based batch size (e.g., "3 molecules per batch") breaks down if one molecule contributes far more fragment content than another (some molecules in this project ship a single short rule; others, like `graphify-first-authoring`, ship several thousand words). Bounding by serialized size (with a fragment-count ceiling as a cheap first-pass guard) keeps every batch call's actual LLM input bounded regardless of *which* molecules land in it, directly targeting the thing that was actually failing (input/output size vs. a single call's reliable capacity), not a proxy for it. The explicit oversized-molecule failure makes the unavoidable no-splitting boundary deterministic and diagnosable.

**Alternatives considered**:
- **Fixed molecule count per batch**: rejected as the sole rule — doesn't bound actual call size, which is the real constraint; kept as a coarse first-pass filter alongside the byte ceiling for simplicity.
- **Dynamic sizing based on live timing feedback (start small, grow until a call is slow)**: rejected for v1 — adds nondeterminism (batch boundaries would depend on runtime timing, breaking FR-003's byte-reproducibility unless batch assignment is fully separated from any timing signal). A fixed, deterministic ceiling is simpler and already resolves the failure mode; adaptive sizing is a future optimization, not required by this spec's success criteria.

## §3. Merge step design and hierarchical scaling

**Decision**: A single flat merge step for the common case (the number of batches at realistic near-term scale, roughly up to a few dozen). Design the merge step as a **binary-tree-capable reduce** from the start (merge takes exactly two composed inputs and produces one, so the same operation can be chained pairwise), but the initial implementation invokes it as one N-ary merge over all batches when N is small, and only falls back to pairwise tree reduction if the merge input itself would exceed the same byte-size ceiling used for batching (§2). This keeps the reduce step itself bounded no matter how large the batch count grows, satisfying FR-001/FR-007's "no fixed ceiling" without over-building for a scale this project does not have evidence of yet.

**Rationale**: A contradiction between two fragments in *any* two batches is still caught as long as the top-level (root) reduce step sees the union of every batch's clauses with full provenance — which holds for both the flat N-ary merge and a pairwise tree, since a tree's root is, by construction, the union of every leaf. The pairwise reducer is specified and tested as part of the initial implementation, so exceeding the flat-merge threshold does not create an unimplemented scale cliff.

**Alternatives considered**:
- **Always build the full recursive tree, even for 2-3 batches**: rejected as unnecessary complexity for the common case (adds an extra LLM call for no benefit when a flat merge already fits comfortably within limits).
- **No hierarchical fallback at all (flat merge only, forever)**: rejected — it would silently reintroduce exactly the same failure mode this feature fixes, just moved to "the merge step" once batch counts themselves grow large enough. Given FR-001/FR-007 explicitly reject a fixed ceiling, the merge step needs the same scaling discipline as the batch step, even if the recursive path isn't exercised at today's scale.

## §4. Runtime consistency (FR-011)

**Decision**: Resolve the CLI runtime (`claude`/`codex`/`gemini`, in the existing fixed priority order via `shutil.which`) exactly once per `spaex install` composition attempt, before dispatching any batch call, and thread that single resolved runtime through every batch call and the merge call.

**Rationale**: Directly implements the resolved clarification (one runtime per run). Reuses `invoke.py`'s existing runtime-resolution logic (`invoke_composer`'s `for name in cli_runtimes: if shutil.which(name) is not None`) unchanged — only the call site changes, from "resolve once, call once" to "resolve once, call once per batch plus once for merge."

**Alternatives considered**:
- **Re-resolve per call**: rejected per the clarification — risks a different runtime answering different batches (e.g. if `claude` becomes unavailable mid-run), which could produce inconsistent phrasing between batches and put SC-003 (byte-reproducibility) at risk in a way that is hard to detect after the fact.

## §5. Per-step diagnostic log preservation (FR-008)

**Decision**: Replace the single `.spaex/composer.log` file with a small JSON-lines log: one line per internal invocation (`{"step": "batch-1", "invocation": 1, "phase": "initial", "raw_output": "...", "outcome": "questions"}` style records), written incrementally as each invocation completes, at the same path (`$SPAEX_COMPOSER_LOG`, default `.spaex/composer.log`) so existing tooling/documentation pointing operators at that path keeps working. At the start of each fresh attempt the file is truncated exactly once; all later records append and flush. On any failure, every already-completed invocation's record is already on disk (written as it completed, not buffered until the end), so the existing `_GenerationRollback`-survives-the-log fix (already shipped) continues to apply per record rather than to one blob.

**Rationale**: Directly implements the resolved clarification (preserve every completed step, not just the failing one). JSON-lines keeps the format append-friendly (a step's record is written and flushed immediately, so a later step's failure — including a hang that never returns — can't erase evidence of earlier steps, whereas holding everything in memory until a single final write would lose that evidence exactly the way the original bug did). Keeping the same env var and default path means the existing failure hint ("see $SPAEX_COMPOSER_LOG") and the just-shipped rollback-preservation fix both keep working without their own changes.

**Alternatives considered**:
- **One file per step** (`composer.batch-1.log`, `composer.merge.log`, ...): rejected — more moving parts (directory creation, cleanup, an unbounded number of files for an unbounded number of batches) for no benefit over one append-only file an operator can just read top to bottom.
- **Keep a single plain-text log, append step boundaries as markers**: rejected — loses structure (no clean way to programmatically tell which step a given chunk of raw output belongs to, complicating any future tooling that wants to inspect one step's output specifically).

## §6. Byte-reproducibility under multi-step composition (FR-003, SC-003)

**Decision**: Determinism holds by construction as long as every step in the pipeline is itself deterministic given the same overall input: (a) fragment→batch assignment is a pure function of the canonically-sorted fragment list and the fixed size ceiling (§2) — no randomness, no wall-clock dependency; (b) the runtime is resolved once and fixed for the whole run (§4); (c) flat merge versus pairwise-tree selection is a pure function of serialized input size; (d) pairwise reduction always consumes adjacent inputs in assignment order; and (e) every batch/merge call uses the existing temperature-0 determinism aids already documented in `composer-interface.md`. No new source of nondeterminism is introduced.

**Rationale**: The existing reproducibility guarantee is preserved without new machinery — this is a property of the design (§1-§4), not a separate mechanism to build. The existing outer reproducibility skip (`source_hash`/`build_input_hash` match → don't invoke the Composer at all) is unaffected, since it operates before the multi-step pipeline is ever entered.

**Alternatives considered**: None — this section documents why the chosen design (§1-§4) already satisfies FR-003 rather than proposing a new mechanism.
