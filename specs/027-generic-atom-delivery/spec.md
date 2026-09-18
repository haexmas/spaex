# Feature Specification: Generic Atom-Category Delivery and Removal

**Feature Branch**: `027-generic-atom-delivery`
**Created**: 2026-09-18
**Status**: Draft
**Input**: User description: "Generic non-behavior atom-category delivery and removal for spaex. This is the concrete first use case that opens the reserved Spec 015 slot (see docs/plans/2026-09-07-slot-015-multi-environment-placeholder.md): the operator wants to publish a molecule that ships static development-environment files (flake.nix, .envrc, .gitignore for a shared Nix devShell) from the haexmas/atoms publisher and have `spaex install` place them at the consumer repo root, and — critically — have `spaex remove` delete those same files again when the molecule is retracted, the same way `behavior` atoms are cleaned up today. Scope is deliberately narrower than the full Spec 015 placeholder sketch: static file placement and removal for atom categories other than `behavior`, `skill`, and `skills`, with the same ownership tracking, path-overlap refusal, and install determinism guarantees `behavior` atoms already have. Multi-environment selection vocabulary, consumer-side environment switching, and orchestration verbs are explicitly out of scope, deferred to a future spec. Reference use case: a `com.github.haexmas.atoms.nix-devshell` molecule shipping flake.nix + .envrc + .gitignore, consumed by repos like holzi and spaex itself."

## Clarifications

### Session 2026-09-18

- Q: When an adopted molecule declares an invalid `nix_packages` fragment (not a JSON array of non-empty strings), should `spaex install` refuse the whole install, or skip that molecule's contribution with a warning and compose the rest? → A: Refuse the whole install with a typed diagnostic; no file is written for the composed category in that generation. Consistent with this project's existing no-silent-degradation principle (e.g. Spec 026 FR-012a and its oversized-molecule refusal before any composer call).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Adopt a molecule that delivers static files (Priority: P1)

An operator adopts a molecule that ships static repo-setup files (for example, files that configure a reproducible development environment) and expects those files to appear in their repo without manually copying anything.

**Why this priority**: This is the core value of the feature — today only `behavior` atoms are actually materialized into a consumer repo; every other declared category is inert. Without this, the feature delivers nothing.

**Independent Test**: Adopt a molecule declaring three files under a non-`behavior` atom category, run `spaex install`, and confirm all three files exist at their declared repo-root-relative paths with content matching the molecule source exactly.

**Acceptance Scenarios**:

1. **Given** a molecule manifest declares files under a category other than `behavior`, `skill`, or `skills`, **When** the operator runs `spaex install`, **Then** each declared file is written at its repo-root-relative path with byte-identical content to the molecule source.
2. **Given** the files were already installed and nothing in the manifest or molecule content changed, **When** the operator runs `spaex install` again, **Then** the files remain byte-identical to the previous run (no spurious rewrites).

---

### User Story 2 - Retract a molecule and have its files cleaned up (Priority: P1)

An operator who removes a previously adopted molecule expects the files it contributed to disappear along with it, the same way removing a molecule with `behavior` atoms already cleans up its constitution fragments.

**Why this priority**: Without automatic cleanup, the feature only solves half the problem the operator raised — installed files would accumulate as unmanaged clutter every time a molecule is retracted, which is the exact drawback of the install-hook workaround this feature replaces.

**Independent Test**: Adopt a molecule that delivers files via a generic atom category, confirm they exist after `spaex install`, then run `spaex remove` for that molecule and confirm none of its files remain.

**Acceptance Scenarios**:

1. **Given** a molecule's generic-category files are present in the repo, **When** the operator runs `spaex remove` for that molecule, **Then** every file that only this molecule contributed is deleted.
2. **Given** two adopted molecules each contribute their own, non-overlapping files, **When** the operator removes only one of them, **Then** only that molecule's files are deleted and the other molecule's files remain untouched.

---

### User Story 3 - Exclusive-category conflicts are still refused (Priority: P2)

An operator who adopts two molecules that both declare full ownership of the same destination path under an *exclusive* generic atom category (one owner, verbatim content — e.g. `.envrc`, `.gitignore`) gets a clear refusal at install time instead of one molecule silently overwriting the other.

