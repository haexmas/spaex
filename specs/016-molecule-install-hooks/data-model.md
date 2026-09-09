# Phase 1 Data Model: Molecule install-hooks in `spaex install`

**Feature**: 016 | **Date**: 2026-09-08

## Overview

The model introduces `InstallHook` and a complete `ResolvedMolecule` record, and extends the molecule manifest and install-lock records. The schema extensions are additive and backwards-compatible with existing molecules and existing install-lock generations.

## Entities

### InstallHook (new dataclass)

Represents the parsed `install_hook` object from a molecule manifest.

**Fields**:

| Field | Type | Required | Constraint | Description |
|---|---|---|---|---|
| `interpreter` | `str` | yes | `len >= 1` | Program name on `PATH` (e.g. `"python3"`, `"bash"`, `"node"`). Resolved via `shutil.which()` at execution time. |
| `script` | `str` | yes | Molecule-directory-relative POSIX path, no leading/trailing slash, no `.`/`..` segments, no control chars. Same `RepoRelativePath` shape used elsewhere in v4. | Path (within the molecule cache directory) to the hook script that spaex will pass to the interpreter. |
| `args` | `list[str]` | no | Each element is a string. Absent field parses to `[]`. | Additional positional arguments passed to the interpreter after the script path. |
| `on_failure` | `Literal["abort", "warn"]` | no | Absent field parses to `"abort"` (explicitly set by parser, NOT via JSON-Schema default). | Failure policy. `"abort"` triggers Spec-008 install-transaction rollback on any hook failure. `"warn"` records `hook_status: "failed"` in install.lock and continues. |

**Invariants**:
- If constructed, all four fields hold defined values (no partial state).
- `interpreter` is not validated against `PATH` at parse time; that check happens at execution time and any failure produces the same policy result as a non-zero exit (per FR-016).
- `script` is not resolved against the cache at parse time; resolution + cache-containment check happens at execution time (per FR-014).

**Parser rules** (`MoleculeManifest.from_json()`):
- When the manifest JSON omits `install_hook`, the parsed `MoleculeManifest.install_hook` is `None`.
- When the manifest JSON includes `install_hook`, the parser constructs an `InstallHook` value with:
  - `interpreter` from the JSON's `interpreter` field.
  - `script` from the JSON's `script` field (already `RepoRelativePath`-validated by the schema).
  - `args` from the JSON's `args` field if present, else `[]`.
  - `on_failure` from the JSON's `on_failure` field if present, else the string `"abort"`. This assignment is explicit in parser code; the JSON-Schema `default` is documentation/validation metadata only and MUST NOT be relied upon.

### MoleculeManifest (extended)

**New field**:

| Field | Type | Required | Description |
|---|---|---|---|
| `install_hook` | `InstallHook \| None` | no | Present when the manifest declares a hook. `None` otherwise. Backwards-compatible: existing molecules without the field remain valid. |

All other `MoleculeManifest` fields (from Spec 007/013) are unchanged.

### ResolvedMolecule (new complete resolver record)

A complete resolver record produced from a consumer's `.spaex.json` compounds + publisher manifests + molecule manifests. The current resolver returns only `ResolvedConstitutionContribution` objects; T009 introduces this molecule-level record alongside or within an equivalent result type, retaining the existing contribution data for publication.

**Record contract** (existing resolver-local metadata is exposed to the hook runner; the parsed hook is added by this spec):

| Field | Type | Origin | Description |
|---|---|---|---|
| `molecule_id` | `str` | manifest | Reverse-DNS molecule id (e.g. `com.github.haexmas.atoms.graphify-first-authoring`). |
| `source_url` | `str` | consumer manifest, canonicalised | Publisher repo URL without trailing `.git`. Passed to `molecule_store.get_or_extract()` as its `source_url` argument — the stable, device-independent cache-key identity (Spec 017). |
| `revision` | `str` | consumer manifest | Full 40-hex commit SHA the compound is pinned to. Passed to `get_or_extract()` verbatim (already canonical at this point in the resolver). |
| `repo_dir` | `pathlib.Path` (absolute) | publisher-fetch | Local bare clone for `source_url` (`publisher_fetch.ensure_object()` / `clone_dir()`). An execution input to `get_or_extract()` — never itself part of the molecule-store cache key (Spec 017 FR-006/device-independence). |
| `molecule_path` | `str` | publisher manifest | Publisher-declared molecule directory path (e.g. `graphify-first-authoring`), i.e. `publisher_entry.path` from the two-step D11 lookup. **NEW**. Passed to `get_or_extract()` alongside `source_url`/`revision` to materialize the molecule's tree on demand. |
| `effective_priority` | `int` | `compounds[].config[<id>].priority` if present, else `manifest.priority` | Sort key for constitution assembly AND (this spec) hook execution ordering. |
| `install_hook` | `InstallHook \| None` | manifest, parsed | **NEW**. Passed through from the manifest so the hook runner consumes only the resolved record, not the raw manifest. |

**Invariants**:
- The resolver MUST produce a `ResolvedMolecule` for EVERY molecule selected by the consumer's compounds, regardless of whether the molecule contributes any `atoms.constitution` entry (FR-007). A hook-only molecule MUST NOT be filtered out.
- Hook materialization is **lazy**: constructing a `ResolvedMolecule` does not require extracting a tree. The hook runner calls `molecule_store.get_or_extract(record.repo_dir, record.source_url, record.revision, record.molecule_path, state_root)` only for an enabled hook with an available interpreter. Records without hooks and hooks skipped via `--no-install-hooks` cause no hook-driven extraction. Current constitution resolution still uses `git_show`; Spec 017's pending T016–T021 will independently materialize selected molecules on demand for their own manifest and constitution reads. Such resolver-driven extraction may also occur for molecules without hooks; the hook runner reuses the same cache key.

