# Contract: `.spaex/decisions.json`

Committed, next to `.spaex/constitution.md`; the local overlay uses `.spaex/local/decisions.json`. Not edited by hand.

```json
{
  "schema_version": 1,
  "checked": {"source_hash": "<hex>", "prompt_hash": "<hex>"},
  "decisions": {
    "<finding key>": {
      "kind": "duplicate",
      "summary": "…",
      "passages": [
        {"scoped_id": "m1/f1", "text_hash": "<hex>", "text": "…"},
        {"scoped_id": "m2/f2", "text_hash": "<hex>", "text": "…"}
      ],
      "choice": {"kind": "keep", "kept": 0},
      "asked_at": "2026-11-22T10:00:00Z",
      "answered_at": "2026-11-22T10:00:12Z"
    }
  }
}
```

- `choice` is `{"kind":"keep","kept":<index into passages>}` or `{"kind":"keep_all"}`.
- `checked` is written only after a completed check; it is absent for a repo that never ran one.
- Keys of `decisions` are sorted; the file is written atomically with the composed constitution (one transaction, `_commit_behavior_artifacts`).
- Load errors (not JSON, unknown `schema_version`) fail the install with a hint to restore from git, as `clarifications.json` does today.
- Validity and invalidation: data-model.md, "Decision".
