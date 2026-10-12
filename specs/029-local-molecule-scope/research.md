# Research: Local (Per-Developer) Molecule Scope

All file references are repo-relative to `src/spaex/` unless marked otherwise.

## R1. Where local state lives

**Decision**: Everything spaex owns for local scope lives under `.spaex/local/`:
`manifest.json` (the local overlay), `install.lock` (local install record),
`constitution.d/`, `constitution.md` (local behavior document),
`generated/` (local composable outputs), plus a self-ignoring
`.spaex/local/.gitignore` containing the single pattern `*`.

**Rationale**:
- The spec asks for the overlay "next to the project manifest". A subdirectory keeps all local artifacts in one place that is trivially excluded and trivially deleted.
- A `.gitignore` with `*` inside the directory ignores the directory's entire content including itself (verified with git: `git add -A` stages nothing under it, `git check-ignore -v` attributes the match to `.spaex/local/.gitignore:1:*`). It needs no git config, works identically in every worktree, and needs no edit to any committed ignore file (FR-005).
- The install-lock path pattern already admits `.spaex/local/...` (leading dot-segment).

**Alternatives considered**:
- `.spaex/manifest.local.json` and other `*.local.*` siblings directly under `.spaex/`: each file would need its own exclusion entry, and they would interleave with committed files.
- A sibling directory `.spaex-local/`: visually confusable with the transaction's `.spaex.next`/`.spaex.prev` siblings and a second top-level footprint.
- Per-user state under `$SPAEX_STATE`: invisible from the checkout, breaks "next to the project manifest", and complicates per-worktree independence.

## R2. Surviving the `.spaex/` rename-swap