### install.lock per-molecule record (extended)

The `.spaex/install.lock` file records one entry per adopted molecule for the currently published generation.

**Extended fields**:

| Field | Type | Required | Constraint | Description |
|---|---|---|---|---|
| `id` | `str` | yes | Reverse-DNS molecule id | Existing. |
| `source` | `str` | yes | Canonical publisher URL | Existing. |
| `revision` | `str` | yes | 40-hex SHA | Existing. |
| `paths` | `list[str]` | yes | Consumer-relative POSIX paths | Existing. Files materialised from this molecule's atoms. |
| `hook_status` | `Literal["ok", "failed", "skipped"] \| absent` | no | Present ONLY when the molecule's manifest declared `install_hook` in the pinned revision | **NEW**. Absence signals "molecule declared no hook"; presence signals a hook outcome for the latest install of this generation. |

**Semantics of `hook_status`**:
- `"ok"`: hook was enabled (no `--no-install-hooks`) and exited 0.
- `"failed"`: hook was enabled but could not be launched (interpreter missing on `PATH`, `OSError` on `subprocess.run`), violated cache containment, or exited non-zero under `on_failure = "warn"`. (A failure under `on_failure = "abort"` does NOT produce this record because the entire generation rolls back.)
- `"skipped"`: the operator supplied `--no-install-hooks` for this invocation.

**Backwards-compatibility**:
- Older install-lock generations written before this feature landed have no `hook_status` field on any record. Reading such a lock is unchanged.
- Reading a new lock with an unfamiliar `hook_status` value (from a future spaex) MUST fall through to the schema's enum-validation, which rejects unknown values. There is no "unknown status" tolerance path.

### Hook side effects and the managed-generation boundary

Hooks run with the consumer repository root as their working directory, so
they may create or modify consumer-owned files such as `.gitignore`,
`.spaex-hook/hello-hook.marker`, git hooks, or provisioned tools. These are
external hook side effects: spaex MUST NOT copy them into the staged
generation, include them in `install.lock`, or pretend that the transaction
can undo them. Hook scripts MUST NOT write to paths under the spaex-managed
generation; writes there are outside this feature's contract. The example
marker therefore lives under `.spaex-hook/`, outside the managed `.spaex/`
generation.

**Hook-only transaction** (FR-025):
- When atom bytes are unchanged between two successive `spaex install` invocations but the resulting `hook_status` records differ from the current install.lock content, spaex publishes a new install.lock generation whose only change is the hook-status delta. Atom file bytes are not rewritten.
- When both atom bytes and hook-status records are unchanged, spaex performs the usual clean no-op after the hooks have run.

## State transitions

There are no long-lived stateful entities introduced by this feature. Every `spaex install` invocation:

1. Resolves the compounds → constructs the `ResolvedMolecule` collection (with `repo_dir`, `molecule_path`, and `install_hook` populated for every record — not just hook-carrying ones, per FR-007).
2. Materialises the resolved atom content into the Spec-008 staging generation. Current constitution-body reads use `git_show`; the pending Spec-017 resolver migration changes that content-read mechanism independently.
3. For each `ResolvedMolecule` with `install_hook != None`, in sort order: if hooks are disabled, records `skipped` without invoking the runner. Otherwise the runner checks the interpreter, obtains the molecule directory lazily through `get_or_extract()`, canonicalises and checks the script against that directory, then executes it with the consumer repository root as `cwd`. Hook-created side effects remain outside the staged generation.
4. Computes the `hook_status` for each record.
5. Publishes the install.lock (with hook_status fields) and swaps the staged generation, OR aborts and rolls back per `on_failure: "abort"` policy.

The parsed `InstallHook` and the resolved records are ephemeral to one invocation. Persistent state is captured only in:
- `.spaex.json` (unchanged by this feature; new `--no-install-hooks` flag is per-invocation, not written back).
- `.spaex/install.lock` (per-molecule `hook_status` field added, per generation).

## Relationships

```text
ConsumerManifest (.spaex.json)
  └── compounds[] (source, revision, molecules[], config[])
        └── PublisherManifest (fetched via git_show, unchanged)
              └── molecules[molecule_id] { path, version }
                    └── MoleculeManifest (currently git_show; Spec 017 T017 migration pending)
                          ├── atoms.<category>: [paths]
                          └── install_hook: InstallHook | None  ← NEW field
                                       │
                                       └── ResolvedMolecule { repo_dir, source_url, revision,
                                             molecule_path, install_hook, effective_priority }
                                                                          │
                                                       (lazy, hook runner only, Spec 017)
                                                                          ▼
                                              molecule_store.get_or_extract(repo_dir, source_url,
                                                revision, molecule_path, state_root)
                                                                          │
                                                                          ▼
                                                    real, on-disk molecule directory
                                                     (canonical script target checked here, then executed)
                                                                          │
                                                                          └── writes .spaex/install.lock
                                                                                └── per-molecule record.hook_status  ← NEW field
```

Note: the publisher root manifest continues to use `git_show.show_bytes()` under Spec 017 FR-016. Currently molecule manifests and constitution bodies also use `git_show`; their migration to `get_or_extract()` is specified by Spec 017 FR-015 but remains pending in T016–T021. That migration is separate from this hook integration. No new cross-repo relationships; this feature consumes the landed materialization API without assuming that the resolver has already migrated.
