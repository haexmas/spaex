# Data Model: v3 Vocabulary

**Spec**: 013
**Purpose**: enumerate every persistent v3 entity and its fields, so the tasks phase and the implementation reference one single source of truth.

Every entity below has its authoritative JSON Schema under [`contracts/`](contracts/). The tables here describe fields, invariants, and relationships in prose; schemas remain the machine-checkable contract.

---

## Consumer manifest (`.haex-hive.json`)

**Schema**: [`contracts/consumer-manifest.v3.schema.json`](contracts/consumer-manifest.v3.schema.json)
**Location**: repo root of a consumer project.
**Reader/writer**: the tool (`haex install`, `haex add`, `haex remove`, `haex migrate`).

| Field | Type | Required | Notes |
|---|---|---|---|
| `haex_hive_version` | string | yes | Must be `"3"`. |
| `identity` | string (reverse-DNS) | yes | Consumer's own project id. Preserved from v2. |
| `haex_hive_min_version` | string | no | Exact `X.Y.Z` or lower-bound `>=X.Y.Z`. Under v3 the constraint's major is `3` for a v3-native repo. |
| `compounds` | array of `compoundEntry` | yes | Renamed from v2 `atoms[]`. Empty allowed; empty = no external inheritance. |
| `groups` | array of string | no | v1 carry-over, unchanged. |
| `active_feature` | string or null | no | v1 carry-over, unchanged. |
| `identity_note` | string | no | v1 carry-over free-text operator note. |

### `compoundEntry`

| Field | Type | Required | Notes |
|---|---|---|---|
| `source` | canonical URL | yes | `https://` or `ssh://` per Principle II; no `.git` suffix; no credentials. |
| `revision` | full 40-hex SHA | yes | Immutable commit SHA per Principle IV. |
| `track` | string | no | Optional non-authoritative branch annotation; never overrides `revision`. |
| `molecules` | array of moleculeId | yes | Renamed from v2 `includes[]`. Reverse-DNS ids adopted from this source at this revision. Deduplicated, lexically sorted on write. |
| `config` | object | no | Per-molecule-id config overrides. Keys must be molecule-ids listed in this entry's `molecules` array. |

**Invariants**:

- Every `revision` is a full 40-hex SHA (no branch names, no `HEAD`, no short SHAs). Enforced at write time by `haex add` and at read time by the schema.
- The pair `(source, revision)` is unique across `compounds[]`; two entries with identical `source` MUST resolve to the same `revision`, or one of them was re-pinned atomically by `haex add` (which keeps all existing molecules of that source).
- Every molecule id in a compound's `molecules[]` MUST exist in the publisher-root manifest at that compound's `revision`. `haex install` refuses otherwise (`molecule-id-not-in-source` before the input reaches the resolver).

---

## Publisher-root manifest (`manifest.json` at publisher repo root)

**Schema**: [`contracts/publisher-manifest.v3.schema.json`](contracts/publisher-manifest.v3.schema.json)
**Location**: repo root of a publisher project (e.g. `haexmas/atoms`, `haexmas/haex-hive`).
**Reader**: the tool (`haex install`, `haex add`). **Writer**: the publisher, via a manual commit (never the tool).

| Field | Type | Required | Notes |
|---|---|---|---|
| `haex_hive_version` | string | yes | Must be `"3"`. |
| `publisher` | reverse-DNS string | yes | Publisher's namespace. Every molecule id in `molecules{}` MUST begin with `publisher + "."`. |
| `molecules` | object (map moleculeId → entry) | yes | Renamed from v2 `atoms{}`. |

### `publisherMoleculeEntry`

| Field | Type | Required | Notes |
|---|---|---|---|
| `path` | repo-relative POSIX path | yes | Directory (not file) containing the molecule's `manifest.json`. |
| `version` | semver `X.Y.Z` | yes | Publisher-declared molecule version. |
| `description` | string | no | Human-readable one-liner. |

---

## Molecule manifest (per-molecule `manifest.json`)

**Schema**: [`contracts/molecule-manifest.v3.schema.json`](contracts/molecule-manifest.v3.schema.json)
**Location**: inside a publisher repo at the `path` declared by that publisher's root manifest.

| Field | Type | Required | Notes |
|---|---|---|---|
| `haex_hive_version` | string | yes | Must be `"3"`. |
| `id` | reverse-DNS string | yes | MUST equal the publisher-root-manifest key that referenced this molecule. |
| `version` | semver `X.Y.Z` | yes | MUST equal the version the publisher root manifest declared. |
| `priority` | integer | yes | Publisher's default priority. Missing in v2 sources is filled with `100` by migration. |
| `atoms` | object (map category → paths) | yes | Category names mapped to non-empty lists of molecule-directory-relative delivered files. Replaces v2 scalar `contributes`. |
| `defaults` | object | no | Default values for the molecule's `config_schema`. |
| `config_schema` | repo-relative POSIX path | no | Path (molecule-directory-relative) to the molecule's config JSON Schema. |

