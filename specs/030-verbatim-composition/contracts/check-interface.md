# Contract: the contradiction and duplicate check

Replaces [023 `composer-interface.md`](../../023-behavior-harness/contracts/composer-interface.md) and the 026 batch/merge interface.

## Input (JSON, to the runtime on stdin together with `CHECK_PROMPT`)

```json
{
  "spaex_version": "<version>",
  "check_prompt_version": "3",
  "fragments": [
    {
      "id": "<molecule-id>/<fragment-id>",
      "modality": "MUST",
      "body": "1: first line\n2: second line"
    }
  ]
}
```

Fragments are sorted by scoped id; `body` is the LF-canonicalized body, one line per fragment line prefixed `<n>: ` with `n` counting from 1. A set is sent in one call when its compact JSON payload, encoded as UTF-8, is at most 150,000 bytes; larger sets are split into calls that stay within that limit. Keys are sorted, with `ensure_ascii=False` and compact JSON separators.

## Output

The existing sentinel envelope `<<<SPAEX-COMPOSER-BEGIN>>> {json} <<<SPAEX-COMPOSER-END>>>`, nothing after it.

```json
{"type": "no_findings"}
```

```json
{
  "type": "findings",
  "findings": [
    {
      "kind": "contradiction",
      "summary": "One sentence saying why the passages cannot both be followed.",
      "passages": [
        {"fragment": "m1/f1", "start": 12, "end": 14},
        {"fragment": "m2/f2", "start": 3,  "end": 3}
      ]
    }
  ]
}
```

## Rules the prompt states

1. Report a contradiction when two passages cannot both be followed, and a duplicate when two passages give the same instruction in the same or other words.
2. Passages come from different fragments; cite the smallest line range that contains the whole instruction, not a heading, and never cut a fenced code block.
3. Report each pair of conflicting or repeated instructions once; do not report a fragment against itself.
4. Never write, reword or propose constitution text; the response contains the envelope only.

## What spaex does with the answer

- Parses and validates every passage (data-model.md); a finding with an invalid passage or fewer than two valid passages makes the answer unusable.
- Unusable answers fail with `invalid-output` (exit 32), as an unusable compose answer does today; runtime failures keep their categories (31, 33, 34, 35). There is no retry in the invocation layer, so none is added here.
- Findings whose key has a valid decision are dropped; the rest go to the operator one at a time.

## Large sets

Payloads above the size limit are partitioned into fragment batches so each batch and each pair of batches stays within the byte limit; the check runs for every batch and every pair (dispatched in parallel as in ADR 0023). A fragment is never split across calls. Findings are merged by key.