**Why this priority**: Silent overwrites would make installs non-deterministic and hide data loss. Today's `atoms-category-overlap` check only catches one molecule declaring the same path under two of its *own* categories — it has never needed to catch two *different* molecules colliding, because `behavior` atoms never have their own destination path (every molecule's fragments are composed into the one shared `.spaex/constitution.md`). Exclusive generic categories are the first case where two different molecules can each declare their own destination path, so this is new cross-molecule refusal logic, generalizing the same underlying principle (a path may have exactly one declaring owner) that `atoms-category-overlap` already established at the single-molecule level. It does not apply to composable contributions (User Story 4), where multiple molecules sharing one generated file is the expected, supported case.

**Independent Test**: Adopt two molecules that each declare a file at the same repo-root-relative path under an exclusive generic category, run `spaex install`, and confirm the install is refused with no files written for either conflicting molecule.

**Acceptance Scenarios**:

1. **Given** two adopted molecules declare the same destination path under an exclusive generic atom category, **When** the operator runs `spaex install`, **Then** the install is refused and neither molecule's conflicting file is written.

---

### User Story 4 - Multiple molecules contribute orthogonal dependencies to one generated file (Priority: P1)

An operator adopts several molecules that each need their own, non-conflicting set of packages available in the repo's shared development environment (for example, a Python molecule and a Rust molecule each need their own toolchain in the same Nix devShell). Each molecule contributes its own package fragment; spaex composes all active contributions into one generated environment file, the same way multiple molecules' `behavior` fragments already compose into one `constitution.md` today.

**Why this priority**: This is the actual dependency-sharing scenario that motivated the feature. Treating every shared destination path as a refuse-on-conflict case (User Story 3) would make it impossible for independent molecules to jointly populate one development environment, which defeats the purpose for the reference Nix use case.

**Independent Test**: Adopt two molecules that each declare a package-contribution fragment toward the same generated environment file, run `spaex install`, and confirm the generated file contains both contributions and the install is not refused.

**Acceptance Scenarios**:

1. **Given** two adopted molecules each declare a package-contribution fragment for the same generated environment file, **When** the operator runs `spaex install`, **Then** the generated file contains both molecules' contributions and the install succeeds.
2. **Given** the operator later removes one of the two contributing molecules, **When** `spaex remove` runs, **Then** the generated file is regenerated to contain only the remaining molecule's contribution, rather than being deleted outright.
3. **Given** the operator removes the last remaining contributing molecule, **When** `spaex remove` runs, **Then** the generated file is deleted entirely.

---

### Edge Cases

