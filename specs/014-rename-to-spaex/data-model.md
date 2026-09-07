# Data Model: v4 Vocabulary

**Spec**: 014
**Purpose**: enumerate every persistent v4 entity, its fields, and the v3→v4 delta so downstream phases have a single source of truth.

Every entity below has its authoritative JSON Schema under [`contracts/`](contracts/). Structurally, **v4 is identical to v3** for every entity here. Only the version-field name changes (`haex_hive_version` → `spaex_version`, value bumps `"3"` → `"4"`) and the min-version-field name (`haex_hive_min_version` → `spaex_min_version`).

The file-naming convention (`.haex-hive.json` → `.spaex.json`; `.haex-hive/install.lock` → `.spaex/install.lock`) is orthogonal to the schema shape but ships in the same feature.

---

## Consumer manifest (`.spaex.json`)

**Schema**: [`contracts/consumer-manifest.v4.schema.json`](contracts/consumer-manifest.v4.schema.json)
**Location**: repo root of a consumer project (renamed from `.haex-hive.json`).
**Reader/writer**: the tool (`spaex install`, `spaex add`, `spaex remove`, `spaex migrate`).

| Field | Type | Required | Notes |
|---|---|---|---|
| `spaex_version` | string | yes | Must be `"4"`. **v3→v4 delta**: name renamed from `haex_hive_version`, value bumped from `"3"`. |
| `identity` | string (reverse-DNS) | yes | Consumer's own project id. Unchanged from v3. |
| `spaex_min_version` | string | no | Exact `X.Y.Z` or lower-bound `>=X.Y.Z`. Under v4 the major is `4` for a v4-native repo. **v3→v4 delta**: name renamed from `haex_hive_min_version`. |
| `compounds` | array of `compoundEntry` | yes | Unchanged from v3. Empty allowed; empty = no external inheritance. |
| `groups` | array of string | no | v1 carry-over, unchanged. |
| `active_feature` | string or null | no | v1 carry-over, unchanged. |
| `identity_note` | string | no | v1 carry-over free-text operator note. |

### `compoundEntry` (unchanged from v3)

| Field | Type | Required | Notes |
|---|---|---|---|
| `source` | canonical URL | yes | `https://` or `ssh://` per Principle II; no `.git` suffix; no credentials. |
| `revision` | full 40-hex SHA | yes | Immutable commit SHA per Principle IV. |
| `track` | string | no | Optional non-authoritative branch annotation; never overrides `revision`. |
| `molecules` | array of moleculeId | yes | Reverse-DNS ids adopted from this source at this revision. Deduplicated, lexically sorted on write. |
| `config` | object | no | Per-molecule-id config overrides. Keys must be molecule-ids listed in this entry's `molecules` array. |

**Invariants** (unchanged from v3):
- Every `revision` is a full 40-hex SHA.
- The pair `(source, revision)` is unique across `compounds[]`.
- Every molecule id in a compound's `molecules[]` MUST exist in the publisher-root manifest at that compound's `revision`.

---

## Publisher-root manifest (`manifest.json`)

**Schema**: [`contracts/publisher-manifest.v4.schema.json`](contracts/publisher-manifest.v4.schema.json)
**Location**: repo root of a publisher project. Filename unchanged.
**Reader**: the tool during resolution (via `spaex_publisher_fetch` after `git ls-remote` and `git fetch`).

| Field | Type | Required | Notes |
|---|---|---|---|
| `spaex_version` | string | yes | Must be `"4"`. **v3→v4 delta**: renamed from `haex_hive_version`. |
| `publisher` | string (reverse-DNS) | yes | Publisher's project identity. Unchanged. |
| `molecules` | object mapping `moleculeId → publisherMoleculeEntry` | yes | Unchanged from v3. |

### `publisherMoleculeEntry` (unchanged from v3)

| Field | Type | Required | Notes |
|---|---|---|---|
| `path` | POSIX relative path | yes | Repo-relative directory containing this molecule's `manifest.json`. |
| `version` | string | yes | Free-form version string set by the publisher. |
| `description` | string | no | Short human-readable description. |

**Invariants** (unchanged from v3):
- Every molecule id MUST begin with the `publisher` value plus `.`.
- `path` values are POSIX and repo-relative; no leading slash, no `..` traversal.

---

## Molecule manifest (`<molecule-dir>/manifest.json`)

**Schema**: [`contracts/molecule-manifest.v4.schema.json`](contracts/molecule-manifest.v4.schema.json)
**Location**: at the `path` declared by the publisher-root manifest.
**Reader**: the tool during resolution.

| Field | Type | Required | Notes |
|---|---|---|---|
| `spaex_version` | string | yes | Must be `"4"`. **v3→v4 delta**: renamed from `haex_hive_version`. |
| `id` | moleculeId | yes | Reverse-DNS id, publisher-prefixed. |
| `version` | string | yes | Free-form version string. |
| `priority` | integer | yes | Non-negative; higher = later during ordered publication. |
| `atoms` | object mapping `categoryKey → list of POSIX paths` | yes | Unchanged from v3. Each path is repo-relative under the molecule dir. |
| `defaults` | object | no | Optional per-molecule default config. |
| `config_schema` | string | no | Optional POSIX relative path to a JSON Schema describing acceptable overrides. |

