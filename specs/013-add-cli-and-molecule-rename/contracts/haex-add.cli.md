# `haex add` — CLI Contract

**Spec**: 013
**Purpose**: adopt one or more molecules from a source repository into `.haex-hive.json` and run `haex install` in the same invocation.

## Synopsis

```
haex add <source-url> [<molecule-id>[,<molecule-id>...]]
         [--revision=<SHA>]
         [--all]
         [--lock-timeout=<sec>]
```

## Arguments

| Argument | Kind | Meaning |
|---|---|---|
| `<source-url>` | required | Publisher repo URL. Canonical `https://` or `ssh://` per Principle II. |
| `<molecule-id>[,<molecule-id>...]` | optional positional | One or more reverse-DNS molecule ids to adopt. Comma-separated on a single positional argument. When omitted, either `--all` or an interactive TTY prompt selects. |
| `--revision=<SHA>` | optional flag | Full 40-hex commit SHA to pin. When omitted, resolves via `git ls-remote <source-url> HEAD`. |
| `--all` | optional flag | Adopt every molecule listed by the publisher manifest at the resolved revision. Mutually exclusive with positional molecule ids. |
| `--lock-timeout=<sec>` | optional flag | Manifest-lock acquisition timeout in seconds. Default: 30. `0` = fail-fast (refuse immediately on contention). See FR-028. |

## Behavior

### Successful adoption

1. Acquire the permanent advisory manifest lock at `.haex-hive.json.lock` (create if absent).
2. Resolve `<source-url>` and `--revision` to a full SHA (`git ls-remote HEAD` when `--revision` was omitted; use the provided SHA verbatim otherwise).
3. Ensure the publisher clone under `$HAEX_HIVE_STATE/repos/<source-digest>/` exists and contains the resolved SHA (initial clone or fetch).
4. Read the publisher-root `manifest.json` at the resolved SHA; validate it against `publisher-manifest.v3.schema.json`.
5. Determine the molecule-id set to add:
   - Positional list, if given.
   - Every id under `manifest.molecules{}` at the resolved SHA, if `--all` given.
   - Interactive selection from a TTY prompt, otherwise. Non-TTY invocation refuses with `interactive-selection-unavailable` and asks for explicit molecule ids or `--all`.
6. Merge or re-pin the compound entry for `<source-url>`:
   - Same source and same revision: merge new molecule ids into the existing `molecules[]` array (deduplicated).
   - Same source, different revision: keep every existing molecule, add the new molecule ids, and re-pin the whole compound to the new revision (deduplicated, sorted) atomically after the new publisher manifest has validated. `track` and `config` are preserved. Every carried-over molecule must exist in the publisher manifest at the new revision; otherwise refuse with `molecule-id-not-in-source` naming it, writing nothing. `haex add` never removes a molecule; only `haex remove` does.
   - No existing compound for this source: append.
7. Write the updated `.haex-hive.json` via `.haex-hive.json.tmp` + rename-in-place.
8. Call `haex install` in-process with the held manifest-lock context. Any diagnostic surfaced by install (missing publisher clone, invalid molecule manifest, delete-orphans conflict, etc.) surfaces here with its own exit code. Note: multi-source constitution merges are refused pre-write in step 6 (`constitution-already-adopted`), so install never sees a review-pending state under Spec 013.
9. On install success: report the resolved SHA, the added molecule ids, any carried-over molecule ids re-pinned from the previous revision (listed separately, as `<old-short-sha> -> <new-short-sha>`), and the participating output roots that changed. Exit 0.
10. Release the manifest lock.

### Refusal keys

| Key | Meaning | Exit code |
|---|---|---|
| `source-url-invalid` | `<source-url>` did not resolve to a git remote (`git ls-remote` failed with a non-transient error). Nothing written. | 2 |
| `revision-not-found` | `--revision=<SHA>` was given, but the remote does not have that SHA. Nothing written. | 2 |
| `publisher-manifest-missing` | The resolved revision has no `manifest.json` at repo root. Nothing written. | 2 |
| `publisher-manifest-invalid` | The publisher `manifest.json` at the resolved revision does not validate against `publisher-manifest.v3.schema.json` (schema violation, or `haex_hive_version` is not `"3"`). Nothing written. | 2 |
| `molecule-id-not-in-source` | A positional molecule-id, or a molecule carried over from an existing compound for the same source at a different revision, is not listed in the publisher manifest at that revision. Nothing written; for a carried-over molecule the operator runs `haex remove <id>` first. | 2 |
| `interactive-selection-unavailable` | No positional ids, no `--all`, and stdin is not a TTY. Nothing written. | 2 |
| `workflow-molecule-already-adopted` | The added molecule set includes a workflow molecule while `.haex-hive.json` already resolves to a different workflow molecule. Names the currently adopted workflow molecule; asks the operator to `haex remove <current-id>` first. Nothing written. | 2 |
| `constitution-already-adopted` | The added molecule set includes a constitution-contributing molecule while `.haex-hive.json` already resolves to another constitution-contributing molecule. Names the currently adopted constitution-contributing molecule; asks the operator to `haex remove <current-id>` first, or to combine the two constitutions into one atom externally. haex-hive does NOT perform multi-source constitution merges (ADR 0010, Spec 014). Nothing written. | 2 |
| `install-transaction-failed` | Underlying `haex install` failed for any reason. Manifest edit is rolled back atomically under the still-held manifest lock; a rollback failure surfaces the recovery path. | matches install |
| `manifest-lock-contended` | The manifest lock at `.haex-hive.json.lock` could not be acquired within the timeout window (default 30 s, operator-overridable via `--lock-timeout=<sec>`, `0` = fail-fast). Nothing written. | 6 |

## Exit codes

- `0`: adoption complete; install succeeded.
- `2`: input validation refused; no state changed.
- `6`: manifest-lock timeout (`manifest-lock-contended`).
- Other: propagated from `haex install` per Spec 008.

Note: exit code `5` is intentionally not used by Spec 013. A prior draft reserved it for a `constitution-review-pending` state that is now retired (see the top-level Refusal Keys row for `constitution-already-adopted`).

## Determinism

- The written `.haex-hive.json` is byte-deterministic for a given (existing content, source, revision, molecule id set): the compound entries preserve their previous order except for the added/updated one, which sorts to the end of `compounds[]` on first append and stays in place on merge/re-pin. Within a compound, `molecules[]` is deduplicated and lexically sorted.
- Concurrent `haex add` invocations serialize via `.haex-hive.json.lock`; the second either waits or refuses (based on the configured lock policy) and never observes a half-written manifest.

## Non-goals

- **`haex update`**: bump pins without changing the molecule set. Deferred.
- **Multi-source constitution merge**: retired by ADR 0010 and Spec 014. Spec 013 refuses pre-write with `constitution-already-adopted`. No `--llm=file` or `--accept-merged` path exists.
- **Central molecule registry**: `<source-url>` remains a direct git URL.
- **Offline mode**: no offline path; a network failure to `git ls-remote`/`git clone` surfaces as `source-url-invalid` or `revision-not-found`.
