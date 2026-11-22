# Data Model: Verbatim Constitution Composition

## Fragment (unchanged, spec 023)

`scoped_id`, optional `modality`, `body` (normalized for hashing), `body_hash`.

## Passage

| Field | Meaning |
| --- | --- |
| `scoped_id` | Fragment the lines belong to |
| `start`, `end` | 1-based inclusive line range of the fragment body (derived from `text`, never persisted as identity) |
| `text` | The lines joined with LF, no trailing newline |
| `text_hash` | sha256 hex of `text` |

Validation (R3): fragment exists, `1 ≤ start ≤ end ≤ len(lines)`, `text` not blank, range does not split a fenced code block.

## Finding (from the check, in memory only)

| Field | Meaning |
| --- | --- |
| `kind` | `contradiction` or `duplicate` |
| `summary` | The model's one-sentence reason, shown to the operator |
| `passages` | Two or more passages of different fragments |
| `key` | sha256 over the sorted `(scoped_id, text_hash)` pairs |

## Decision (persisted)

| Field | Meaning |
| --- | --- |
| `key` | Same as the finding's key |
| `kind`, `summary` | As reported when asked |
| `passages` | `scoped_id`, `text_hash`, `text` per passage |
| `choice` | `keep` with `kept` = index of the passage kept (the others are excluded), or `keep_all` |
| `asked_at`, `answered_at` | UTC timestamps |

Valid while every passage's `text` occurs exactly once, line-aligned, in the current body of its fragment. Otherwise it is dropped (and the finding is asked again if the check still reports it).

## Check state

`checked: { source_hash, prompt_hash }` in `decisions.json`: the fragment fingerprint and effective check prompt at the last completed check. Equal to the current values means no model call.

## Composed document (version 2)

Header (`source_hash`, `build_input_hash`, `version="2"`), title, notices, preamble, fragment blocks in scoped-id order, exclusion comments inside blocks. Layout in [contracts/spaex-md-format-v2.md](./contracts/spaex-md-format-v2.md). `build_input_hash` covers the check prompt version, its hash and the valid decisions, so any change of decisions changes the header.

## State transitions

```text
fragments or prompt changed ──► check ──► findings? ── no ──► record checked ──► render ──► verify ──► publish
                                   │ yes
                                   ▼
                      ask operator per finding ──► decisions saved with the publish (same transaction)
unchanged ───────────────────────────────────────────────────────► render ──► verify ──► publish (byte-identical)
```

Any failure before publish leaves `.spaex/` byte-unchanged (FR-019).
