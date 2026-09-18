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
- The root `flake.nix` (an exclusive atom shipped once by a base molecule) reads `.spaex/generated/nix-packages.json` via a **guarded** read — `if builtins.pathExists ./.spaex/generated/nix-packages.json then builtins.fromJSON (builtins.readFile ./.spaex/generated/nix-packages.json) else [ ]` — and passes the resulting list as `extraPackages` to the shared `mkDevShell` helper, not an unconditional `readFile`.

**Rationale**: Minimizes the actual scope of ADR 0026's boundary widening to exactly the files that must be root-visible for their own tools to find them. Nix has no difficulty reading a JSON file from a subdirectory relative to the flake; this keeps the generated-and-frequently-regenerated artifact under the same ownership/cleanup machinery `behavior` atoms already use, and keeps the root itself limited to the three files an operator actually expects to see there. The guarded read matters because `flake.nix` (owned by the base molecule) and `nix-packages.json` (owned collectively by whichever molecules currently declare `nix_packages`) have independent lifecycles: retracting the *last* `nix_packages` contributor deletes the generated file (§4/FR-006b) while the base molecule, and therefore `flake.nix`, can remain adopted. An unconditional `readFile` would make `nix develop`/`nix flake` evaluation fail in that (entirely valid — "no extra packages contributed") state; the guard treats a missing file as `[ ]`, which is semantically exactly what it means.

**Alternatives considered**:
- **Write the composed package list directly into `flake.nix` by regenerating the whole file.** Rejected: conflates an exclusive, human-glanceable skeleton file (which an operator may reasonably open and read) with machine-generated content regenerated on every install/remove; keeping them separate means the skeleton file only changes when the base molecule itself changes, not on every dependency add/remove elsewhere.
- **Always keep `.spaex/generated/nix-packages.json` present (writing `[]` instead of deleting it once the last contributor is retracted), so `flake.nix` could use an unconditional `readFile`.** Rejected: it would make the composable category's "deleted entirely once no adopted molecule contributes to it" removal semantics (§4/FR-006b) conditional on some *other*, exclusive-category molecule's adoption state — coupling the two category kinds' lifecycles for no benefit over the guarded read, which keeps them fully independent.

## §4. Removal semantics for composed files

**Decision**: `spaex remove <molecule>` recomputes the active molecule set first, then re-runs the §2 composition algorithm over whatever remains. If zero molecules still declare `nix_packages`, the generated file is deleted; otherwise it is rewritten to reflect only the remaining contributors (FR-006b).

**Rationale**: Matches the "recompute from scratch, don't patch incrementally" principle already established for `behavior`/`constitution.md` (Spec 023) and directly resolves the ordering/idempotency problems raised during clarification (sequential incremental mutation was considered and rejected — see spec.md's discussion of "step by step" installation in favor of composition).

**Alternatives considered**: Incremental/sequential mutation (append on install, surgically remove on `spaex remove`) — rejected during spec clarification for order-dependence and fragile removal; see spec.md.

## §5. Install-lock path-pattern relaxation

**Decision**: Extend `install-lock.v4.schema.json`'s `paths` item pattern with an `anyOf` alternative branch accepting a bare repo-root-relative filename (no required leading dot-segment). This is a purely syntactic widening of which path *shapes* the schema accepts — `paths` is a flat array of strings with no per-entry category field, so the schema has no way to check "only exclusive-category atoms may use this shape." That check is application logic, in the materializer that decides what to write, not something expressible in the schema itself. The existing dot-segment-required pattern remains the *only* accepted form for `behavior`/`skill`/`skills` and for the composable category's `.spaex/generated/...` entries — those categories' materializers simply never produce a bare-filename path, even though the schema would now allow one there too.

**Rationale**: Required to record ownership/provenance for `flake.nix`/`.envrc`/`.gitignore` at all (see ADR 0026); a JSON Schema `anyOf` alternative is the smallest change that preserves every existing constraint for existing categories while admitting the new case. Being explicit that this is schema-level-only, not category-scoped, avoids a false sense that the schema itself prevents, say, a future `behavior`-atom bug from emitting a bare-filename path — that protection has to come from the materializer code, and should be covered by its own tests (tasks.md T004).

**Alternatives considered**: Drop the pattern constraint entirely (accept any path). Rejected: loses the existing protection against path traversal and platform-unsafe characters that the current pattern (and the sibling `repoRelativePath` `$def` in the molecule-manifest schema) already enforces; a targeted `anyOf` keeps that protection for the new case too.

## §6. Publishing root files without the existing `.spaex/` swap transaction

**Decision**: `src/spaex/io/transaction.py`'s `publish_generation`/`stage_generation` implement a crash-safe directory rename-swap for exactly one `live` root (`<root>.next/` written and fsynced → `<root>` renamed to `<root>.prev` → `<root>.next` renamed to `<root>`). This is scoped to one directory by construction and cannot be extended to also cover independent files scattered at the repo root — there is no single rename that swaps `flake.nix`, `.envrc`, `.gitignore`, *and* `.spaex/` into place together. Exclusive-category `DeliveredFile`s are therefore published through a separate, simpler mechanism:

1. Write each exclusive-category root file individually via temp-file-plus-rename in its own destination directory (write to `<path>.spaex-tmp`, fsync, `os.replace(<path>.spaex-tmp, <path>)`) — this is atomic *per file* (POSIX `rename(2)`/Windows `MoveFileEx` with replace both guarantee no observer ever sees a torn/partial file at `<path>`), just not atomic *across* files.
2. Perform every root-file write for the generation *before* staging/publishing that generation's `.spaex/` swap (which is what actually publishes the new `install.lock`).
3. If any root-file write fails, abort before the `.spaex/` swap runs at all. The previous generation's `install.lock` remains live and correct — it never claimed ownership of a file that in fact failed to write. Any root files that *did* write successfully before the failure are harmless leftovers: FR-006 already requires overwriting a spaex-unowned file at a claimed path, so the next `spaex install` retry silently reconciles them (same "reinstall converges" model `transaction.py`'s own docstring already establishes for the `.spaex/` swap).
4. `spaex remove` applies the same ordering in reverse: delete each owned root file individually (a single `os.remove` is already atomic at the filesystem level — no temp-file dance needed for a delete) *before* publishing the updated, smaller `install.lock` generation. A deletion failure leaves the previous (larger) `install.lock` generation live, still correctly claiming the file that in fact still exists; a retry attempts deletion again.

