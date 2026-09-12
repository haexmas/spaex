# Contract: `.spaex/clarifications.json` Schema

Storage for operator answers to Composer clarification questions. Version-controlled; committed alongside `.spaex/manifest.json` and `.spaex/constitution.d/`.

## File location

`<repo-root>/.spaex/clarifications.json`

Created on first Composer clarification. Absent when no clarifications have ever been recorded.

## Schema (version 1)

```json
{
  "schema_version": 1,
  "clarifications": {
    "<key-hex>": {
      "question": "<human-readable question>",
      "cited_fragments": [
        {
          "molecule_id": "<molecule-id>",
          "fragment_id": "<fragment-id>",
          "body_sha256": "<hex>"
        }
      ],
      "answer": "<operator answer text>",
      "asked_at": "<ISO-8601>",
      "answered_at": "<ISO-8601>"
    }
  }
}
```

Top-level structure:
- `schema_version`: integer, currently `1`. Rejection on unknown version.
- `clarifications`: object keyed by clarification hex key (see key derivation below).

Each entry:
- `question`: the Composer's original question, verbatim. Human-readable, used in `spaex constitution build --check` diff outputs.
- `cited_fragments`: array of the fragments the question referred to. Order is stable (sorted lexicographically by `molecule_id` then `fragment_id`).
- `answer`: operator response, free-form text.
- `asked_at`, `answered_at`: ISO-8601 timestamps (UTC). For provenance only; not used in key derivation.

## Key derivation (per research.md §7)

Input to SHA256:
1. Sort `cited_fragments` by `<molecule-id>/<fragment-id>` lexicographically.
2. For each entry, emit line: `<molecule-id>/<fragment-id>|<body_sha256>`.
3. Concatenate all lines with LF separators, no trailing LF.
4. Compute SHA256 over the UTF-8 encoding of the concatenation.
5. Format as lowercase hex, 64 characters.

The `body_sha256` for each fragment is computed via:
1. Read fragment body as UTF-8 text.
2. Normalize: strip trailing whitespace on each line, convert CRLF to LF, collapse multiple trailing newlines to one.
3. Compute SHA256, format lowercase hex.

## Loading

- Missing file: treated as empty `clarifications: {}`.
- Parse error: install aborts with a diagnostic pointing at the offending line and suggesting the operator restore from git.
- Unknown `schema_version`: install aborts.

## Writing

Atomic write pattern:
1. Read existing file into memory (or start from empty object).
2. Stage new answers and invalidation changes in memory while the Composer runs.
3. Publish the staged set only after Shape A has passed parsing and both local hash checks.
4. Apply changes (add new entries, remove invalidated entries) to the published snapshot.
5. Write to `.spaex/clarifications.json.tmp`.
6. Rename over `.spaex/clarifications.json`.

If composition aborts, discard the staged set and leave the existing file
byte-for-byte unchanged.

## Invalidation semantics

On Composer invocation:
1. For each stored clarification entry, recompute `key-hex` from its `cited_fragments` (using current on-disk fragment bodies to derive `body_sha256`).
2. If recomputed key does not match stored key, or any cited fragment is missing: mark entry as invalidated.
3. Composer proceeds with valid entries applied to its input context.
4. Any clarification question the Composer produces that matches an invalidated entry's semantic scope becomes a fresh entry (new key, new question text, prompts operator).

## Manual editing

Operators MAY edit `answer` fields by hand to update their guidance. Doing so
does NOT invalidate the fragment key, but it changes `build_input_hash`, so the
answer takes effect on the next Composer run without triggering a re-ask.

Operators MUST NOT edit `key-hex`, `cited_fragments`, or `body_sha256` fields; those are consistency invariants. Corrupted values cause invalidation on the next Composer run.

## Schema evolution

The v4 schema is clean-cut: schema changes require an explicit project-owned update to the manifest and its tests; spaex does not rewrite or migrate older layouts in place.