**Decision**: Local-scope files are staged into the same `.spaex` generation as project files. `.spaex/local/**` is added to the set the install stages on every publish (today's `_preserved_project_local_files` and `extra_spaex_files` paths in `cli/install.py`), so one `transaction.publish_generation` publishes both scopes atomically.

**Rationale**: `io/transaction.py` rename-swaps the whole `.spaex/` directory; any unstaged file is dropped. Staging both scopes into one generation reuses the existing crash safety (`.spaex.prev` restore, `SPAEX_CRASH_AFTER` seam) and satisfies FR-016 without a second transaction. Repo-root writes for local exclusive atoms run in the same `post_write_verify` snapshot/restore step as project ones (`constitution/publish.py:231-246`).

**Alternatives considered**: a second, nested swap of `.spaex/local/` after the project swap. Rejected: two commit points need a compensating rollback of the first when the second fails, which is the problem the single swap already solves.

**Known ceiling**: an older spaex version (without this feature) running `spaex install` in the same checkout drops `.spaex/local/` because it does not stage it. The overlay itself is small and recreatable with `spaex add --local`; documented in the quickstart.

## R3. Overlay format

**Decision**: New schema `local-manifest.v1.schema.json`: `{ "spaex_version": "4", "compounds": [...] }`, `additionalProperties: false`. Compound entries reuse the consumer-manifest compound shape (`source`, `revision`, `molecules`, optional `config`) and the same validation (canonical source, 40-hex revision, unique molecules). Parsing reuses `ConsumerManifest`'s compound parsing, extracted into a shared function rather than duplicated.

**Rationale**: FR-002 requires the same adoption shape. `identity`, `spaex_min_version`, `groups`, `skill_installation` and `constitution.local_fragments` are project-level concerns; allowing them locally would create a second, conflicting source of truth.

**Alternatives considered**: reusing the full v4 consumer manifest for the overlay. Rejected because `identity` is required there and would have to be duplicated or faked.

## R4. Local install record

**Decision**: `.spaex/local/install.lock`, same `install-lock.v4` schema and `InstallLock` model as the project lock. Its `generation_id` equals the project lock's generation id of the same publish. Orphan deletion for local scope reuses `_delete_orphaned_paths` with the previous and current local locks.

**Rationale**: Same semantics (paths, hook status, speckit record, content hashes), zero new model code. One generation id across both files makes `status` consistency checks (`read_with_consistent_generation`) cover both reads.

## R5. Local behavior composition

**Decision**: Local behavior fragments are materialized into `.spaex/local/constitution.d/<molecule>/` and composed by the existing behavior orchestrator into `.spaex/local/constitution.md`, run as a second pass with local roots and local fragments only. The emitted document starts with a fixed preamble: it supplements `.spaex/constitution.md`, and project rules prevail on conflict (FR-008). The project pass is unchanged and receives no local fragments (FR-007, SC-002).

**Rationale**: reuses composer, clarifications and staleness logic; the only parameterization is the output root and the fragment set. Composing project plus local together would make the developer's copy of the team constitution diverge and would recompose the team document on every local change.

**Alternatives considered**: concatenating local fragments verbatim without the composer. Rejected: loses deduplication and modality normalization the project pass gets, and creates a second rendering format agents must understand.

## R6. Making agents read the local document

**Decision**: Bump the global bootstrap block (`behavior/bootstrap.py`, ADR 0013) from version 2 to 3. The new text adds: "If `.spaex/local/constitution.md` exists, read it after the project constitution; it holds the developer's personal rules for this checkout and never overrides project rules." After install, when a local behavior document exists and an installed runtime block is older than version 3, spaex prints a one-line hint to rerun `spaex install --global` (extending `maybe_emit_no_bootstrap_hint`).

**Rationale**: the block is the only mechanism agents use to find spaex policy; spaex never writes project-level agent files. The existing upgrade path (version marker plus `--global`) handles the change.

## R7. Keeping local outputs outside `.spaex/local/` out of git

**Decision**: Paths outside `.spaex/local/` that local scope writes (exclusive generic atoms at the repo root, Spec Kit output) are listed in a marker-delimited block in the file returned by `git rev-parse --git-path info/exclude`:

```
# spaex-local:start worktree="<git-dir name>"
/flake.local.nix
# spaex-local:end worktree="<git-dir name>"
```

One block per worktree, keyed by the basename of `git rev-parse --git-dir` (`.git` for the primary checkout). spaex rewrites only its own block for the current worktree, creates the file and its `info/` directory when missing, and removes the block when it becomes empty. Entries are anchored (`/path`) so they match only at the repo root. Outside a git repository the step is skipped (spec edge case).

The block is reconciled only after all in-tree staging and validation succeeds and
is replaced through a temporary file plus atomic rename. If that write fails,
the generation and repo-root snapshot are rolled back before the install
returns an error. A process crash between the in-tree rename and the exclude
rename is repaired by the next install, which reconciles the block from the
current local lock before reporting success.

**Rationale**:
- `info/exclude` is git's built-in per-clone, never-committed ignore file, so no committed `.gitignore` changes (FR-005). Writing `.gitignore` itself is not an option: it can be an exclusive atom of a project molecule.
- Verified: `info/exclude` lives in the common git dir and is shared by all worktrees, hence the per-worktree key so removing a local adoption in one worktree never drops another worktree's entries.

**Known ceiling** (to be marked `ponytail:` in code): because all worktrees share the file, an entry added by worktree A also ignores the same untracked path in worktree B. The harm is limited to hiding an untracked file at exactly that path; upgrade path is per-worktree `core.excludesFile` via `extensions.worktreeConfig`, deferred until someone needs it.

**Alternatives considered**: per-worktree `core.excludesFile` now (requires enabling `extensions.worktreeConfig` repository-wide, a git config change with wider blast radius); adding entries to `.spaex/local/.gitignore` (git only applies a `.gitignore` to its own directory and below, so it cannot cover repo-root paths).

## R8. Refusing writes that would change the committed tree

**Decision**: Before any write, local exclusive atom destinations are checked against (a) every path owned by project scope in the same install and (b) `git ls-files -z -- <paths>`. Any hit refuses the whole install with a typed diagnostic naming the molecule, path and reason, and nothing is written (FR-006, FR-016).

**Rationale**: `info/exclude` has no effect on tracked files (verified), so excluding is not enough; writing would show up as a modification. Refusing the whole install, rather than silently skipping the local molecule, follows the project's no-silent-degradation precedent (Spec 027 clarification) and leaves the developer a clear fix (`spaex remove --local <id>`).

## R9. Same molecule in both scopes

**Decision**:
- `spaex add --local <id>` refuses when `<id>` is pinned in project scope (new error key `local-adoption-shadowed`).
- At install time, a molecule present in both is resolved only from project scope; the local entry is reported as `shadowed` by `install` and `status` and contributes nothing. The overlay is not rewritten automatically (self-modifying state stays operator-driven).

**Rationale**: FR-010; project wins (spec Assumptions). A teammate's later project adoption must not break the developer's install.

## R10. Spec Kit in local scope

**Decision**: If project scope has a `speckit` declaration, a local molecule with a `speckit` declaration is refused at `add --local` and at install (FR-013). If only local scope declares it, the existing `integrations/speckit.prepare_install` runs with the local lock as its `existing_lock`. Output paths to exclude are read from the official CLI's per-integration manifests (`.specify/integrations/<key>.manifest.json`) after install, plus `/.specify/` when local scope created it.

**Rationale**: one Spec Kit policy per checkout, matching the existing `SpeckitDeclarationConflictError` rule across molecules; the official CLI owns the file list, so spaex reads it instead of guessing.

## R11. Install hooks in local scope

**Decision**: Local hooks run through `install/hook_runner.run_install_hook` like project hooks, after project hooks, with an added environment variable `SPAEX_SCOPE=local` (`project` for project hooks). The local install snapshots repository state around each hook: a changed tracked or project-owned path refuses the publish and restores the pre-hook state; newly created untracked repository paths are added to the local lock and the per-worktree exclusion block before publication. `spaex add --local` of a hook-bearing molecule prints a one-time warning that side effects outside the repository are not covered by these checks (FR-014).

**Rationale**: hooks are arbitrary code, so the repository boundary must be enforced by observing their side effects rather than trusting hook authors. `SPAEX_SCOPE` still lets a hook author place outputs appropriately; the snapshot also prevents a hook from silently modifying committed or project-owned files.

## R12. Composable categories

**Decision**: `nix_packages` contributions from local molecules compose into `.spaex/local/generated/nix-packages.json` (same composition function, local input set). The project file is unchanged. Consuming the local file (for example a `flake.nix` that optionally reads it) is a publisher-side follow-up, out of scope.

## R13. CLI surface

**Decision**: `spaex add --local` and `spaex remove --local`. `spaex install` always applies both scopes (no flag). `spaex status` and `spaex trace` gain a `scope` field in JSON output and a scope label in text output; JSON `format_version` goes from 1 to 2 because existing consumers may treat the molecule list as project-only. `spaex constitution show` prints the project document, then the local document under a `## Local (this checkout only)` separator.

**Alternatives considered**: `--scope project|local` instead of `--local`. Rejected for now: there are exactly two scopes and project is the default; a boolean flag is the shortest unambiguous surface (can grow into `--scope` if a third scope appears).

## R14. Graph consultation before new names

`graphify query` was run for "git ignore exclude entries writer", "overlay manifest scope local adoption" and "preserved files across spaex generation swap":
- No existing ignore or exclude writer exists (only comments mention `.gitignore`).
- `install/overlay.py` exists but is an empty stub for "mixed-ownership overlay primitives (FR-003)", an unrelated concept; the new module is named `install/local_scope.py` to avoid conflating the two.
- `_preserved_project_local_files` (`cli/install.py:656`) is the existing hook point for staging `.spaex/local/**` and is extended rather than duplicated.
- `ConsumerManifest.from_json` compound parsing is extracted and shared rather than copied (R3).

## Side finding (out of scope, separate fix)

`cli/add.py` `_mutate_compounds` and `cli/remove.py` `_apply_removal` rebuild `ConsumerManifest(...)` without `skill_installation`, so every add or remove drops a persisted skill policy (`cli/skills.py` correctly uses `dataclasses.replace`). Tracked as a separate bug fix, not part of this feature; the local-scope add/remove code must not copy the pattern.
