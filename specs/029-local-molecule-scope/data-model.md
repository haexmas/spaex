# Data Model: Local (Per-Developer) Molecule Scope

## Scope (enum)

`project` | `local`. Default `project` everywhere. Carried on every report record (status, trace, install output) and passed to hooks as `SPAEX_SCOPE`.

## LocalManifest (`.spaex/local/manifest.json`)

| Field | Type | Rules |
|---|---|---|
| `spaex_version` | `"4"` | Required, constant. |
| `compounds` | `CompoundEntry[]` | Required (may be empty). Same shape and validation as the project manifest's `compounds[]`: canonical `source`, 40-hex `revision`, unique non-empty `molecules`, optional `config` keyed by adopted molecule ids. |

Validation (FR-017): schema `local-manifest.v1.schema.json`, `additionalProperties: false`. Any failure stops install with `local-manifest-invalid` naming the file.

Lifecycle: created by the first `spaex add --local`; compounds that become empty are dropped by `spaex remove --local`; when no compound remains, the whole `.spaex/local/` directory is removed by the next publish.

## Local install record (`.spaex/local/install.lock`)

Same `InstallLock` model and `install-lock.v4` schema as `.spaex/install.lock`.
- `generation_id` is allocated independently from the local seed (`allocate_generation_id` over the local records), so a local-only change never rewrites the committed project `install.lock` (SC-001, SC-002).
- `molecules[].paths` lists every path local scope wrote, including `.spaex/local/constitution.md`, `.spaex/local/generated/nix-packages.json` and repo-root exclusive files.
- `content_hashes` covers local repo-root exclusive files, as for project scope.
- `molecules[].speckit` holds the local Spec Kit record when local scope owns the Spec Kit policy.

## Resolved scope set (in-memory, per install)

| Field | Meaning |
|---|---|
| `project` | Resolved molecules from `.spaex/manifest.json` (unchanged). |
| `local` | Resolved molecules from the overlay, minus shadowed ids. |
| `shadowed` | Molecule ids present in both; reported, never installed from local. |

Invariants checked before any write (FR-006, FR-010, FR-013):
1. No local exclusive destination equals a project-owned path.
2. No local exclusive destination is tracked by git.
3. At most one scope declares `speckit`; a local declaration alongside a project one is refused.

## Local behavior document (`.spaex/local/constitution.md`)

Composed from `.spaex/local/constitution.d/<molecule>/*.md` only, with the standard `spaex-composed` hash header, followed by the fixed preamble:

> These rules apply only to this checkout and only for this developer. They supplement `.spaex/constitution.md`; where they conflict, the project constitution prevails.

## Exclusion block (`$(git rev-parse --git-path info/exclude)`)

```
# spaex-local:start worktree="<git-dir basename>"
/<repo-relative path>
...
# spaex-local:end worktree="<git-dir basename>"
```

- Exactly one block per worktree key; entries sorted, de-duplicated, anchored with a leading `/`.
- Contents = every path in the local lock's `molecules[].paths` outside `.spaex/`: exclusive root files plus files a local hook or the local Spec Kit run created (research R10, R11).
- Block is removed when empty. Text outside spaex blocks is never modified. A malformed block (start without end) refuses install before any write, like malformed bootstrap markers.

## `.spaex/local/.gitignore`

Single line `*`. Written on every publish that has a non-empty local scope; staged like every other local file.

## State transitions

```
no overlay ──add --local──▶ overlay with 1+ compounds ──install──▶ local outputs + lock + exclusion block
     ▲                                                                    │
     └────────────── remove --local (last molecule) ◀─────────────────────┘
                     (outputs deleted, block removed, .spaex/local/ gone)
```