- What happens when the target path for an exclusive generic-category file is already occupied by a file spaex does not own (pre-existing, not previously installed by spaex)? Resolved by FR-006: `spaex install` overwrites it.
- What happens when an operator manually edits a file that spaex delivered, and later removes the molecule that delivered it? Resolved by FR-007: spaex warns and leaves the file in place rather than deleting it.
- What happens when the install transaction fails partway through writing generic-category files, or partway through regenerating a composed file? Resolved by FR-011: composed-category files live inside `.spaex/` and are covered by the existing directory-swap transaction unchanged; exclusive-category root files are outside `.spaex/` and cannot participate in that same directory swap (it publishes exactly one directory), so they are written individually (each write atomic in isolation) *before* that swap runs. A failure partway through root-file writes aborts before the swap, leaving the previous generation's `install.lock` authoritative — any root files already written are harmless, self-healing leftovers that the next `spaex install` retry overwrites (FR-006).
- What happens when two molecules contribute package identifiers that are textually different but semantically conflicting (e.g. one contributes `python311`, another `python317`)? System performs exact-string deduplication only and has no semantic understanding of package identity or version compatibility; both identifiers are included in the composed output as independent packages, exactly as if an operator had listed both by hand in one `packages` list. This is not a new limitation introduced by composition — it matches how a Nix devShell already behaves when two same-purpose, differently-versioned packages are both listed (whichever is later on `PATH` wins for unqualified invocations; both remain present in the store).
- What happens when an adopted molecule's `nix_packages` fragment is malformed (not a JSON array of non-empty strings)? Resolved by FR-009: `spaex install` refuses the whole install with a typed diagnostic rather than silently dropping that molecule's contribution.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST materialize, on `spaex install`, every file declared under an *exclusive* generic atom category (any category other than `behavior`, `skill`, `skills`, and the composable dependency-contribution category from FR-006a) verbatim to the repo-root-relative path given in the molecule manifest.
- **FR-002**: System MUST record the owning molecule id and category for each materialized file (exclusive or composed), the same way ownership is tracked for `behavior`-atom files today, so ownership can be queried and conflicts detected.
- **FR-003**: System MUST refuse an install where two adopted molecules declare the same destination path under an *exclusive* generic atom category, under a new diagnostic key `exclusive-atom-path-collision` (naming both colliding molecule ids and the shared path) distinct from the existing `atoms-category-overlap` key. This is new cross-molecule enforcement — `atoms-category-overlap` only ever covered one molecule's own manifest declaring a path twice — generalizing the same one-owner-per-path principle to across molecules. This refusal does not apply to the composable dependency-contribution category (FR-006a), where multiple molecules sharing one generated file is expected.
- **FR-004**: `spaex remove` MUST delete every file that only the retracted molecule contributed via an exclusive generic atom category, mirroring existing `behavior`-atom cleanup on removal.
- **FR-005**: Two consecutive `spaex install` runs with unchanged manifest and molecule inputs MUST produce byte-identical materialized files for generic atom categories (exclusive or composed), matching the determinism guarantee `spaex install` already gives overall.
- **FR-006**: When the declared destination path for an exclusive generic atom is already occupied by a file spaex does not own, `spaex install` MUST overwrite the existing file with the molecule-declared content.
- **FR-006a**: System MUST support a composable dependency-contribution category through which multiple adopted molecules each declare a package fragment for a shared development environment; `spaex install` MUST compose every active molecule's fragment deterministically into one generated environment file, rather than refusing due to shared ownership. Composition here means a plain, deterministic merge of structured package identifiers (e.g. a sorted, deduplicated union) — it reuses the *recompute-the-whole-output-from-every-currently-active-fragment* principle the `behavior`-atom Composer (Spec 023/026) already established for `constitution.md`, but not that Composer's LLM-based prose-merging mechanism, which exists to resolve semantic overlap/contradiction in free text and has no bearing on merging a structured list of package names.
- **FR-006b**: When `spaex remove` retracts a molecule that contributed to a composed environment file, the system MUST regenerate that file to exclude the retracted molecule's fragment, deleting the file entirely only once no adopted molecule contributes to it any longer.
- **FR-007**: When `spaex remove` would delete or regenerate a file whose on-disk content no longer matches what spaex last wrote (modified by the operator since install), the system MUST warn and leave the file in place rather than deleting or regenerating it.
- **FR-008**: System MUST continue treating `behavior`, `skill`, and `skills` as reserved category names whose existing, specialized handling is unaffected by this generalization.
- **FR-009**: When any adopted molecule's `nix_packages` fragment is not a *non-empty* JSON array of non-empty strings, `spaex install` MUST refuse the entire install with the typed diagnostic `nix-packages-fragment-invalid`, naming the offending molecule id, rather than skipping that molecule's contribution and composing the rest. No composed-category file is written in that generation while the refusal stands. An empty array (`[]`) is invalid under this rule — a molecule contributing zero packages should not declare the category at all — so the "at least one contributing molecule" state `ComposedFile` assumes (data-model.md) can never be produced by a technically-present-but-empty contributor.
- **FR-010**: For every exclusive-category write (FR-001), delete (FR-004), and overwrite (FR-006), the system MUST resolve the destination's canonical path (following any symlinked ancestor directory) and refuse the operation if that canonical path falls outside the consumer repository's canonical root, even when the declared path is lexically repo-relative with no `..` segments.
- **FR-011**: Composed-category files (living under `.spaex/generated/`) publish through the existing `.spaex/` directory-swap transaction (Spec 008) unchanged. Exclusive-category root files cannot participate in that same swap, since it publishes exactly one directory and root files live outside `.spaex/`; the system MUST instead write each exclusive-category root file individually, with each individual write atomic in isolation (no torn/partial file content ever observable), and MUST complete all such root-file writes for a generation *before* staging and publishing that generation's `.spaex/` swap — so that a root-file write failure leaves the previous generation's `install.lock` authoritative rather than one claiming ownership of a file that was never actually written. `spaex remove` MUST apply the same ordering in reverse: delete owned root files individually before publishing the updated (smaller) `install.lock` generation, so a failed deletion leaves `install.lock` still claiming that file and a retry attempts deletion again.

### Key Entities

