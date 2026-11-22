# Research: Verbatim Constitution Composition

Each entry gives the decision, why, and what was rejected. Numbers are referenced from [plan.md](./plan.md).

## R1 — Document layout (format version 2)

**Decision**: Header line `<!-- spaex-composed:source_hash="…" build_input_hash="…" version="2" -->`, the title and two italic notice lines, an optional preamble (spec 029), then one block per fragment in scoped-id order:

```text
<!-- spaex-fragment id="<molecule>/<fragment>" modality="MUST" -->   (modality only if declared)
<body: CRLF and CR to LF, nothing else changed>
<!-- /spaex-fragment -->
```

One blank line separates blocks. No modality sections.

**Why**: Bodies are free prose with mixed modalities, so they cannot be split into clauses without rewriting. `<!-- spaex-` is the comment form spec 023 already rejects inside fragment bodies, so a boundary can never occur in a body and `render.parse` is unambiguous.

**Rejected**: Demoting body headings (changes text). A heading per fragment instead of a comment (collides with body headings). A JSON sidecar (agents read the Markdown file only).

## R2 — Verification by parsing back

**Decision**: `render.verify(fragments, decisions, text)` parses the document, removes the exclusion comments' wrapping, and compares each reconstructed body with the fragment body after CRLF and CR have been canonicalized to LF (nothing else: trailing whitespace and trailing newlines are compared as they are). It also checks that every exclusion corresponds to a decision and that no other text differs.

**Why**: FR-014 asks for a check that cannot be satisfied by a citation-like note. Verifying against the source, not against the renderer's own output, catches a renderer bug.

**Rejected**: Re-rendering and comparing (proves determinism, not fidelity). Keeping the citation regex (it is what let rules disappear).

## R3 — Passages

**Decision**: A passage is `(scoped_id, start_line, end_line)`, 1-based inclusive lines of the fragment body as spaex normalizes it for hashing. spaex rejects a named passage when the fragment is unknown, the range lies outside the body, the range is empty or blank, it spans two fragments, or it cuts through a fenced code block. A finding needs at least two passages of different fragments.

**Why**: Line ranges are checkable mechanically; a quoted sentence would need fuzzy matching. Fences are the one structure where a comment would break the Markdown.

**Rejected**: Sentence quotes (not verifiable). Whole-fragment findings (too coarse, see Complexity Tracking).

## R4 — The check call

**Decision**: A new prompt `CHECK_PROMPT` (prompt version `3`). Input: fragments with every body line prefixed by its number. Output envelope: `{"type":"no_findings"}` or `{"type":"findings","findings":[{"kind":"contradiction"|"duplicate","summary":"…","passages":[{"fragment":"m/f","start":N,"end":M},…]}]}`. spaex parses with the existing sentinel envelope, validates passages (R3), and treats an unusable answer as an unusable compose answer today: `invalid-output`, exit 32.

**Why**: Output is small, so the length-driven failures of spec 026 do not apply, and the model has no way to write constitution text.

**Rejected**: Asking the model to return the text with comments inserted (it would again own the text).

## R5 — When the model runs

**Decision**: `decisions.json` records `checked: {source_hash, prompt_hash}` after a completed check. The header of the composed file carries no prompt or check data (FR-003). Install calls the model only when the current fragments' `source_hash` or the check prompt hash differs from `checked`. A finding is skipped when a valid decision exists for the same set of passage texts.

**Why**: SC-002 and SC-006: a deleted composed file regenerates without a model call because the checked state lives in `decisions.json`, not in the composed file's header.

**Rejected**: Reading the checked state from the composed file header (lost when the file is deleted).

## R6 — Large fragment sets

**Decision**: If the serialized payload fits the existing size limit (`composer/batching.py`), one call. Otherwise split by molecule into batches and run the check for every batch and every pair of batches, with the existing parallel dispatch.

**Why**: Cross-batch findings are the case spec 026's merge step existed for; running pairs covers them without a merge step. A set stays one call when its compact serialized UTF-8 payload is at most 150,000 bytes.

**Rejected**: Dropping the limit (risks model context). A merge step over partial findings (needs the text again anyway).

## R7 — Operator interaction

**Decision**: One finding at a time: print kind and summary, then every passage with fragment id, lines and text, and numbered options "keep 1 (exclude the others)", "keep 2 …", "keep all". Blank answer or end of input declines and aborts (exit 21 as today); a non-interactive terminal aborts the same way. Tests inject a decision callback.

**Rejected**: Free-text answers (spec 023 clarifications): not machine-applicable.

## R8 — Decisions file

**Decision**: `.spaex/decisions.json` (`.spaex/local/decisions.json` for spec 029): schema in [contracts/decisions-schema.md](./contracts/decisions-schema.md). A decision stores each passage's scoped id and sha256 of its text, plus the text itself, the choice, and timestamps. It is valid while every passage text still occurs exactly once in its fragment; ranges are recomputed from the text on every run.

**Why**: Reproducibility (FR-004, FR-010) and no re-asking after unrelated edits.

**Rejected**: Reusing `clarifications.json` (fragment-hash keys; answers are free text about merged clauses).

## R9 — Check unavailable

**Decision**: No runtime, timeout, quota or unusable output after retries fails the install with the existing failure categories and leaves all tracked files unchanged. There is no unchecked write.

**Why**: Operator decision (spec clarifications); a coherent constitution cannot be guaranteed otherwise.

## R10 — Format version and migration

**Decision**: `version="2"`. A file with another version, or without a v2 header, is out of date. First v2 install asks the findings anew, removes `clarifications.json` and `.stale` in the same transaction, and rewrites the file.

**Rejected**: Converting v1 answers (they describe rewritten clauses, no passage to bind to).

## R11 — `trace`

**Decision**: Parse fragment blocks and exclusion comments from the file (no clause grammar). `trace <molecule>/<fragment>` prints molecule pin, atom source and the line range in the file; a phrase matches lines inside blocks and names fragment, line, and whether the line lies in an exclusion (with the kept passage).

## R12 — `status`

**Decision**: `ConstitutionSummary` gains `fragment_count`, `fragments_by_molecule`, `decision_count`, `excluded_passage_count` and loses `clause_counts`. The JSON output keys change accordingly (breaking, covered by the major version). The `constitution_stale` drift finding now means: file missing, version not 2, text differs from a fresh render, or `checked` does not match the current fragments.

## R13 — Local scope (spec 029)

**Decision**: The local pass calls the same orchestration with `spaex_dir=.spaex/local/`; it has its own `decisions.json`. Findings are checked among the local fragments only, as local composition is today, and never change the project document.

## R14 — Retired pieces and release

**Decision**: Remove `composer/reduce.py`, `composer/clarify.py`, `composer/clarifications.py`, `composer/completeness.py`, `clauses.py`, `stale.py`, `MERGE_PROMPT`, the compose prompt, and the `abort_on_contradiction=False` plausibility mode of `add`/`remove` (they now ask like install). New ADR 0028 supersedes ADRs 0022–0025. The code PR carries a `feat!:` commit so release-please proposes the next major version; consumers (atoms, haex-vault) rebuild their constitution afterwards.

## R15 — Bootstrap block

**Decision**: The block's wording stays, with one added sentence: text in a comment marked `spaex-excluded` is not an instruction. Its marker version in `bootstrap.py` is bumped so `spaex install --global --check` reports the update.
