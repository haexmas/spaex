# ADR 0028: spaex renders the constitution verbatim; the model only checks

**Status**: Accepted
**Date**: 2026-11-22
**Related**: Spec 030 (verbatim constitution composition); supersedes ADR 0022 (map-reduce Composer), ADR 0023 (parallel batch dispatch), ADR 0024 and ADR 0025 (merge ceiling); Spec 023, Spec 026

## Context

Since spec 023 a language model wrote `.spaex/constitution.md`: it received all fragments and returned one-line clauses. Measured on the haex-vault repo, with the same fragments and two compositions, a fragment of 32 rules became 12 and 10 clauses and a fragment of 15 rules became 11 and 13. Three properties of the design cause this:

1. The prompt asks for "one bullet per merged clause" and sets no rule for how much of a fragment must survive.
2. The completeness check only demands that every fragment is cited at least once, so a fragment that lost most of its rules still passes.
3. The prompt states that the temperature is zero, which the CLI runtimes do not offer, so the wording differs on every install and every install produces a noise diff.

Spec 026 made the call reliable at scale (batches, merge, ceilings) but kept the model as the author of the text.

## Decision

spaex writes the text. `.spaex/constitution.md` (format version 2) holds every fragment body byte for byte in scoped-id order. The model runs one check that returns findings (contradictions or duplicates, as fragment and line range) or nothing, and can never change text. spaex verifies the named passages and asks the operator about every finding. The answer is a persisted decision, bound to the exact passage text, and is applied by commenting out the passage that is not kept; the commented text stays unchanged. The output is a pure function of fragments and decisions.

## Consequences

- Rules reach the agent as their authors wrote them; nothing is condensed, and the completeness check compares text, not citations.
- Reproducible output, no model call for unchanged input, a deleted file regenerates identical.
- The file is longer (haex-vault: about 930 lines instead of about 185); the operator accepted this.
- Sources need not change for each consumer: a conflict or duplicate between authors is resolved in the consumer repo by an exclusion, which the consumer can review in git.
- The map-reduce composer, merge ceilings, clause grammar, free-text clarifications and the `.spaex/.stale` marker are removed. `trace`, `status` and `build --check` change; the format and the `status` JSON are a breaking change for every consumer, released as a new major version.
- A language model can miss a finding; each changed fragment set is checked again in full, and decisions already made are kept.

## Alternatives considered

- Keep the composer and add a clause-level completeness check: the model still owns the wording, the check is fuzzy, output stays nondeterministic.
- Verbatim text with free-text resolutions appended: the agent would read both the contradiction and a note about it; the operator asked for a coherent constitution.
- Exclude whole fragments: too coarse, drops unrelated rules.