- **Exclusive Generic Atom Category**: A named group of files declared under a molecule's `atoms` map, for any category key other than `behavior`, `skill`, `skills`, or the composable dependency-contribution category, whose files are materialized verbatim to the consumer repo with a single owning molecule per path.
- **Composable Dependency-Contribution Category**: A category through which multiple molecules each declare an orthogonal package fragment; spaex composes all active fragments into one generated environment file rather than enforcing single ownership.
- **Delivered File**: A single file written into a consumer repo from an exclusive generic atom category, tracked with its owning molecule id and category so it can be checked for path conflicts and cleaned up on removal.
- **Composed File**: A single generated file produced by merging every adopted molecule's fragment from the composable dependency-contribution category; regenerated (not deleted) when one of several contributing molecules is removed, and deleted only once its last contributor is removed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator adopting a molecule that ships N static files sees all N files present at their correct repo paths immediately after one `spaex install` run, with zero manual file-copying steps.
- **SC-002**: Retracting that molecule via `spaex remove` leaves zero of its previously-delivered exclusive-category files behind in the repo, except where FR-007 explicitly preserves a modified file.
- **SC-003**: Running install, then remove, then install again with no manifest changes in between reproduces byte-identical delivered- and composed-file content every time.
- **SC-004**: A molecule that attempts to claim a destination path already owned by another adopted molecule under an exclusive category is rejected at install time, with zero files written for the conflicting molecule.
- **SC-005**: Two molecules that each contribute an orthogonal dependency fragment to the same generated environment file both see their contribution present after one `spaex install` run, with neither being rejected because they share that file.
- **SC-006**: Removing one of several molecules contributing to a generated environment file leaves the other contributors' packages intact in that file; the file is only removed once every contributor has been retracted.

## Non-Goals

- Removing a molecule's dependency-contribution fragment from a composed environment file (FR-006b) removes that dependency from the *definition* the environment is built from. It does not reclaim disk space or otherwise garbage-collect the underlying package artifacts — that remains an operator- and system-level concern (e.g. Nix's own store garbage collection) entirely outside spaex's responsibility, since such cleanup is inherently system-wide and not scoped to a single repo or molecule.
- Detecting or resolving semantic conflicts between package identifiers contributed by different molecules (e.g. two molecules each wanting a different version of "the same" tool under different package names) is out of scope. Composition performs exact-string deduplication only; it does not understand package identity, versioning, or compatibility. This mirrors Nix's own behavior when multiple same-purpose packages are listed by hand and is not a gap introduced by this feature.

## Assumptions

- The exclusive-delivery generalization covers any atom category name except the reserved `behavior`, `skill`, `skills`, and composable dependency-contribution keys — no new category-naming vocabulary needs to be invented for the exclusive case; this matches the molecule-manifest schema's existing open `Dict[str, List[str]]` shape and the atoms publisher README's stated intent that environment-config files "can be declared under any category name a publisher chooses."
- The composable dependency-contribution mechanism (FR-006a/FR-006b) is scoped to one fixed category for package/dependency fragments feeding a shared generated environment file — it reuses the `behavior`-fragment Composer's *recompute-from-every-active-fragment* principle (Spec 023/026), not its LLM-based prose-merging mechanism (see FR-006a), and does not introduce a general "any category can opt into composable vs. exclusive" configuration knob; broadening that is left to future work if a concrete need arises.
- Multi-environment selection vocabulary (dev/staging/prod), consumer-side environment switching, and runtime orchestration verbs (e.g. `spaex enter`, `spaex dev up`) remain out of scope, deferred to a future spec per the original Spec 015 placeholder's own non-goals.
- A `com.github.haexmas.atoms.nix-devshell-base` molecule ships the exclusive `flake.nix`/`.envrc`/`.gitignore` skeleton (the `mkDevShell` wiring) exactly once; per-language molecules (python, rust/tauri, javascript-typescript, ...) do not each ship their own `flake.nix` — they each contribute only a package fragment via the composable dependency-contribution category, which the skeleton's generated package list reads. This split is what lets a single contributor (e.g. the python molecule) be removed independently: removal regenerates the composed package list from the remaining contributors without touching the untouched, separately-owned skeleton file. Publishing these molecules is a follow-up once this spec lands, not part of this spec's deliverable.
- Overwriting a pre-existing, spaex-unowned file at an exclusive atom's destination path (FR-006) is an explicit, accepted risk for the convenience of frictionless adoption; operators who already have a hand-authored file at that path are responsible for reconciling it (e.g. renaming it aside) before adopting a molecule that claims the same path.
- Existing install-transaction atomicity (Spec 008) already covers partial-failure rollback for everything inside `.spaex/`; this spec's composed-category files (`.spaex/generated/nix-packages.json`) participate in that same transaction unchanged. Exclusive-category root files live outside `.spaex/` and cannot participate in a swap scoped to one directory — they use the separate, per-file-atomic, publish-before-the-swap mechanism defined in FR-011/research.md §6 instead.