### `atoms{}` category vocabulary

Categories are **open**: any string key. Publishers pick category names by convention. Common categories today:
- `constitution`: files that participate in constitution assembly (see Spec 007/008).
- `slash_commands`: files placed under `.claude/commands/` (or the equivalent for other agent CLIs).
- `agents`: agent-role files.
- `mcps`: MCP-server descriptors.

**Environment-config files** (`flake.nix`, `Dockerfile`, `devcontainer.json`, `.envrc`, `shell.nix`, etc.) can be declared under any category name a publisher chooses today, because the schema treats keys as open. Spec 014 makes **no** naming commitment here (see Clarification 2026-09-07 Q3); the multi-environment vocabulary (dev/staging/prod), consumer-side selection, and orchestration verbs are the scope of Spec 015.

**Invariants** (unchanged from v3):
- No path appears in more than one category's list within the same molecule (`atoms-category-overlap` refusal at load time).

---

## Install lock (`.spaex/install.lock`)

**Schema**: [`contracts/install-lock.v4.schema.json`](contracts/install-lock.v4.schema.json)
**Location**: at `.spaex/install.lock` under the consumer repo root (renamed from `.haex-hive/install.lock`).
**Writer**: `spaex install` (via the transactional publisher from Spec 008).

| Field | Type | Required | Notes |
|---|---|---|---|
| `spaex_version` | string | yes | Must be `"4"`. **v3→v4 delta**: renamed from `haex_hive_version`. |
| `generation_id` | string | yes | Unique per publication. Preserved from Spec 008's npm/pip-shape amendment (2026-09-03). |
| `molecules` | array of `moleculeEntry` | yes | Canonical order (lexical by molecule id). |

### `moleculeEntry` (unchanged from v3, per Spec 008 npm/pip-shape amendment)

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | moleculeId | yes | |
| `revision` | 40-hex SHA | yes | Commit SHA the molecule was fetched at. |
| `source` | canonical URL | yes | The publisher URL. |
| `paths` | array of POSIX relative paths | yes | Files this molecule contributed under participating roots. Sorted. |

**Retired fields (per Spec 008 npm/pip-shape amendment, do not reintroduce in v4)**:
- `generated_by`, `constitution`, `participating_roots`, `generation_inputs`.

---

## `v3_to_v4` transform

**Contract**: [`contracts/spaex-migrate.v3-to-v4.md`](contracts/spaex-migrate.v3-to-v4.md)
**Location in code**: `src/spaex/migrate/transform.py::v3_to_v4()`
**Signature**: `def v3_to_v4(parsed: dict, kind: str) -> dict` where `kind` ∈ `{"consumer", "publisher", "molecule", "install_lock"}`.

**Semantics**:
1. Rename `haex_hive_version: "3"` to `spaex_version: "4"` at the top level.
2. Rename `haex_hive_min_version` (consumer only) to `spaex_min_version`, applying the version-bump rule:
   - Exact `3.X.Y` becomes `4.X.Y`.
   - Lower bound `>=3.X.Y` becomes `>=4.0.0`.
   - Any other form: refuse with `unsupported-min-version-constraint`, name the offending constraint.
3. Every other field and value passes through unchanged. `atoms{}`, `molecules[]`, `compounds[]`, `paths[]`, `source`, `revision`, etc. all preserved byte-for-byte modulo JSON reserialization.

**Determinism**: Given identical `(parsed, kind)`, the transform emits identical output. No timestamps, no host state, no randomness.

**Filename-target map** (for proposal placement):
- v3 `.haex-hive.json` → v4 target `.spaex.json`. Proposal file: `.spaex.json.migrated` next to `.haex-hive.json`.
- v3 publisher `manifest.json` → v4 target `manifest.json`. Proposal file: `manifest.json.migrated` next to the source.
- v3 molecule `manifest.json` → same as publisher.
- v3 `.haex-hive/install.lock` → **not migrated** (runtime output; regenerated on next `spaex install`).

---

## Field-rename table (canonical)

| v3 field name | v4 field name | Applies to |
|---|---|---|
| `haex_hive_version` | `spaex_version` | consumer, publisher, molecule, install-lock |
| `haex_hive_min_version` | `spaex_min_version` | consumer only |

Every other structural element is unchanged.

## Filename-rename table (canonical)

| v3 filename | v4 filename |
|---|---|
| `.haex-hive.json` | `.spaex.json` |
| `.haex-hive.json.lock` | `.spaex.json.lock` |
| `.haex-hive/install.lock` | `.spaex/install.lock` |
| `.haex-hive/pending/…` | `.spaex/pending/…` |

Publisher-root `manifest.json` and per-molecule `manifest.json` filenames stay.
