# Research: Generic Atom-Category Delivery and Removal

## §1. Category kind: fixed vocabulary, not a per-category flag

**Decision**: Two fixed category kinds, distinguished by category *name*, not by a new manifest field:
- Any `atoms` category key other than `behavior`, `skill`, `skills`, and the one reserved composable key (`nix_packages`) is **exclusive**: single owner per destination path, verbatim content, refused on path collision between molecules (FR-001–FR-005).
- `nix_packages` is the one **composable** category: any number of molecules may declare it; `spaex install` merges every active molecule's package-identifier list into one generated file (FR-006a/FR-006b).

**Rationale**: The spec's own Assumptions section already scopes this to "one fixed category for package/dependency fragments," explicitly rejecting a general "any category can opt into composable vs. exclusive" configuration knob as broader than the driving use case needs. A fixed, well-known name is the simplest thing that satisfies that scope — no new schema field, no new validation surface, and it mirrors how `behavior` is already a hardcoded, specially-handled category name rather than a flagged one.

**Alternatives considered**:
- **A `composable: true` boolean per category in the molecule manifest.** Rejected: this is real generality the spec explicitly did not ask for (see spec.md Assumptions), and it multiplies the states the installer/schema must validate (composable exclusive-looking categories, exclusive composable-looking categories) for no requirement that currently needs it.
- **Infer composability from content-type (e.g. "JSON list values are composable").** Rejected: fragile, implicit, and surprising — a molecule author declaring a category should not have its delivery semantics silently depend on what the file happens to contain.

## §2. Composition algorithm

**Decision**: Deterministic, order-independent merge with no LLM involvement:
1. Collect every currently-adopted molecule that declares a `nix_packages` fragment.
2. Read each molecule's fragment file (a JSON array of package identifiers — plain strings, e.g. `["python312"]`).
3. Concatenate all identifiers across all active molecules, then reduce to a sorted, deduplicated (exact string match only) list.
4. Serialize that list, deterministically formatted (stable key order, trailing newline, no timestamps), to the generated output.

**Rationale**: FR-005 requires byte-identical output across reinstalls with unchanged inputs; sorting the final merged list makes the result a pure function of the *set* of active molecules, independent of install order or how many times install has run before. This is not the `behavior`-atom Composer (Spec 023/026): that pipeline exists to resolve semantic overlap/contradiction in free-form prose via an LLM call, which has no bearing on merging a structured list of opaque string identifiers. Reusing it here would add an LLM call (cost, latency, nondeterminism risk) to solve a problem a `sorted(set(...))`-shaped operation already solves exactly.

**Alternatives considered**:
- **Reuse the `behavior` Composer pipeline.** Rejected per the above — wrong tool for structured, order-independent data; see spec.md FR-006a's explicit correction of this on an earlier draft.
- **Preserve molecule-adoption order instead of sorting.** Rejected: makes output depend on *history* (which molecule was adopted first), not just the current active set, which would make two consumer repos with the same adopted-molecule set produce different `flake.nix` content depending on how they got there — an avoidable, surprising inconsistency.
- **Semantic conflict detection between similarly-named packages (e.g. flag `python311` vs `python312`).** Rejected as out of scope (spec.md Edge Cases and Non-Goals): spaex has no package-identity/version semantics and this mirrors Nix's own behavior when the same packages are listed by hand.

## §3. Where composed vs. exclusive content lives

**Decision**:
- Exclusive-category files (`flake.nix`, `.envrc`, `.gitignore`) are written at the literal consumer-repo root, per ADR 0026.
- The composable category's generated output is written to `.spaex/generated/nix-packages.json`, staying inside the existing dot-directory boundary — no boundary widening needed for it.
- The root `flake.nix` (an exclusive atom shipped once by a base molecule) reads `.spaex/generated/nix-packages.json` via `builtins.fromJSON (builtins.readFile ./.spaex/generated/nix-packages.json)` and passes the resulting list as `extraPackages` to the shared `mkDevShell` helper.

**Rationale**: Minimizes the actual scope of ADR 0026's boundary widening to exactly the files that must be root-visible for their own tools to find them. Nix has no difficulty reading a JSON file from a subdirectory relative to the flake; this keeps the generated-and-frequently-regenerated artifact under the same ownership/cleanup machinery `behavior` atoms already use, and keeps the root itself limited to the three files an operator actually expects to see there.

**Alternatives considered**:
- **Write the composed package list directly into `flake.nix` by regenerating the whole file.** Rejected: conflates an exclusive, human-glanceable skeleton file (which an operator may reasonably open and read) with machine-generated content regenerated on every install/remove; keeping them separate means the skeleton file only changes when the base molecule itself changes, not on every dependency add/remove elsewhere.

## §4. Removal semantics for composed files

**Decision**: `spaex remove <molecule>` recomputes the active molecule set first, then re-runs the §2 composition algorithm over whatever remains. If zero molecules still declare `nix_packages`, the generated file is deleted; otherwise it is rewritten to reflect only the remaining contributors (FR-006b).

**Rationale**: Matches the "recompute from scratch, don't patch incrementally" principle already established for `behavior`/`constitution.md` (Spec 023) and directly resolves the ordering/idempotency problems raised during clarification (sequential incremental mutation was considered and rejected — see spec.md's discussion of "step by step" installation in favor of composition).

**Alternatives considered**: Incremental/sequential mutation (append on install, surgically remove on `spaex remove`) — rejected during spec clarification for order-dependence and fragile removal; see spec.md.

## §5. Install-lock path-pattern relaxation

**Decision**: Extend `install-lock.v4.schema.json`'s `paths` item pattern with an alternative branch accepting a bare repo-root-relative filename (no required leading dot-segment), scoped to entries contributed via the exclusive generic atom category. The existing dot-segment-required pattern remains the only accepted form for `behavior`/`skill`/`skills` and for the composable category's `.spaex/generated/...` entries.

**Rationale**: Required to record ownership/provenance for `flake.nix`/`.envrc`/`.gitignore` at all (see ADR 0026); a JSON Schema `anyOf` alternative is the smallest change that preserves every existing constraint for existing categories while admitting the new case.

**Alternatives considered**: Drop the pattern constraint entirely (accept any path). Rejected: loses the existing protection against path traversal and platform-unsafe characters that the current pattern (and the sibling `repoRelativePath` `$def` in the molecule-manifest schema) already enforces; a targeted `anyOf` keeps that protection for the new case too.
