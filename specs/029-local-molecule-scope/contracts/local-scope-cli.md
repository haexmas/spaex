# Contract: Local-Scope CLI Surface

## `spaex add [--local] <source-url> <molecule-ids>`

- Without `--local`: unchanged.
- With `--local`: mutates `.spaex/local/manifest.json` (created when missing), then runs install. The committed `.spaex/manifest.json` is never written.
- Refusals (nothing written, manifest restored):

| Condition | Error key | Exit code |
|---|---|---|
| id is pinned in project scope | `local-adoption-shadowed` | `VALIDATION_REFUSE` |
| molecule declares `speckit` and project scope already does | `speckit-declaration-conflict` (existing) | existing |
| local exclusive destination is project-owned or tracked by git | `local-path-conflict` | `VALIDATION_REFUSE` |

- A hook-bearing molecule prints: `warning: <id> runs an install hook; files it writes on its own are not excluded from git`.

## `spaex remove [--local] <molecule-ids>`

- With `--local`: requires every id to be present in the overlay (`unknown-molecule-id`, existing key, with a hint naming `.spaex/local/manifest.json`), removes them, reinstalls. Files only those molecules wrote are deleted; their exclusion entries are dropped.
- Without `--local`: unchanged. An id adopted only locally is reported as not adopted in project scope, with a hint to use `--local`.

## `spaex install`

- Applies project then local scope in one generation.
- Additional output lines:
  - `local: <n> molecule(s) installed` when local scope is non-empty.
  - `shadowed: <id> (adopted in project scope; local entry ignored, run 'spaex remove --local <id>')` per shadowed id.
  - Bootstrap hint when a local behavior document exists and an installed runtime block is older than version 3.
- New refusals: `local-manifest-invalid`, `local-path-conflict`, malformed exclusion block (`local-exclude-malformed`).

## `spaex status [--format text|json]`

- Text: each molecule line gains ` [local]` when local; shadowed entries are listed under `Shadowed:`.
- JSON: `format_version: 2`; each molecule object gains `"scope": "project" | "local"`; top-level `"shadowed": [ids]`; drift findings carry `scope`.

## `spaex trace <path> [--format text|json]`

- Owners come from both locks. Text output appends ` (local)` to local owners. JSON owner objects gain `"scope"`; `format_version: 2`.

## `spaex constitution show`

- Prints `.spaex/constitution.md` as today, then, when `.spaex/local/constitution.md` exists, a separator line `## Local (this checkout only)` and the local document.

## Hook environment

- `SPAEX_SCOPE=project|local` is set for every install hook invocation.
