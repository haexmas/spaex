# Contract: CLI surface changes (delta to 023 `cli-surface.md`)

## `spaex install`

- Never writes a constitution that was not checked (check state in `decisions.json` matches the fragments), and never writes while a finding is undecided.
- Exit codes unchanged: 21 for a finding that cannot be answered (non-interactive or declined), 31–35 for runtime failures, 32 for unusable check output.
- Writes `.spaex/decisions.json` and removes `.spaex/clarifications.json` and `.spaex/.stale` in the same transaction.
- Interactive prompt: see research R7.

## `spaex add` / `spaex remove`

The `abort_on_contradiction=False` plausibility mode and `.spaex/.stale` are gone. The install they trigger asks about findings exactly like `spaex install`.

## `spaex constitution build`

- `--check`: exit 0 only if the file equals a fresh render of the fragments and valid decisions **and** `checked` matches the current fragments; never calls the model. Reports "out of date", "version 1", or "not checked" otherwise.
- `--force`: reruns the check even when `checked` matches.
- Output lines: `composed .spaex/constitution.md (N fragment(s), D decision(s))` or `reused …`.

## `spaex constitution trace <query>`

Query is `<molecule>/<fragment>`, a molecule id, or a phrase. Output per match: scoped id, atom source, molecule pin, line range in the composed file, and `excluded (kept <ref>)` where the line lies in an exclusion. JSON output has the same fields. A bare fragment id that exists in several molecules is rejected as ambiguous, as today.

## `spaex status`

The constitution summary reports `fragment_count`, `fragments_by_molecule`, `decision_count`, `excluded_passage_count`. `clause_counts` is removed (breaking for the JSON output).

## `spaex install --global`

The bootstrap block text gains one sentence (research R15); its version marker changes.
