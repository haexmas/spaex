# Phase 1 Data Model: Composition Status and Provenance Query

All entities below are process-internal (computed on every invocation from on-disk state); nothing here is persisted. Field names match the JSON output shape (`--format json`); the text renderer presents the same fields in prose.

## CompositionReport (`spaex status`)

| Field | Type | Origin | Notes |
|---|---|---|---|
| `format_version` | `int` | New | `1`. Bumped on any incompatible shape change. |
| `molecules` | `list<MoleculeRecord>` | `.spaex/manifest.json` ∪ `.spaex/install.lock` | Union of pinned and installed molecule ids, sorted by `molecule_id`. |
| `constitution` | `ConstitutionSummary \| null` | `.spaex/constitution.d/`, `.spaex/constitution.md` | `null` when neither exists (edge case "No behavior molecules"). |
| `drift` | `list<DriftFinding>` | research.md R3, R4 | Empty list when the manifest, lock and constitution are all consistent. |

## MoleculeRecord

One molecule appearing in either the manifest's pins or the install lock (FR-003, FR-004, FR-005).

| Field | Type | Origin | Notes |
|---|---|---|---|
| `molecule_id` | `str` | Manifest `compounds[].molecules[]` / Lock `MoleculeEntry.id` | |
| `pinned` | `{source, revision} \| null` | Manifest `CompoundEntry.source`/`.revision` | `null` when installed but no longer pinned. |
| `installed` | `{source, revision} \| null` | Lock `MoleculeEntry.source`/`.revision` | `null` when pinned but not installed. |
| `install_state` | enum `installed` \| `pinned_not_installed` \| `installed_not_pinned` | Derived | `installed` covers both a clean match and a revision mismatch — the mismatch itself is a separate `DriftFinding`, not a fourth state, so a molecule is never in two states. |
| `hook_status` | `"ok" \| "failed" \| "skipped" \| null` | Lock `MoleculeEntry.hook_status` | `null` when the molecule declares no `install_hook` or is not installed. |
| `atoms` | `AtomGrouping` | research.md R1 | Present even when every bucket is empty (edge case "contributes nothing observable"). |

## AtomGrouping

Per-molecule breakdown of what spaex materialized from its atoms, grouped by kind rather than by the molecule manifest's own category names (research.md R1; 2026-09-22 clarification).

| Field | Type | Origin | Notes |
|---|---|---|---|
| `behavior_fragments` | `list<str>` (fragment ids) | `.spaex/constitution.d/<molecule-id>/*.md` file stems | Sorted. Empty list, not omitted, when the molecule contributes no behavior fragments. |
| `composed_artifacts` | `list<str>` (repo-relative paths) | `InstallLock.molecules[].paths` entries with more than one owning molecule, excluding `COMPOSED_CONSTITUTION_RELATIVE_PATH` | Sorted. Today only `.spaex/generated/nix-packages.json` (Spec 027) can appear; the rule is generic over any future composable category. |
| `files` | `list<str>` (repo-relative paths) | `InstallLock.molecules[].paths` entries with exactly one owner, excluding `COMPOSED_CONSTITUTION_RELATIVE_PATH` | Sorted. This is FR-004's per-molecule file list, reused as the third bucket. |

## ConstitutionSummary

| Field | Type | Origin | Notes |
|---|---|---|---|
| `exists` | `bool` | `.spaex/constitution.md` presence | |
| `clause_counts` | `map<modality, int>` | `.spaex/constitution.md`, parsed via the shared `parse_clauses` (research.md R5) | Keys are the six modalities (`MUST`, `MUST_NOT`, `SHOULD`, `SHOULD_NOT`, `MAY`, `MAY_NOT`); a modality with zero clauses is omitted rather than listed as `0`, matching `constitution trace`'s existing clause-section convention. |
| `contributing_molecules` | `list<str>` | `.spaex/constitution.d/` directory names, excluding `_project` | Sorted. |
| `project_local_fragment_ids` | `list<str>` | `.spaex/constitution.d/_project/*.md` file stems | Sorted. Empty list when there are none. |
| `stale` | `bool` | research.md R4 (local fingerprint recomputation) | `true` when the recomputed `source_hash`/`build_input_hash` do not match the header, or the header is unreadable while fragments exist. |

