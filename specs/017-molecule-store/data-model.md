# Phase 1 Data Model: Molecule tree materialization store

**Feature**: 017 | **Date**: 2026-09-08

## Overview

One new capability (`get_or_extract`), one new error type, and a migration of two existing read call sites in `constitution/resolve.py`. No new persistent, versioned, or consumer-visible data structures — everything introduced here is either an internal cache-key concept or an in-memory value used for one call's duration.

## Entities

### MaterializationKey (conceptual — not necessarily a literal class)

The triple that identifies one cache entry.

| Field | Type | Constraint | Description |
|---|---|---|---|
| `repo_dir` | `pathlib.Path` | Must be an existing, already-cloned bare git repository (produced by `publisher_fetch.ensure_object`) | The local git object store to read from. Not itself part of the cache KEY (the same content, if ever cloned to two different local paths for the same canonical source, would still be identified by `source-digest`, which `repo_dir`'s caller already derives via `clone_dir()`), but the input needed to perform extraction. |
| `revision` | `str` | Full 40-character lowercase hex SHA. Callers MUST supply the canonical form (resolved via `git_revparse.full_sha()` beforehand) — `get_or_extract` treats a non-canonical-looking input as a caller contract violation, not a value it will normalize itself (see contracts/get-or-extract.md). |
| `molecule_path` | `str` | A safe, relative POSIX path (no `..` segments, no leading `/`, no control characters) — the same `RepoRelativePath` shape already validated elsewhere in the v4 manifest schema. | The publisher-declared subtree to materialize. |

**Cache key derivation**: `SPAEX_STATE/molecule-store/<source-digest>/<revision>/<molecule_path>/`, where `<source-digest>` is derived from the canonical source URL using the same SHA-256-hex-16 digest scheme `clone_dir()` already uses (the caller, not `get_or_extract` itself, is responsible for deriving `repo_dir` from the source URL via the existing `clone_dir()` — `get_or_extract` receives `repo_dir` directly and derives its OWN cache-directory digest from the same source URL input the caller used to produce `repo_dir`, keeping the two digests consistent by construction. See contracts/get-or-extract.md for the exact signature.)

### MaterializedDirectory (the return value)

Not a distinct class — `get_or_extract` returns a plain `pathlib.Path`. Documented here for its invariants:

- **Invariant 1**: the directory exists on disk and is a real directory (not a symlink to one) at the moment of return.
- **Invariant 2**: the directory directly contains the requested subtree's top-level entries — never nested one level deeper under a `molecule_path`-named child (FR-002).
- **Invariant 3**: once successfully returned for a given `MaterializationKey`, the directory's content never changes for the lifetime of the local cache (revisions are immutable; there is no "refresh" or "invalidate" operation in this spec).
- **Invariant 4**: every file inside has passed the path-containment validation in `contracts/tar-member-validation.md` — no file inside can be a symlink/hardlink that escapes the directory, and no file's own path escapes it either.

### MoleculeTreeExtractionError (new)

New member of `spaex.util.errors`, following the existing `HaexError` subclass pattern (see e.g. `PinnedRevisionNotFoundError`, `MissingAtomManifestError` for the sibling shape to match).

| Field | Value |
|---|---|
| `diagnostic_key` | `"molecule-tree-extraction-failed"` |
| `exit_code` | `exit_codes.IO_REFUSE` (matching `PinnedRevisionNotFoundError`'s category — an environment/IO-level refusal, not a user-input-shape refusal) |
| `hint` | Something like: "Check the publisher repository is reachable and the local cache is writable; if the failure persists, the source content may be malformed." |

Raised for: `git archive` subprocess failures other than the "pathspec did not match" not-found case (e.g., unexpected non-zero exit for a different reason, or the subprocess failing to launch at all); a malformed/corrupt tar stream that `tarfile` cannot parse; a path-containment refusal per FR-010/FR-011/FR-012 (a tar member that must be rejected for safety); a filesystem-level failure during the atomic-publish step (disk full, permission denied) that is not itself one of the more specific existing error types.

**Explicitly NOT raised for**: "molecule path does not exist at this revision" (this is the `git archive` exit-128 case, translated by callers — see below — into whichever existing "not found" error fits their context, not into `MoleculeTreeExtractionError`).

### Existing errors reused (no schema change, behavior clarified)

| Error | Raised by `resolve.py` when |
|---|---|
| `PinnedRevisionNotFoundError` | The compound's revision cannot be resolved to a canonical SHA in the local clone at all (unchanged — `git_revparse.full_sha()` already raises this; this spec's only change is that `resolve.py` now correctly captures and uses the returned canonical value). |
| `MissingAtomManifestError` | Either (a) `get_or_extract()` fails because the declared molecule path doesn't exist at the pinned revision (`git archive` exit 128), or (b) the molecule path exists but `manifest.json` is absent inside the materialized directory, or (c) the materialized manifest fails to parse / has a mismatched id or version — same conditions this error already covers today, now reached via a materialized-directory read instead of a `git show` byte read. |
| `ContributionFileNotFoundError` | A molecule manifest declares a constitution file path that is not actually present inside the materialized directory (unchanged condition, now reached via a materialized-directory read). |

## Relationships

```text
ConsumerManifest (.spaex.json)
  └── compounds[] (source, revision, molecules[])
        └── PublisherManifest (fetched via git_show.show_bytes — UNCHANGED)
              └── molecules[molecule_id] { path, version }
                    │
                    ├── (existing, unchanged) canonical revision resolved via git_revparse.full_sha()
                    │     — return value NOW captured and used consistently (this spec's fix)
                    │
                    └── molecule_store.get_or_extract(repo_dir, canonical_revision, path, state_root)
                              │
                              └── returns: MaterializedDirectory (real directory on disk)
                                        │
                                        ├── manifest.json  ← read directly (was: git_show.show_bytes)
                                        │      → MoleculeManifest.from_json(...)
                                        │
                                        └── <declared constitution path>  ← read directly (was: git_show.show_bytes)
                                               → ResolvedConstitutionContribution.body
```

## State transitions

None in the traditional sense — a `MaterializedDirectory` has exactly two states relative to any given `MaterializationKey`: **absent** (no successful materialization has ever completed for this key) and **present** (materialization completed successfully at least once; permanently valid thereafter, per Invariant 3). There is no "stale," "expired," or "invalidated" state in this spec's scope — that would require either a TTL policy (not specified, not needed given revision immutability) or an explicit invalidation trigger (not specified — out of scope; see spec.md's Out-of-scope section on content-integrity verification, which is the natural home for any future "detect and repair corruption" capability).

The only state-adjacent behavior is the **in-progress** window during a single call to `get_or_extract()` for a not-yet-materialized key: content is being extracted into a temporary location, not yet visible at the final cache path. This window is protected by the lock (Story 2) and is never observable by another caller as anything other than "absent" (if it queries before the lock is acquired or while it's held) or "present" (only after the atomic rename completes).
