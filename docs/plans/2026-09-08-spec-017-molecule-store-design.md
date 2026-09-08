# Spec 017 — Molecule tree materialization store

**Status**: Draft design doc; supersedes the unimplemented half of Spec 007's D15 with a scoped, current-vocabulary version.
**Author**: discovered mid-implementation of Spec 016 (2026-09-08); operator recalled the original D15 decision from the Spec 007 design session.
**Target spaex version**: 4.1.0 (ships alongside Spec 016; both land before the 4.1.0 release)

## Problem

[Spec 007's design doc, Decision D15](2026-08-28-spec-007-unified-manifest-design.md#d15-storage-layout-hybrid-content-addressed-store) (2026-08-28) specified a two-tier storage layout:

```
$HAEX_HIVE_STATE/repos/<clone-hash>/   — raw git clones (shared across consumer repos)
$HAEX_HIVE_STATE/store/<content-hex>/ — content-addressed shared store (deduplicated resolved-molecule trees)
.haex-hive/generated/ in consumer     — copies from store, agent-facing, committed
```

Only the first tier (`repos/<clone-hash>/`, now `SPAEX_STATE/repos/<digest>/`) was ever implemented, as `spaex.git.publisher_fetch.ensure_object()` / `spaex.migrate.transform.clone_dir()`. It creates a **bare** git clone — no working tree. The second tier (a materialized, deduplicated tree store) was never built. No document explicitly dropped it; the constitution-assembly feature that actually got implemented (Spec 007/008/013) never needed a working tree on disk, so it read individual file bytes directly via `git show <sha>:<path>` (`spaex.git.show.show_bytes`) instead, and the store tier quietly never got built.

This went unnoticed until Spec 016 (molecule install-hooks): a hook is a script that a subprocess interpreter must open and execute, plus (per the reference implementation, `graphify-first-authoring/install.py`) potentially import sibling modules relative to its own `__file__`. Byte-level `git show` access cannot support this — there is no file to point the interpreter at, and no directory for sibling-relative imports to resolve against. Spec 016's implementation cannot proceed without a real, materialized molecule directory on disk.

## What this spec does NOT do

Explicitly scoped down from the original D15, based on 2026-09-08 operator decisions:

- **No content-integrity hashing.** D15 specified an elaborate `haex-hive-tree-v1` byte-framed serialization with SHA-256 tree hashing, feeding `atoms[].content_integrity` lockfile fields and a `haex verify` CLI verb. Neither `content_integrity` nor `haex verify` was ever implemented (verified: zero occurrences in `src/spaex/` as of 2026-09-08). Building the full hashing scheme now, with no consumer, is speculative work. Deferred to a future spec if/when Spec 010 (compiler, still preview-stage) or an equivalent verification feature actually needs it.
- **No cross-device or cross-machine sync.** The store is a local, per-device cache under `SPAEX_STATE`, exactly like the existing `repos/` tier. No change to that model.
- **No `.spaex/generated/` consumer-visible tree.** D16's fully-committed `generated/` output (rules.md, hooks/, skills/, specs/ subdirectories) is Spec 010 (compiler) territory, still in preview status. This spec only materializes molecule trees into the **local cache**; what gets copied into the consumer repo is unchanged (still just `.spaex/constitution.md` and `.spaex/install.lock`, per Spec 007/008, plus whatever a hook decides to write per Spec 016).
- **No eager materialization of every resolved molecule regardless of need.** The store is populated on demand: called by whichever code path actually needs molecule content (see below), not proactively for the whole resolved-molecule graph.

## What this spec DOES do

Introduces one new module, `spaex.git.store` (or `spaex.install.molecule_store` — naming decided during `/speckit-plan`), exposing:

```python
def get_or_extract(repo_dir: Path, revision: str, molecule_path: str, state_root: Path) -> Path:
    """Return the local directory containing molecule_path's tree at revision.

    Extracts via `git archive <revision> -- <molecule_path>` piped into
    Python's stdlib `tarfile` (not the external `tar` binary — see Extraction
    mechanism below), into a cache keyed by (repo_dir, revision, molecule_path).
    Idempotent: a second call with the same key returns the same directory
    without re-extracting. Safe under concurrent processes via the existing
    `ManifestLockContext` pattern (matching `publisher_fetch.ensure_object`'s
    per-target lock file).
    """
```

### Cache key and layout

```
SPAEX_STATE/molecule-store/<source-digest>/<revision>/<molecule-path>/
```

- `<source-digest>`: same SHA-256-hex-16 digest scheme `clone_dir()` already uses for the `repos/` tier, applied to the canonical source URL. Reuses the existing digest helper rather than inventing a new one.
- `<revision>`: the full 40-hex SHA (immutable — safe to cache indefinitely, no staleness ever possible for a fixed revision).
- `<molecule-path>`: the publisher-declared molecule directory path (already validated as a safe `RepoRelativePath` — no `..`, no control characters — safe to use as literal path segments).

Presence of the final directory (post successful extraction) is itself the cache-hit signal; no separate marker file needed given the immutability of `(source, revision, molecule_path)`.

### Extraction mechanism

`git archive <revision> -- <molecule_path>` run against the bare clone (`repo_dir`, from the existing `repos/` tier — no new clone step needed), producing a tar stream on stdout. That stream is extracted using Python's stdlib `tarfile`, **not** the external `tar` binary:

- **Portability**: matches this project's "Python-only, py3-none-any wheel, Linux/macOS/WSL2" target (plan.md Technical Context, unchanged by this spec). Shelling out to `tar` would add a new external-binary dependency the project doesn't otherwise have (git and the configured interpreter are the only external tools spaex already assumes).
- **Path-safety**: `tarfile.extractall(path, filter="data")` (Python 3.12+) refuses member paths that would escape `path` via `..` segments, refuses device files, and strips unsafe metadata. On Python 3.10/3.11 (this project's stated minimum), `filter="data"` is unavailable; the extraction helper MUST perform equivalent manual validation — for each tar member, resolve its target path and verify containment under the destination directory before extracting, rejecting any member that would escape (symlink or `..`-based). This applies even though `git archive` only ever emits paths under the requested `molecule_path` prefix from a repository spaex itself does not control the trustworthiness of — the pinned SHA authenticates the publisher's bytes, but this extraction-time check is the same defense-in-depth principle Spec 016's `canonicalise_within` already applies at hook-invocation time (FR-014/015), just one layer earlier (at materialization time, before any file is used for anything).
- **Atomicity**: extract into a temporary sibling directory first (`<final-dir>.tmp-<random>`), then atomic rename into place. A crash or concurrent extraction mid-way never leaves a partially-extracted directory at the final path. Mirrors `publisher_fetch.ensure_object`'s own temp-dir-then-`os.replace` pattern for the bare clone itself.
- **Locking**: wrap extraction in a `ManifestLockContext` keyed off the destination directory (same pattern `ensure_object` uses: `repo_dir.with_name(repo_dir.name + ".lock")`), so two concurrent `spaex install` processes racing to extract the same `(source, revision, molecule_path)` don't corrupt each other's temp directories.
- **Resulting tar entries preserve the `molecule_path` prefix** (git archive does not strip the requested pathspec's leading directory). `get_or_extract` returns `<dest>/<molecule_path>`, not `<dest>` itself, so callers get a path that directly contains `manifest.json`, `constitution.md`, `install.py`, etc. — not one nesting level up.

### Callers migrated to the store

**`spaex.constitution.resolve.resolve_constitution_contributions`** — migrated per the 2026-09-08 operator decision to consolidate on a single molecule-content access path instead of maintaining two (git-show bytes AND store extraction) side by side:

- The publisher ROOT manifest read (`git_show.show_bytes(repo_dir, revision, "manifest.json", ...)`) stays unchanged — it is needed to discover each molecule's declared path *before* extraction is even possible (chicken-and-egg: the store key requires knowing `molecule_path`, which only the publisher manifest provides), and it is a single small file with no sibling-file needs.
- The per-molecule manifest read (currently `git_show.show_bytes(repo_dir, revision, f"{publisher_entry.path}/manifest.json", ...)`) is replaced: call `get_or_extract(...)` once for that molecule, then read `(cache_dir / "manifest.json").read_bytes()`.
- The constitution-file body read(s) (currently `git_show.show_bytes(repo_dir, revision, contribution_path, ...)` per declared `atoms.constitution` entry) are replaced: read `(cache_dir / constitution_path).read_bytes()` from the same already-extracted `cache_dir` — no additional extraction call, since the molecule's manifest read above already triggered it.

Net effect: one `git archive` call per resolved molecule (memoized across repeat calls within a process and across processes via the on-disk cache), replacing what were previously 1-2 `git show` calls per molecule. For a molecule contributing only a single small `constitution.md`, this is marginally more I/O up front (archive+extract vs. two byte reads) in exchange for a single, consistent code path. Given molecule trees are small (a manifest, a constitution fragment, occasionally a handful of hook/script files) and the result is cached indefinitely per immutable SHA, this trade is judged acceptable.

**`spaex.install.hook_runner`** (Spec 016, not yet implemented) — calls `get_or_extract(...)` to obtain `cache_dir`, then resolves `install_hook.script` against it exactly as Spec 016's data-model.md and tasks.md already describe, with one correction: `ResolvedMolecule.cache_dir` (as referenced by Spec 016's task T013) is now populated via this store rather than assumed to pre-exist. See "Spec 016 rework" below.

**`spaex.cli.add`** — explicitly OUT of scope. `add.py`'s own `git_show.show_bytes` calls exist to validate an adoption request (does the molecule exist, is a workflow-category conflict present, etc.) before writing `.spaex.json`, independent of the full resolution `spaex install` performs afterward. These are single small-manifest reads with no sibling-file needs; migrating them to the store would add extraction overhead to a validation path that doesn't need a tree, for no behavioral benefit. Left unchanged.

### ResolvedMolecule field correction (affects Spec 016)

Spec 016's `data-model.md` described `ResolvedMolecule.cache_dir` as "Immutable extracted publisher tree for this revision" without specifying who extracts it or when. That was underspecified — this spec fills the gap: `cache_dir` is populated by calling `get_or_extract()` at the point each caller (resolver, hook runner) actually needs molecule content, not eagerly by the resolver for every resolved molecule regardless of use. Spec 016's task list (T009, T013) will be revised in a follow-up amendment once this spec's implementation lands, to call `get_or_extract()` at the correct call sites instead of assuming a pre-populated field.

## Testing

- **Unit tests** for `get_or_extract`: extraction produces expected files; repeated calls with the same key return the same directory without re-extracting (verify via a marker file inside the source molecule that would be duplicated/corrupted by a naive re-extraction, or via mtime-stability of the returned directory); concurrent extraction (two threads/processes) does not corrupt state (lock contention test); a crafted tar member with a `..`-escaping path is rejected (path-containment test, mirroring Spec 016's `canonicalise_within` unit tests); a molecule path absent at the given revision fails cleanly with a typed error.
- **Integration tests** for the migrated `resolve.py`: existing `tests/unit/test_resolve.py` suite (fixture-based, using real git repos per its established `_publish`/`_clone` helpers) MUST continue to pass unchanged in behavior — same constitution contributions resolved, same ordering, same error types for missing/invalid manifests. This is a refactor-with-stable-contract; no existing test should need behavioral changes, only (if needed) fixture adjustments for the new intermediate extraction step.
- **Cross-platform note**: `tarfile`-based extraction (not shelling out to `tar`) is chosen specifically so these tests run identically on Linux, macOS, and Windows/WSL2 without requiring a `tar` binary on `PATH`.

## Dependencies

- **Spec 007** (Unified Manifest v2): originated the D15 decision this spec implements a scoped subset of.
- **Spec 008** (Install Transaction): the store sits below the install-transaction boundary — extraction happens as a read-side operation before atoms are staged; it does not interact with the staging-generation-then-publish rename-swap machinery.
- **Spec 016** (Molecule install-hooks): the concrete, immediate consumer that surfaced this gap. Spec 016's implementation is blocked on this spec landing first (or landing together, if implemented in the same session).

## Open items for `/speckit-plan`

- Final module path/name (`spaex.git.store` vs `spaex.install.molecule_store` vs other) — a naming call, not a design call; resolved during planning against the existing `git/` vs `install/` module boundary conventions.
- Whether `get_or_extract` takes `state_root` explicitly (matching `ensure_object`'s signature) or reads it from a shared config object — follow the codebase's existing convention once identified in `/speckit-plan`'s research phase.
