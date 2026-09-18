# Data Model: Generic Atom-Category Delivery and Removal

## GenericAtomCategory *(new, molecule-manifest concept — no new field)*

A molecule's `atoms` map (existing v4 schema) already permits any category key. This feature classifies each key at read time, not at declaration time:

| Category key | Kind | Materialization |
|---|---|---|
| `behavior` | *(existing, unchanged)* | Constitution-fragment pipeline (Spec 023/026), untouched by this feature. |
| `constitution` | *(existing, unchanged)* | The pre-Spec-023 legacy category: file(s) joined verbatim into `.spaex/constitution.md` by `spaex.constitution.resolve`/`publish`'s own, separate publication path. Not a Spec 027 generic atom, despite superficially having "just a category key and declared paths" — untouched by this feature. |
| `skill`, `skills` | *(existing, reserved)* | Rejected by schema per the `not: {enum: [...]}` constraint already in place; untouched. |
| `nix_packages` | **Composable** *(new)* | Every adopted molecule's package-identifier list is merged into one generated file (see ComposedFile below). |
| anything else | **Exclusive** *(new, generalized)* | Each declared path is materialized verbatim, one owning molecule per path. |

**Validation rules**: A molecule declaring `nix_packages` MUST list exactly one file (the fragment file) under that category; the fragment file's content MUST be a *non-empty* JSON array of non-empty strings (package identifiers), validated at resolve time — see PackageFragment below for why empty arrays are rejected rather than treated as a no-op contribution. A molecule declaring any exclusive category path that another currently-adopted molecule also declares (for the same destination path) fails install under the new `exclusive-atom-path-collision` diagnostic (FR-003) — this is new cross-molecule enforcement, not a reuse of the existing `atoms-category-overlap` key, which only ever covered one molecule's own manifest declaring a path twice (`behavior` atoms never have their own destination path to collide on, so no cross-molecule case existed before this feature).

## DeliveredFile *(new, persisted via install.lock)*

A single file materialized verbatim from one molecule's exclusive-category declaration.

| Field | Type | Notes |
|---|---|---|
| `path` | `str` | Repo-root-relative POSIX path. For exclusive-category entries this MAY now be a bare filename (`flake.nix`) with no leading dot-segment — see research.md §5 and ADR 0026. Every other category's paths keep the existing dot-segment-required pattern. |
| `owning_molecule_id` | `str` | Reverse-DNS molecule id, recorded the same way `behavior`-atom paths are attributed to their contributing molecule today. |
| `content_hash` | `str` (`sha256:...`) | Recorded so `spaex remove` can detect operator modification since install (FR-007) without re-reading and diffing full file content on every run. |

