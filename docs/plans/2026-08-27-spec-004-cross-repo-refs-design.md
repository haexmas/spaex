# Spec 004 — Cross-Repo References (Phase 1)

Date: 2026-08-27
Status: Landed as [Spec 004](../../specs/004-cross-repo-refs/) (all 43 tasks ticked). This document is retained as the original 2026-08-27 design capture, when it read "Brainstormed, not yet specified".
Feeds into: `specs/004-cross-repo-refs/` (to be created via `/speckit-specify`)

## Problem

The design plan's Phase 1 calls for portable cross-repo references — a way
for one haex-hive-opted-in repo to consume harness content (starting with
a constitution) from another repo, in a form that:

- Pins an immutable Git revision (Constitution Principle IV).
- Requires explicit per-project opt-in for each external source
  (Principle V).
- Resolves identically on any device, without local-path configuration
  (Principles II and III).
- Works against Git objects directly, so a full working clone of the
  external repo is not needed.

Spec 003 delivered a partial version of this for one specific role:
`.haex-hive.json`'s `constitution` block already carries a
`repository + revision + path` triple, and the repo's own constitution is
resolved from it at session start. What is missing:

- A general tool (`spec-resolve`) that turns a pinned reference into
  content, drivable from the snippet and from CLI.
- Enforcement of the per-project allowlist against arbitrary references,
  not just the one hard-coded constitution role.
- Consolidation of the duplicated allowlist location (`.specify/system.yaml`
  and `.haex-hive.json` both currently carry an
  `external_sources.allowed` block).
- A cache layout that lets multiple opted-in repos on one device share
  a single fetch of a given external repo.

## Layer separation (important for reading everything below)

This design is *deliberately narrow*. It lives on exactly one layer of
the eventual haex-hive stack:

- **Layer 1 — Reference primitive (this spec, Phase 1).** A dumb,
  untyped mechanism: given `repository + revision + path`, produce the
  file content. Knows nothing about skills, MCPs, permissions, or any
  other typed harness artifact.
- **Layer 2 — Typed harness slots (Phase 2 / Spec 006+).** Named
  categories — `skills`, `mcp_servers`, `permissions`, `instructions` —
  each of which internally *uses* Layer 1 to resolve its pointers.
  Not delivered here.
- **Layer 3 — Per-user exposed harness (Phase 2/3).** A per-device
  aggregation directory (candidate location: `~/.haex-hive/{skills,mcp,...}`)
  where compiled harness artifacts land for CLIs to pick up.
  Not delivered here.

A common failure mode during brainstorming was smuggling Layer 2 concerns
(typed slots for `skills`/`mcp_servers`) into the Layer 1 design as a
generic `refs` block. That was rejected: Spec 004 introduces no generic
`refs` block. The only live consumer of Layer 1 in Phase 1 is the
existing `constitution` slot in `.haex-hive.json`. Layer 2 slots arrive
when Phase 2's multi-tool compiler is designed, and each such slot
consumes Layer 1 internally.

## Deliverables

Spec 004 lands these, and only these:

1. **`spec-resolve` CLI tool.** Python, stdlib-only. Given a reference
   entry (from `.haex-hive.json`'s `harness_sources` array, from a
   feature-scoped `spec-ref.json`, or from an argument list), fetches
   the required Git objects into a shared cache and prints the
   resolved file content. Also handles allowlist enforcement and a
   `prefetch` subcommand for warming the cache on a fresh clone.
   Command surface v1: `resolve`, `prefetch`, and a read-only `status`
   for the staleness indicator.
2. **Unified `harness_sources` shape in `.haex-hive.json`.** The
   separate top-level `constitution` slot and the `external_sources.allowed`
   list from Spec 003 collapse into one array — `harness_sources` — whose
   entries are either concrete role-carrying pointers (the constitution
   entry is the sole live example) or permission-only scopes (for external
   repos trusted broadly). See "Data model changes" below.