**Category semantics**:

- Keys of `atoms{}` are category names as documented by Spec 010 (compiler + adapters). Known categories: `constitution`, `workflow`, `hooks`, `skills`, `prompts`, `mcp`, and adapter-specific ones.
- The value of each key is a non-empty, unique list of molecule-directory-relative POSIX paths. No absolute paths; no `..` segments.
- A molecule contributing a constitution declares `atoms.constitution: [<path>]` (typically one file). Spec 014 (single-non-negotiable-prose) rule interpretation still applies to the *consumer*'s adopted set.
- **Cross-category path overlap is refused**: no delivered path may appear in more than one category's list within a single molecule manifest's `atoms{}` map. JSON Schema's `uniqueItems` only detects intra-array duplicates, so the tool enforces this cross-array constraint at molecule-manifest load-time and refuses with `atoms-category-overlap` (per Spec 007's contract) before any publication. This is orthogonal to the `install.lock` `paths` uniqueness constraint, which covers the post-publication ledger.

---

## Install lock (`.haex-hive/install.lock`)

**Schema**: [`contracts/install-lock.v3.schema.json`](contracts/install-lock.v3.schema.json)
**Location**: `.haex-hive/install.lock` in a consumer repo.
**Writer**: `haex install`. **Readers**: `haex install`, external tools inspecting adopted state.

Field-level renames from v2 install-lock:

| v2 field | v3 field | Notes |
|---|---|---|
| `atoms` (top-level array of records) | `molecules` | Array of `MoleculeEntry` (renamed from `AtomInstallRecord`). |
| `atomInstallRecord.id` | `MoleculeEntry.id` | Field name unchanged; enclosing record renamed and simplified. |

**Superseded 2026-09-03** by Spec 008's own npm/pip-shape install.lock amendment (independent of the v2→v3 rename): `install.lock` now carries only `{haex_hive_version, generation_id, molecules[]}`, each entry `{id, source, revision, paths}`. `contributed_paths` is renamed to `paths`. The `constitution` block, `generated_by`, `participating_roots`, `generation_inputs`, and `visibility_marker` are all retired — constitution provenance and participating roots are now derived from `molecules[].paths[]` (see [contracts/install-lock.v3.schema.json](contracts/install-lock.v3.schema.json) and Spec 008's `spec.md`).

---

## Manifest lock (`.haex-hive.json.lock`)

**Location**: repo root of a consumer project.
**Lifecycle**: created once by the tool on first `haex add` / `haex remove` / `haex install`; NEVER renamed, deleted, or truncated by the tool afterward.
**Purpose**: permanent advisory file-lock target for serializing `.haex-hive.json` reads and writes across the tool's own processes.

The lock file itself carries no schema-relevant content. Its byte content is inconsequential; only the file's existence and the OS-level advisory lock on its file descriptor matter.

---

## State-directory migration proposals

**Location** (remote publisher case): `$HAEX_HIVE_STATE/migrations/<source-digest>/<revision>/<repo-relative-path>.migrated`.
**Lifecycle**: written by `haex migrate` in write mode; removed by the operator after adoption (copy into a publisher checkout, PR, pin bump).
**Purpose**: hold a v3 proposal for a manifest read from an immutable remote revision that the operator cannot directly edit.

The proposal file's content is byte-identical to the v3 shape the transform would produce as an in-tree sibling for a local file at the same v2 input.

---

## Relationships and lifecycle

```
consumer .haex-hive.json (v3)
   |
   |-- compounds[i].source ---> publisher repo URL
   |                            |
   |                            +-- root manifest.json (v3) ---> molecules{id -> entry}
   |                                                              |
   |                                                              +-- entry.path -> per-molecule dir
   |                                                                                    |
   |                                                                                    +-- manifest.json (v3)
   |                                                                                        atoms{category -> [files]}
   |
   +-- compounds[i].molecules[j] ---- matches key in publisher.molecules{}
                                      matches id in per-molecule manifest.json

.haex-hive/install.lock (v3)   <-- written by haex install after successful publication
.haex-hive/visibility.json     <-- unchanged from Spec 008
```

- `haex add`: reads and writes the consumer manifest; reads (via publisher clone) the publisher-root manifest and per-molecule manifests at the resolved SHA; delegates to `haex install` for `install.lock` and `visibility.json` publication.
- `haex remove`: reads and writes the consumer manifest; delegates to `haex install` for orphan-file deletion and `install.lock`/`visibility.json` update.
- `haex install`: reads the consumer manifest, resolves each compound against the corresponding publisher clone, writes `.haex-hive/install.lock` (v3 shape) and `.haex-hive/visibility.json` (unchanged from Spec 008).
- `haex migrate`: read-only against v2 originals; emits v3 proposals to `.migrated` siblings or state-directory paths; never writes to originals.