**State transitions**: created on first `spaex install` after adoption → left unchanged on a no-op reinstall (FR-005) → deleted on `spaex remove` of its owning molecule, unless `content_hash` no longer matches the on-disk file (FR-007: warn, leave in place, drop from install.lock's next-generation path list without touching the file).

**Path containment**: before every write, delete, or overwrite, the destination's canonical path (resolved through any symlinked ancestor directory) MUST be confirmed to fall inside the consumer repository's canonical root (FR-010) — a lexically repo-relative, `..`-free path string is not sufficient on its own, since an ancestor directory could itself be a symlink pointing outside the repo.

**Publication ordering**: because a `DeliveredFile` lives outside `.spaex/`, it cannot publish through the existing `.spaex/` directory-swap transaction (`src/spaex/io/transaction.py`'s `publish_generation`, scoped to exactly one `live` root directory). All `DeliveredFile` writes for a generation complete individually (each write atomic in isolation, via temp-file-plus-rename — never a torn/partial file) *before* that generation's `.spaex/` swap is staged and published; all `DeliveredFile` deletions for a `spaex remove` complete individually *before* the updated `install.lock` generation is published (FR-011). See research.md §6.

## PackageFragment *(new, process-internal — not separately persisted)*

One molecule's contribution toward the composable `nix_packages` category, read fresh from the pinned molecule cache on every `spaex install`/`spaex remove`, exactly as `behavior` fragments are read today.

| Field | Type | Notes |
|---|---|---|
| `molecule_id` | `str` | Reverse-DNS id of the contributing molecule. |
| `packages` | `tuple[str, ...]` | Declared package identifiers, in the molecule's own declared order (order is discarded at composition time — see ComposedFile). |

**Validation rules**: Non-empty strings only, in a non-empty array; duplicate identifiers *within* one molecule's own fragment are deduplicated before composition (a molecule listing the same package twice is not a cross-molecule conflict). An empty array (`[]`) is rejected, not treated as a valid zero-package contribution: `ComposedFile.contributing_molecule_ids` (below) is defined as molecules that contributed *at least one* package, so an empty-but-present fragment would be a molecule that both is and is not a contributor — a molecule wanting to declare no packages should simply not declare the `nix_packages` category at all. A fragment that is not a non-empty JSON array of non-empty strings aborts composition for the *entire* generation under the `nix-packages-fragment-invalid` diagnostic (FR-009) — refused, not skipped; no partial `ComposedFile` is written while any adopted molecule's fragment fails this check.

## ComposedFile *(new — conceptual state; only `packages` is persisted, at `.spaex/generated/nix-packages.json`)*

The generated result of merging every currently-adopted molecule's `PackageFragment`. `ComposedFile` as a whole is a conceptual grouping for this document, not the literal on-disk shape — only `packages` is serialized into the file itself.

| Field | Type | Notes |
|---|---|---|
| `packages` | `list[str]` | **The entire on-disk content of `.spaex/generated/nix-packages.json`**: a bare JSON array, e.g. `["cargo", "python312", "rustc"]` — no wrapping object. Sorted, deduplicated (exact string match) union of every active `PackageFragment.packages`, per research.md §2. Pure function of the *set* of currently-adopted contributing molecules — independent of adoption order or prior generations. This is what research.md §3's `flake.nix` reads via `builtins.fromJSON (builtins.readFile ...)` and passes as `extraPackages` — an object shape here would break that evaluation. |
| `contributing_molecule_ids` | `list[str]` | **Not written to the file.** Sorted molecule ids that contributed at least one package to this generation, recorded *only* in `install.lock` as this path's owners (plural — the one case where a path has more than one owning molecule). |

**State transitions**: created on first `spaex install` where any adopted molecule declares `nix_packages` → regenerated (not touched-in-place) on every subsequent install/remove where the active contributor set changes → regenerated with one fewer contributor's packages when `spaex remove` retracts one contributor while others remain (FR-006b) → deleted entirely once `contributing_molecule_ids` would become empty. See research.md §3 for how the exclusive-category `flake.nix` skeleton tolerates this file's absence (guarded read, not an unconditional one).

## InstallLock extension *(existing schema, extended)*

`install-lock.v4.schema.json`'s `moleculeEntry.paths` pattern gains an `anyOf` alternative accepting a bare repo-root-relative filename (research.md §5). **This is a schema-level (syntactic) relaxation only, not category-scoped enforcement**: `paths` is a flat list of path strings with no accompanying category field, so the schema itself cannot distinguish "this bare filename came from an exclusive-category atom" from any other case — it can only widen or narrow which path *shapes* are syntactically legal at all. The actual constraint that only exclusive-category atoms ever produce bare-root-relative entries is enforced by application logic (the materializer in `src/spaex/install/`), not by the schema. `ComposedFile`'s path (`.spaex/generated/nix-packages.json`) already satisfies the existing dot-segment-required pattern unchanged and is listed under every one of its `contributing_molecule_ids`' entries — the existing schema already allows one path to appear in multiple molecules' `paths` arrays (no schema change needed for shared ownership itself, only for the bare-filename case).