3. **Allowlist enforcement.** `spec-resolve` refuses to resolve any
   reference not permitted by an entry in `harness_sources`. Role-carrying
   entries permit their own reference implicitly. See "Allowlist
   granularity" below.
4. **JSON Schema at `.specify/schemas/haex-hive.schema.json`.** Canonical
   description of `.haex-hive.json`'s shape, including the `role` enum
   (Phase 1: exactly one value, `constitution`). `spec-resolve`
   validates against it at load-time; editors that pick up JSON schema
   references get autocomplete and inline error hints. See "JSON Schema"
   below.
5. **Consolidation cleanup.** `.specify/system.yaml` is removed —
   its content lives in `.haex-hive.json.harness_sources` after the
   unification. The name change from `external_sources` to
   `harness_sources` (see "Naming" below) is part of the same move.
6. **Constitution PATCH-bump (v1.1.0 → v1.1.1).** Principle V's wording
   is rewritten to cite `.haex-hive.json`'s `harness_sources` array
   rather than `.specify/system.yaml`'s `external_sources.allowed` list.
   Purely a wording refresh; no principle removed, added, or relaxed.
   Governed as PATCH per the constitution's version-bump rules.
7. **Global snippet extension (from Spec 003).** The session-start
   snippet gains one additional step: after reading `.haex-hive.json`,
   verify that all pinned references are resolvable from the local cache
   (or trigger `spec-resolve prefetch` if not). The snippet also prints
   a compact staleness indicator — `"3 refs, last update-check: never /
   YYYY-MM-DD"` — drawn from cache metadata only, no network call.
8. **Documentation.** `README.md` or a new `docs/spec-resolve.md`
   covers the tool's command surface, cache location, and how a
   consuming repo wires a real external source (e.g. secana-specs) into
   its `harness_sources`. Wiring an external source into this repo is
   deliberately NOT done as part of Spec 004 (see "Non-goals").

## Data model changes

### `.haex-hive.json` shape (after Spec 004)

```json
{
  "haex_hive_version": "1",
  "identity": "local:haex-hive",
  "harness_sources": [
    {
      "role": "constitution",
      "repository": "self",
      "revision": "<full-sha>",
      "path": ".specify/memory/constitution.md"
    }
  ],
  "groups": [],
  "active_feature": null
}
```

Changes from the current file:
- The top-level `constitution` slot is removed. Its content moves into
  `harness_sources` as a role-carrying entry (`role: "constitution"`).
- `external_sources.allowed` (both nested and array-of-strings variants
  seen historically) is replaced by the flat `harness_sources` array.
  The nested `.allowed` layer was redundant — every entry in the list
  is permitted by definition.
- `identity_note` stays as-is on entries that carry it; nothing else in
  the top-level schema changes.
- **No generic `refs` block. Deliberate.** All harness references live
  in `harness_sources`, typed by their `role` (if any).

### Entry semantics — two shapes

**A) Role-carrying entry (concrete pointer + self-permission):**
```json
{
  "role": "constitution",
  "repository": "self",
  "revision": "<full-sha>",
  "path": ".specify/memory/constitution.md"
}
```
- Loaded automatically at session start by the snippet.
- Its own reference is implicitly permitted; no separate permission
  entry needed.
- MUST carry `repository + revision + path` (single path). MUST NOT
  carry `paths` (plural).
- Phase 1 defines exactly one valid `role`: `constitution`. Extending
  the enum is a Phase 2+ concern.

**B) Permission-only entry (trust scope):**
```json
{
  "repository": "gitlab.com/itemis/.../secana-specs",
  "revision": "<optional-sha>",
  "paths": ["<optional>", "<path-allowlist>"]
}
```
- Not loaded automatically — no `role`.
- Permits any pinned reference (from a `spec-ref.json`) that falls
  within the scope: same `repository`, matching `revision` if
  specified, path in `paths` if specified.
- MUST NOT carry `role` (that would flip it to shape A).
- MUST NOT carry `path` (single) — use `paths` (plural) for the
  permission list.

### Feature-scoped references (documented escape hatch)