## DriftFinding

One disagreement between the manifest, the install lock, or the composed constitution (User Story 4).

| Field | Type | Origin | Notes |
|---|---|---|---|
| `kind` | enum `pinned_not_installed` \| `installed_not_pinned` \| `revision_mismatch` \| `constitution_stale` | research.md R3, R4 | |
| `molecule_id` | `str \| null` | — | `null` only for `constitution_stale`, which is not per-molecule. |
| `pinned` | `{source, revision} \| null` | Manifest | Present for `pinned_not_installed` and `revision_mismatch`. |
| `installed` | `{source, revision} \| null` | Lock | Present for `installed_not_pinned` and `revision_mismatch`. |

`spaex status` reports `drift` without changing its own exit code (FR-007, Assumption "Drift is informational"); the text renderer additionally prints a one-line hint to run `spaex install` when `drift` is non-empty.

## FileAttribution (`spaex trace <path>`)

Result of one `spaex trace` invocation.

| Field | Type | Origin | Notes |
|---|---|---|---|
| `format_version` | `int` | New | `1`. |
| `query` | `str` | Normalized input | The resolved repo-relative path, forward-slash form, after applying FR-011's path-form normalization. |
| `kind` | enum `file` \| `directory` | Derived | `directory` when `query` matches a path prefix rather than an exact recorded path. |
| `matches` | `list<PathOwnership>` | research.md R2 | One entry for a file query; every recorded path under the prefix for a directory query, sorted by path. Empty when nothing is recorded. |
| `error` | `str \| null` | — | Present (and `matches` empty) when nothing is recorded for `query` (FR-010); explains that hand-written and install-hook-written files are not tracked. |

### PathOwnership

| Field | Type | Origin | Notes |
|---|---|---|---|
| `path` | `str` | `InstallLock.molecules[].paths` | Repo-relative, forward slashes. |
| `owners` | `list<{molecule_id, source, revision}>` | `InstallLock.molecules[]` | One entry per owning molecule; more than one only for a shared path (the composed constitution, or a composed generated artifact). |
| `constitution_trace_hint` | `bool` | `path == COMPOSED_CONSTITUTION_RELATIVE_PATH` | `true` only for `.spaex/constitution.md` (FR-009); the text renderer turns this into a pointer line to `spaex constitution trace`, the JSON renderer leaves clause-level lookup to a separate call. |

## Reused, unmodified entities

- **`ConsumerManifest` / `CompoundEntry`** (`spaex.model.consumer_manifest`): source of `pinned`, flattened via the new public `flatten_compound_pins` function this feature adds to that module (research.md R5 addendum) — the dataclasses themselves are unmodified.
- **`InstallLock` / `MoleculeEntry`** (`spaex.model.install_lock`): source of `installed`, `hook_status`, and every `paths` list this feature groups.
- **`BehaviorFragment`** (`spaex.behavior.fragment`): parses each `.spaex/constitution.d/<molecule-id>/<fragment-id>.md` file; its `id` is the fragment id in `AtomGrouping.behavior_fragments`.
- **`TracedClause`** (renamed/promoted from `behavior_commands._TracedClause` to `spaex.behavior.clauses.TracedClause`, research.md R5): source of `ConstitutionSummary.clause_counts` and, transitively, `contributing_molecules` (every clause's `provenance` entries' molecule-id segment).

## State transitions

None. Every entity here is recomputed fresh on each invocation from already-persisted state; nothing introduced by this feature is written, cached, or carried between invocations.

## Read consistency

Building a `CompositionReport` or a `FileAttribution` reads several files under `.spaex/` that a concurrent `spaex install` publishes as one atomic unit (research.md R9). Both builders bracket their read with `InstallLock.generation_id` (read first, re-read last) and retry once on a mismatch, so the entity returned always reflects one single generation, never a mix of two (FR-015).
