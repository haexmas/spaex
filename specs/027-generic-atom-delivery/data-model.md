# Data Model: Generic Atom-Category Delivery and Removal

## GenericAtomCategory *(new, molecule-manifest concept — no new field)*

A molecule's `atoms` map (existing v4 schema) already permits any category key. This feature classifies each key at read time, not at declaration time:

| Category key | Kind | Materialization |
|---|---|---|
| `behavior` | *(existing, unchanged)* | Constitution-fragment pipeline (Spec 023/026), untouched by this feature. |
| `skill`, `skills` | *(existing, reserved)* | Rejected by schema per the `not: {enum: [...]}` constraint already in place; untouched. |
| `nix_packages` | **Composable** *(new)* | Every adopted molecule's package-identifier list is merged into one generated file (see ComposedFile below). |
| anything else | **Exclusive** *(new, generalized)* | Each declared path is materialized verbatim, one owning molecule per path. |

**Validation rules**: A molecule declaring `nix_packages` MUST list exactly one file (the fragment file) under that category; the fragment file's content MUST be a JSON array of non-empty strings (package identifiers), validated at resolve time. A molecule declaring any exclusive category path that another currently-adopted molecule also declares (for the same destination path) fails install with the existing cross-category-overlap-refused diagnostic, unchanged in shape from today's `behavior`-vs-`behavior` case.

## DeliveredFile *(new, persisted via install.lock)*

A single file materialized verbatim from one molecule's exclusive-category declaration.

| Field | Type | Notes |
|---|---|---|
| `path` | `str` | Repo-root-relative POSIX path. For exclusive-category entries this MAY now be a bare filename (`flake.nix`) with no leading dot-segment — see research.md §5 and ADR 0026. Every other category's paths keep the existing dot-segment-required pattern. |
| `owning_molecule_id` | `str` | Reverse-DNS molecule id, recorded the same way `behavior`-atom paths are attributed to their contributing molecule today. |
| `content_hash` | `str` (`sha256:...`) | Recorded so `spaex remove` can detect operator modification since install (FR-007) without re-reading and diffing full file content on every run. |

**State transitions**: created on first `spaex install` after adoption → left unchanged on a no-op reinstall (FR-005) → deleted on `spaex remove` of its owning molecule, unless `content_hash` no longer matches the on-disk file (FR-007: warn, leave in place, drop from install.lock's next-generation path list without touching the file).

## PackageFragment *(new, process-internal — not separately persisted)*

One molecule's contribution toward the composable `nix_packages` category, read fresh from the pinned molecule cache on every `spaex install`/`spaex remove`, exactly as `behavior` fragments are read today.

| Field | Type | Notes |
|---|---|---|
| `molecule_id` | `str` | Reverse-DNS id of the contributing molecule. |
| `packages` | `tuple[str, ...]` | Declared package identifiers, in the molecule's own declared order (order is discarded at composition time — see ComposedFile). |

**Validation rules**: Non-empty strings only; duplicate identifiers *within* one molecule's own fragment are deduplicated before composition (a molecule listing the same package twice is not a cross-molecule conflict). A fragment that is not a JSON array of non-empty strings aborts composition for the *entire* generation (FR-009) — refused, not skipped; no partial `ComposedFile` is written while any adopted molecule's fragment fails this check.

## ComposedFile *(new, persisted at `.spaex/generated/nix-packages.json`)*

The generated result of merging every currently-adopted molecule's `PackageFragment`.

| Field | Type | Notes |
|---|---|---|
| `packages` | `list[str]` | Sorted, deduplicated (exact string match) union of every active `PackageFragment.packages`, per research.md §2. Pure function of the *set* of currently-adopted contributing molecules — independent of adoption order or prior generations. |
| `contributing_molecule_ids` | `list[str]` | Sorted molecule ids that contributed at least one package to this generation, recorded in install.lock as this path's owners (plural — the one case where a `DeliveredFile`-like entry has more than one owning molecule). |

**State transitions**: created on first `spaex install` where any adopted molecule declares `nix_packages` → regenerated (not touched-in-place) on every subsequent install/remove where the active contributor set changes → regenerated with one fewer contributor's packages when `spaex remove` retracts one contributor while others remain (FR-006b) → deleted entirely once `contributing_molecule_ids` would become empty.

## InstallLock extension *(existing schema, extended)*

`install-lock.v4.schema.json`'s `moleculeEntry.paths` pattern gains an `anyOf` alternative accepting a bare repo-root-relative filename for exclusive-category `DeliveredFile` entries (research.md §5). `ComposedFile`'s path (`.spaex/generated/nix-packages.json`) already satisfies the existing dot-segment-required pattern unchanged and is listed under every one of its `contributing_molecule_ids`' entries — the existing schema already allows one path to appear in multiple molecules' `paths` arrays (no schema change needed for shared ownership itself, only for the bare-filename case).