Unchanged from earlier: a feature that needs to pin external content
for its own work MAY drop a `spec-ref.json` at
`specs/<feature>/spec-ref.json` with a `{name: {repository, revision, path}}`
shape. `spec-resolve` discovers these when invoked with the feature
directory. Spec 004 ships no such file itself.

### The retired file

`.specify/system.yaml` is deleted. Any prior reader is migrated to read
`.haex-hive.json.harness_sources` instead. `.specify/` remains
otherwise untouched (its `memory/`, `extensions/`, `templates/`, etc.
are spec-kit's territory).

### Feature-scoped references (documented escape hatch)

A feature that needs to pin external content for its own work MAY drop
a `spec-ref.json` file at `specs/<feature>/spec-ref.json`. Shape:

```json
{
  "some-name": {
    "repository": "...",
    "revision": "<full-sha>",
    "path": "..."
  }
}
```

`spec-resolve` discovers these when invoked with the feature directory.
Spec 004 itself does NOT ship any feature-scoped `spec-ref.json` — the
tool is validated against synthetic Git fixtures and one manual smoke
test (see "Testing").

### The retired file

`.specify/system.yaml` is deleted. Any prior reader is migrated to read
`.haex-hive.json.harness_sources.allowed` instead. `.specify/` remains
otherwise untouched (its `memory/`, `extensions/`, `templates/`, etc.
are spec-kit's territory).

## Allowlist granularity

Four entry shapes are permitted in `harness_sources`. Three are
permission-only (shape B above); one is role-carrying (shape A above)
and self-permitting.

**Shape 1 — Permission-only, repository-only (broadest):**
```json
{ "repository": "gitlab.com/itemis/solutions/pltf/secana-specs" }
```
Permits any pinned reference into this repo, regardless of revision or
path. Convenient when you decide to trust a repo as a whole and pull
multiple documents from it over time.

**Shape 2 — Permission-only, repository + revision:**
```json
{
  "repository": "gitlab.com/itemis/solutions/pltf/secana-specs",
  "revision": "7ae4c218e140..."
}
```
Permits any pinned reference at exactly this SHA. Any other SHA in the
same repo is refused. Bumping the pinned SHA is a review-gated commit
to `.haex-hive.json`.

**Shape 3 — Permission-only, repository + revision + paths:**
```json
{
  "repository": "gitlab.com/itemis/solutions/pltf/secana-specs",
  "revision": "7ae4c218e140...",
  "paths": [".specify/memory/constitution.md", "skills/foo.md"]
}
```
Permits references at exactly this SHA AND with a path in the listed
set. Strictest permission scope — a new file to consume requires
updating this entry.

**Shape 4 — Role-carrying (concrete pointer, self-permitting):**
```json
{
  "role": "constitution",
  "repository": "gitlab.com/itemis/solutions/pltf/secana-specs",
  "revision": "7ae4c218e140...",
  "path": ".specify/memory/constitution.md"
}
```
A pointer for a specific named role (Phase 1: only `constitution`).
Automatically loaded by the snippet at session start. Its own reference
is implicitly permitted; no separate Shape 1/2/3 entry is needed to
authorize it. Because it names a full `repository + revision + path`
triple, it is by construction the strictest possible permission entry.

**No branch field on any shape.** Principle IV forbids branch or HEAD
references in anything a spec, plan, or task consumes. The allowlist
does not weaken that: every `spec-ref` still names a full SHA
regardless of which shape permits it.

**Enforcement rule:** `spec-resolve` iterates over `harness_sources`
for the requested `repository`; the first entry (of any shape) whose
scope permits the reference lets it through. If nothing matches,
resolution refuses with a specific error message naming the offending
reference and the missing/mismatching entry.

## JSON Schema

**Location:** `.specify/schemas/haex-hive.schema.json` in this repo.

**Purpose:** single canonical vocabulary source for `.haex-hive.json`'s
shape. Editors that map `.haex-hive.json` to this schema (JetBrains IDE
mappings, VSCode's `json.schemas` setting, or an inline `$schema` field
in `.haex-hive.json`) get autocomplete on field names and role values,
plus inline errors on typos and shape violations. `spec-resolve`
validates loaded config against it at every invocation; unknown roles,
malformed entries, or forbidden field combinations fail loudly with a
specific message.

**Draft shape** (illustrative, will be finalized in Spec 004's spec.md):

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": ".specify/schemas/haex-hive.schema.json",
  "title": "haex-hive project marker",
  "type": "object",
  "required": ["haex_hive_version", "identity", "harness_sources"],
  "properties": {
    "haex_hive_version": { "const": "1" },
    "identity": { "type": "string", "minLength": 1 },
    "identity_note": { "type": "string" },
    "harness_sources": {
      "type": "array",
      "items": { "$ref": "#/definitions/harness_source_entry" }
    },
    "groups": { "type": "array" },
    "active_feature": { "type": ["string", "null"] }
  },
  "definitions": {
    "harness_source_entry": {
      "type": "object",
      "required": ["repository"],
      "properties": {
        "role": { "enum": ["constitution"] },
        "repository": { "type": "string", "minLength": 1 },
        "revision": {
          "type": "string",
          "pattern": "^(self|[0-9a-f]{7,40})$"
        },
        "path": { "type": "string" },
        "paths": {
          "type": "array",
          "items": { "type": "string" },
          "minItems": 1
        }
      },
      "allOf": [
        {
          "if": { "required": ["role"] },
          "then": {
            "required": ["revision", "path"],
            "not": { "required": ["paths"] }
          }
        },
        {
          "if": {
            "not": { "required": ["role"] }
          },
          "then": {
            "not": { "required": ["path"] }
          }
        }
      ]
    }
  }
}
```

**Role enum evolution:**
- Phase 1 (Spec 004): `["constitution"]` — exactly one member.
- Phase 2+: new role names added as Phase-2 spec introduces typed
  single-file slots. Additions are PATCH-level for the constitution
  (they widen the enum without removing values).

**Validation timing:**
- `spec-resolve` validates on every invocation before doing any work.
- Snippet Step 8 (see below) surfaces validation errors to the operator
  before harness work starts, so a broken `.haex-hive.json` is caught
  at session start, not partway through a task.

## `spec-resolve` tool design

**Language:** Python 3, stdlib only. `json` for config parsing, `subprocess`
for calling `git`, `hashlib` for cache directory naming, `pathlib` for path
handling, `argparse` for CLI. No third-party dependencies. No YAML
support (removed with the `system.yaml` consolidation).

**Validation:** The tool performs direct, targeted checks matching the
JSON Schema — required keys, `role` value in the known set, role/shape
constraints (see "Entry semantics"), SHA pattern. No general JSON Schema
engine is embedded (that would need a third-party lib). The schema file
is authoritative for editors and documentation; the tool's checks are
kept in sync with it as part of any change that touches either. Testing
covers "schema and tool agree" for the known cases.

**Distribution:** committed at `.specify/scripts/spec-resolve` (executable,
`#!/usr/bin/env python3` shebang). Invoked by absolute or relative path
from the snippet; consumers running it manually put its containing dir
on PATH or invoke it directly. A Nix flake wrapper is a plausible Phase 3
add-on; not required in Phase 1.

**Subcommands (v1):**

- `spec-resolve resolve <ref-source>` — reads a reference (from stdin,
  from a `spec-ref.json`, or from an inline flag set), verifies against
  the caller's allowlist, resolves through the cache, prints the file
  content to stdout. Exit 0 on success, non-zero with a specific error
  code on refusal (allowlist mismatch), missing cache and offline
  network, or malformed input.
- `spec-resolve prefetch` — walks all pinned references discoverable
  from the current repo (`.haex-hive.json` + any `specs/*/spec-ref.json`),
  populates the shared cache for any missing objects, exits when
  everything is cached or with a clear error listing what could not be
  fetched.
- `spec-resolve status` — prints a compact summary suitable for the
  session-start snippet: number of references, timestamp of last cache
  update per source, and offline-safeness (are all references resolvable
  from cache right now).

**Explicitly NOT in v1:** `check-updates`, `bump`, any interactive
update workflow. Those live in Spec 005.

**Object-fetch mechanism:** for each unique `repository`, `spec-resolve`
maintains a bare-clone-like directory in the shared cache and uses
`git fetch <repo-url> <sha>` to pull missing objects into it (falling
back to a shallow filter if the server does not accept the sha refspec).
Content extraction is `git show <sha>:<path>`. This matches the
design-plan wording.

## Cache design

**Location:** `~/.cache/haex-hive/repos/<repo-hash>/` on Linux and macOS
(XDG-cache-home aware; falls back to `~/.cache/` on Linux, honors
`$XDG_CACHE_HOME` if set, uses `~/Library/Caches/` on macOS).

**Content:** each `<repo-hash>` directory is a bare Git object store
for one external repository. Populated on demand by `spec-resolve`. Safe
to delete at any time — deletion just means the next `spec-resolve
resolve` needs network.

**Deduplication:** [Certain] Multiple opted-in repos on the same device
that reference the same external repo share one cache entry. The
`<repo-hash>` naming is stable across repos so this happens automatically.

**Layer 3 (`~/.haex-hive/...`)** is explicitly not created by Spec 004.
Any per-user exposure of compiled harness artifacts is Phase 2/3.

## Snippet extension (from Spec 003)

The current global snippet's 7 steps become 8. Between the current
"read repo instructions" step and the "run conflict pass" step, insert:

> **Step N — Verify pinned references are resolvable.** Read
> `.haex-hive.json`'s `constitution` block and any `spec-ref.json`
> files under `specs/*/`. Run `spec-resolve status` and confirm every
> reference is resolvable from the local cache. If any is missing, run
> `spec-resolve prefetch` before proceeding; if that fails (offline and
> no cache), refuse to start harness work and surface the failure to
> the operator.

The snippet also prints the compact staleness line
(`"3 refs, last update-check: 2026-08-27 (0 days ago)"`) as part of
its start-of-session summary. The line is drawn from cache metadata
only — no network call at session start.

## Naming

The field currently named `external_sources` in `.haex-hive.json` and in
`.specify/system.yaml` is renamed to **`harness_sources`**. Rationale:

- `external_sources` is unspecific — anything could be a "source".
- `external_specs` was considered and rejected because "spec" is
  already the local name for feature specs (`specs/*/spec.md`); a
  same-word overload in `.haex-hive.json` would create a permanent
  low-grade confusion.
- `harness_sources` names what actually goes there: external Git
  repositories vouched-for as sources of *harness content* —
  constitutions today, skills/MCPs/instructions when Phase 2 lands.

The rename is captured in the constitution PATCH-bump so no dangling
citation remains.

## Testing

**Unit-scale (in this repo):**
- Synthetic Git fixtures under `tests/fixtures/`: small local repos
  built with `git init` + a couple of commits, used to drive
  `spec-resolve` end-to-end without network. Covers: happy-path
  resolve, allowlist refusal (all four shapes including role-carrying),
  role-entry auto-permission, SHA mismatch, path mismatch, malformed
  reference, and cache-miss+offline.
- **Schema-vs-tool agreement tests:** for a curated set of valid and
  invalid `.haex-hive.json` samples, both the schema (via any
  off-the-shelf validator invoked in the test harness only) and the
  tool's built-in checks agree on accept/reject. Catches drift between
  the two.
- Assertion style: shell-driven, invoking the tool and checking exit
  codes + stdout, mirroring how the snippet uses it. No pytest-style
  framework — YAGNI for a stdlib-only Python tool at this stage.

**Manual smoke test:**
- One documented smoke run against a real external repo (secana-specs)
  using a temporary allowlist entry in a *scratch checkout*, not
  committed to haex-hive's own `.haex-hive.json`. Purpose: prove that
  `git fetch <repo> <sha>` and `git show` work as expected against a
  real remote. Documented in the spec's quickstart; the temp scratch
  checkout is thrown away afterwards.

**Cross-OS acceptance:** deferred to when a real macOS satellite
exists. Spec 004 validates on Linux only. A written cross-OS test plan
is included so the eventual macOS validation is a well-defined follow-up,
not a fresh design exercise. Rationale: same as the design plan's
deferral of WSL2 validation — no real satellite exists yet, so
synthetic macOS validation would carry no signal.

## Non-goals

Explicitly out of scope for Spec 004:

- Any actual external harness source added to `haex-hive`'s own
  `harness_sources.allowed`. The mechanism is validated with fixtures
  and a scratch smoke test; wiring a real external source into this
  repo would violate the "no work/personal mixing" spirit of Principle
  V and gains nothing for the tool's correctness.
- The `check-updates` and `bump` commands. Those live in Spec 005.
- Notification / periodic-ask UX (see "Notes for Spec 005" below).
- Any per-user aggregation of compiled harness artifacts
  (`~/.haex-hive/skills/`, etc.). Phase 2/3 territory.
- Windows-native / WSL2 validation. Deferred with the same rationale
  as macOS.
- Any typed slots in `.haex-hive.json` (`skills`, `mcp_servers`, ...)
  or a generic `refs` block. Phase 2+.

## Notes for Spec 005 (captured so they don't get lost)

- The update-detection workflow will most likely be a hybrid of the
  Option-B (staleness indicator + explicit `check-updates` / `bump`)
  and the "LLM periodically asks the operator whether to run the check"
  pattern that surfaced during brainstorming. The periodic-ask pattern
  avoids both the passivity of pure Option B and the boot-time cost of
  Option C (async check on session start).
- The `bump` command produces a proposed commit diff against
  `.haex-hive.json` (and any `spec-ref.json` files) with the updated
  SHAs. Per Principle VI it never auto-merges; the operator reviews
  and commits.
- Cache eviction / rotation policy is deferrable — the cache is
  blow-away-safe, and until it grows noticeably there is nothing to
  design.

## Open questions (deferrable, not blocking Spec 004)

- Exact filename convention for feature-scoped references
  (`spec-ref.json` vs. `refs.json` vs. `harness-refs.json`).
  Recommendation: `spec-ref.json` singular, matching the design plan's
  wording. Not urgent to lock — no feature spec other than 004 has a
  live external ref yet.
- How error output from `spec-resolve` is surfaced to the operator when
  invoked from the snippet — plain stderr is enough for v1, but a
  structured JSON error mode might help Phase 2's compiler.
- Where the smoke-test scratch checkout lives (in a temp dir under the
  scratchpad, or under `~/tmp/haex-hive-smoke/`). Cosmetic.

## Acceptance criteria (draft, will be sharpened in Spec 004's spec.md)

- `.specify/system.yaml` is removed; a `git grep external_sources`
  returns matches only in historical files (ADRs, this design doc,
  spec 003 artifacts).
- `.haex-hive.json.harness_sources` is a flat array; the top-level
  `constitution` slot no longer exists; the constitution's own
  reference has migrated in as a `role: "constitution"` entry with
  no observable behavior change.
- `.specify/schemas/haex-hive.schema.json` exists and validates the
  new `.haex-hive.json` shape. IDE mapping (VSCode `json.schemas` or
  JetBrains config, whichever this operator uses) is documented in
  `docs/spec-resolve.md`.
- `spec-resolve resolve` produces byte-identical output for the
  constitution reference before and after the change (regression check
  for the one live consumer).
- With `harness_sources` containing only the `role: "constitution"`
  entry pointing at `self`, `spec-resolve` refuses to resolve any
  non-`self` reference with a clear message.
- A fresh clone of this repo, run through the updated snippet
  end-to-end, prefetches all references (only `self` here) and starts
  harness work without a network call after the initial clone.
- Schema and tool agree on the curated valid/invalid sample set.
- Constitution version stamp is v1.1.1, ratified 2026-08-26,
  last-amended the date Spec 004 lands.
