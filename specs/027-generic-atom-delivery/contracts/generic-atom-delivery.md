# Contract: Generic Atom-Category Delivery and Removal

Observable behavior of `spaex install` / `spaex remove` for molecules that declare atoms outside `behavior`/`skill`/`skills`. No new CLI flags or subcommands — this extends the existing commands' effects.

## `spaex install`

**Given** an adopted molecule declares one or more paths under an *exclusive* category (any key other than `behavior`, `skill`, `skills`, `nix_packages`):

- Each declared path is written at that repo-root-relative location, content identical byte-for-byte to the molecule source, via an individually atomic write (temp file + rename — never a torn/partial file), and only *after* the destination's canonical path is confirmed to resolve inside the repo root through any symlinked ancestor (FR-010).
- If the path is already occupied by a file install.lock does not currently record as spaex-owned, it is overwritten (FR-006; ADR 0026).
- If another *currently adopted* molecule declares the same path under an exclusive category, the install is refused (diagnostic key `exclusive-atom-path-collision`, FR-003) before any file is written for either molecule. This is new cross-molecule enforcement — `atoms-category-overlap` only ever catches one molecule's own manifest declaring a path twice — there is no pre-existing cross-molecule check to extend, since `behavior` atoms never have their own destination path to collide on.
- All exclusive-category root-file writes for a generation complete *before* that generation's `.spaex/` directory-swap transaction is staged and published (FR-011) — they are outside `.spaex/` and cannot participate in that swap. On success, `install.lock` records `{path, owning molecule id}` for each such file as part of that swap.

**Given** one or more adopted molecules declare a `nix_packages` fragment:

- `spaex install` reads every active molecule's fragment, composes them per research.md §2 (sorted, deduplicated union), and writes `.spaex/generated/nix-packages.json`.
- Multiple molecules declaring `nix_packages` is not a conflict; none are refused on this account.
- If any active molecule's fragment is not a *non-empty* JSON array of non-empty strings, the whole install is refused (FR-009, diagnostic key `nix-packages-fragment-invalid`) naming that molecule id; no composed file is written, and no other molecule's contribution is silently composed without it.
- The written file's content is *only* the sorted, deduplicated JSON array of package identifiers (e.g. `["cargo", "python312", "rustc"]`) — no wrapping object, no `contributing_molecule_ids` field. That file lives inside `.spaex/generated/`, so it publishes through the existing `.spaex/` swap unchanged (FR-011), unlike exclusive-category root files.
- On success, `install.lock` records `.spaex/generated/nix-packages.json` once, with every contributing molecule id listed as an owner of that path (the one case where a path has more than one owning molecule) — that ownership list lives in `install.lock` only, never in the generated file itself.

**Idempotency** (both cases): re-running `spaex install` with no manifest or molecule-content change produces byte-identical files and an unchanged `install.lock` (generation id excepted).

## `spaex remove <molecule-id>`

**Given** the retracted molecule contributed exclusive-category files:

- Every file install.lock attributes solely to that molecule is deleted individually, *before* the updated (smaller) `install.lock` generation is staged and published (FR-011) — so a deletion failure leaves the previous generation's `install.lock` still claiming that file, and a retry attempts deletion again. A file whose on-disk content hash no longer matches what install.lock last recorded is the one exception (FR-007): it is left in place, a warning is emitted, and the path is dropped from install.lock's next-generation record for that molecule regardless.

**Given** the retracted molecule contributed a `nix_packages` fragment and at least one other adopted molecule still contributes one:

- `.spaex/generated/nix-packages.json` is regenerated (not deleted) to reflect only the remaining contributors' merged packages.

**Given** the retracted molecule was the *last* remaining `nix_packages` contributor:

- `.spaex/generated/nix-packages.json` is deleted entirely.

## Non-effects (explicitly out of contract)

- Neither command invokes `nix-collect-garbage` or any other Nix store operation. Package removal from a generated file changes what a future `nix develop`/`direnv reload` will build, not what is currently present in the Nix store (spec.md Non-Goals).
- Neither command distinguishes "same tool, different version" package identifiers; composition is exact-string set logic only (spec.md Edge Cases).
