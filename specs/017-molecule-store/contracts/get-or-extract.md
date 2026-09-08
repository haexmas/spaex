# Contract: `get_or_extract`

**Module**: `spaex.git.molecule_store` (per research.md's module-placement decision)

## Signature

```python
def get_or_extract(
    repo_dir: Path,
    revision: str,
    molecule_path: str,
    state_root: Path,
) -> Path:
    ...
```

## Preconditions

- `repo_dir` MUST be an existing directory containing a valid git repository (bare or non-bare — both work identically with `git archive`) that already has `revision` fetched locally. Callers are responsible for having called `publisher_fetch.ensure_object()` (or equivalent) first; `get_or_extract` does NOT fetch or clone anything itself.
- `revision` MUST be a canonical, full 40-character lowercase hex SHA. Callers MUST have already resolved any short or symbolic form via `git_revparse.full_sha(repo_dir, ...)` before calling this function. `get_or_extract` MAY validate the shape (regex match) and raise a caller-contract violation (a plain `ValueError`, not one of the `HaexError` subclasses — this is a programming error, not a runtime/environment condition) if given a non-canonical-looking string, but it MUST NOT attempt to resolve a short/symbolic revision itself.
- `molecule_path` MUST be a safe, relative POSIX path with no `..` segments, no leading `/`, and no control characters — the same shape already enforced by `RepoRelativePath` elsewhere in the codebase. `get_or_extract` MUST validate this itself (FR-014) and raise an appropriate typed error if violated, since the path may originate from data this function's callers have not all independently re-validated.
- `state_root` MUST be a writable directory (typically the caller's `SPAEX_STATE` resolution) under which the `molecule-store/` cache tree lives.

## Postconditions (success)

- Returns a `Path` to an existing directory that directly contains the requested `molecule_path` subtree's top-level entries (FR-002) — never nested one level deeper.
- Every file inside has passed the path-containment validation in `tar-member-validation.md`.
- The directory's content is byte-identical to the committed content at `(repo_dir's remote, revision, molecule_path)` (FR-003).
- A subsequent call with the identical `(repo_dir, revision, molecule_path)` returns a `Path` to the same directory without performing any extraction work (FR-005) — verifiable via a no-additional-subprocess-call assertion in tests.

## Postconditions (failure)

| Condition | Raises |
|---|---|
| `git archive <revision> -- <molecule_path>` exits with a nonzero code whose stderr indicates "did not match any files" (verified empirically: exit 128 for a nonexistent pathspec) | A distinct "not found" signal — the exact exception TYPE is this function's own to choose (e.g. a new `MoleculeTreePathNotFoundError`, or reuse of an existing not-found-shaped error if one fits without overloading its meaning; `/speckit-tasks`/implementation decides the concrete class name, but it MUST be distinguishable by type or attribute from `MoleculeTreeExtractionError` below, per FR-004's "distinct, identifiable failure kind" requirement). `resolve.py`'s caller then translates this into `MissingAtomManifestError` per the resolver error contract in research.md — that translation is `resolve.py`'s responsibility, not `get_or_extract`'s. |
| `molecule_path` fails FR-014's shape validation | Raised before any git/filesystem operation. Exact type TBD in tasks/implementation; MUST be distinguishable from the not-found and extraction-failure cases. |
| A tar member fails path-containment validation (FR-010/FR-011/FR-012) | `MoleculeTreeExtractionError` (data-model.md). This is a safety refusal, not a "not found" — a molecule tree that IS present but contains a malicious entry is a materially different situation from one that doesn't exist. |
| Any other IO/subprocess failure during extraction or atomic publish (disk full, permission denied, malformed tar stream `tarfile` cannot parse, `git archive` fails to launch at all) | `MoleculeTreeExtractionError` |

## Behavioral guarantees under concurrency (User Story 2)

- Two or more concurrent calls with the identical `(repo_dir, revision, molecule_path)` for a key that has never been materialized MUST both return successfully with correct, complete content (FR-008). Internally: the first caller to acquire the per-key lock performs extraction; subsequent callers either wait for the lock and then find the directory already present (fast path), or — if the implementation instead lets concurrent extractions race into independent temp directories with the lock only guarding the final atomic-rename step — both complete correctly regardless of which "wins" the rename, since both extracted content is identical for an immutable revision. Either internal strategy satisfies FR-008; `/speckit-tasks`/implementation picks one (recommendation: follow `publisher_fetch.ensure_object`'s existing precedent of "acquire lock, then check existence, then do work only if still needed" — avoids redundant `git archive` invocations under contention).
- An interrupted materialization (process killed after the temp directory has data written to it, before the atomic rename completes) MUST NOT leave a directory at the final cache path that a later caller would treat as a valid cache hit (FR-009). The temp directory itself may be left behind as an orphan (acceptable — it is never at the path future callers check) or may be cleaned up as a best-effort on the next successful call for the same or a different key; this spec does not require guaranteed temp-directory cleanup, only that the FINAL path is never observably corrupted.

## Non-goals of this contract

- Does not fetch, clone, or update `repo_dir`'s content — that is the caller's responsibility via existing `publisher_fetch` machinery.
- Does not verify content integrity via any cryptographic digest (explicitly out of scope per spec.md).
- Does not expire, invalidate, or refresh a previously-materialized directory — once present, always considered valid for that exact key (data-model.md's Invariant 3).