**Rationale**: This gives every individual root-file write or delete the same "no torn state ever observable" property the `.spaex/` swap gives its directory, without inventing a new multi-root transaction primitive. It does *not* give all-or-nothing atomicity across the *set* of root files the way the `.spaex/` swap gives its directory — writing `flake.nix` successfully and then crashing before writing `.envrc` is a real, reachable intermediate state. That gap is bounded and self-healing (ordering rule 3: the crash happens before `install.lock` publishes, so the next `spaex install` retry re-attempts and overwrites/completes the set) rather than eliminated outright. Building true cross-file atomicity for arbitrary repo-root paths (e.g. a second directory-swap-style primitive rooted one level up, requiring the entire repo root to be swappable) is a materially larger undertaking than this spec's scope and was rejected below.

**Alternatives considered**:
- **Extend `publish_generation` itself to accept root-relative `StagedFile`s alongside `.spaex/`-relative ones, staging everything under one `<repo_root>.next/`-style directory and swapping the whole repo root.** Rejected: would require swapping the *entire consumer repository* into place, including files this feature has nothing to do with (the operator's own source tree) — far larger blast radius than a coding-harness tool should touch, and incompatible with the repo already being a live, in-use working tree (git status, open editors, running processes) during install.
- **Write root files only after the `.spaex/` swap publishes `install.lock`.** Rejected: inverts the failure-safety property — a root-file write failure *after* `install.lock` already claims ownership leaves a lock that asserts something false about the repo's state until the next successful reinstall repairs it. Writing root files first means a failure there never corrupts `install.lock`'s meaning.
- **No atomicity at all for root files (plain `open(...).write(...)`).** Rejected: a crash mid-write leaves a torn, corrupt file at a path a tool (Nix, direnv, Git) will actively try to parse — worse than either "old content" or "missing," both of which are recognizable, recoverable states. Temp-file-plus-rename costs one extra syscall pair per file and eliminates this entirely.

## §7. Canonical path containment for exclusive writes

**Decision**: Before writing, deleting, or overwriting an exclusive-category `DeliveredFile`, resolve the destination through `Path.resolve()` (or equivalent — following symlinks at every ancestor component) and confirm the resulting canonical path is inside the canonically-resolved repository root; refuse the operation otherwise (FR-010).

**Rationale**: The existing `install-lock.v4.schema.json` path pattern (and the molecule-manifest `repoRelativePath` `$def`) already rejects `..` segments and absolute paths lexically, but a lexically-safe relative path can still canonicalize outside the repository if some ancestor directory in the repo working tree is itself a symlink pointing elsewhere. Because FR-006 already has this feature overwrite files it doesn't already own, and FR-004/FR-011 have it delete files, an unguarded write/delete through a symlinked ancestor would let a maliciously or accidentally symlinked directory redirect spaex into overwriting or deleting a file *outside* the repository entirely — a meaningfully worse outcome than the in-repo overwrite FR-006 already knowingly accepts.

**Alternatives considered**: Rely on the existing lexical path pattern alone. Rejected: demonstrably insufficient against a symlinked ancestor, which the lexical pattern cannot detect by construction (it only inspects the path string, never the filesystem).
