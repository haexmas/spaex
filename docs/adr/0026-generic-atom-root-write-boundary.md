# ADR 0026: Extend spaex's write boundary to the visible repo root for generic atom categories

**Status**: Accepted
**Date**: 2026-09-18
**Related**: Spec 027 (generic atom-category delivery and removal)

## Context

Every path spaex has ever written to a consumer repo has lived under a
leading dot-segment (`.spaex/constitution.md` is the only case today). This
is not incidental: `install-lock.v4.schema.json`'s `paths` pattern requires
a leading dot-directory segment, and `install_lock.py` documents
"participating roots" as derived from "the set of leading dot-segments
across every path" — the on-disk contract assumes spaex confines itself to
hidden tool-config directories and never touches the visible project root.

Spec 027 asks spaex to deliver and later remove files such as `flake.nix`,
`.envrc`, and `.gitignore` — files whose consuming tools (Nix, direnv, Git)
require them at the repo root by their own convention. There is no way to
honor Spec 027's zero-manual-steps goal (SC-001) while keeping spaex's
writes confined to a dot-directory: redirecting the real content into
`.spaex/generated/` and asking the operator to hand-maintain a root shim
file reintroduces exactly the manual per-repo step the feature exists to
remove, and does so for every consuming repo, forever.

## Decision

spaex's write/ownership boundary is extended, specifically and only for
files delivered through the *exclusive* generic atom category, to allow
repo-root-relative paths with no required leading dot-segment.
`install-lock.v4.schema.json`'s `paths` pattern is relaxed accordingly for
exclusive-category entries, and the "participating root = leading
dot-segment" derivation in `install_lock.py`'s module docstring is updated
to note the root-path exception.

The composable dependency-contribution category does **not** need this
widening: its generated output (a package-fragment composition, consumed by
an exclusive-category `flake.nix` via a plain Nix `import`) is written
under `.spaex/generated/`, staying inside the existing dot-directory
boundary. Only the small, fixed set of skeleton files that their consuming
tools require at the literal repo root (`flake.nix`, `.envrc`, `.gitignore`)
ever need root placement, and those are always exclusive-category atoms.

This does not change how `behavior`, `skill`, or `skills` atoms are
tracked — those remain confined to their existing dot-directories. The
boundary widens only for the exclusive generic-atom-category mechanism, and
only because the files it is designed to deliver are only useful to their
consuming tools when placed at the root.

## Consequences

- spaex gains, for the first time, the ability to write and later delete
  files at the visible top level of a consumer repository, not only inside
  recognizable tool-config directories. Operators adopting a molecule that
  uses this category should expect root-level file changes, the same way
  they already expect `.spaex/constitution.md` changes from `behavior`
  atoms.
- FR-006's accepted overwrite behavior (a generic atom claiming a path
  already occupied by a file spaex does not own silently overwrites it)
  applies at the repo root, where pre-existing, individually-authored files
  are more likely to exist than under `.spaex/`. This is a deliberate,
  documented risk accepted for frictionless adoption (see spec.md
  Assumptions), not an oversight.
- No change to path-overlap refusal for exclusive categories (FR-003) or to
  install-transaction atomicity (Spec 008): both extend to root paths
  unchanged, only the dot-segment requirement is lifted.
- The composable dependency-contribution category's ownership tracking is
  entirely unaffected by this ADR — its generated file stays under
  `.spaex/generated/` and continues to satisfy the existing path pattern
  without modification.

## Alternatives Considered

- **Keep the dot-directory boundary; deliver real content under
  `.spaex/generated/` with a static root shim file.** Rejected: `.envrc`
  and `.gitignore` cannot be redirected this way at all (direnv and Git
  require them at the literal repo root), and even for `flake.nix` this
  only relocates the problem — the shim itself is still a root file spaex
  cannot own without the same boundary change, and asking every consuming
  repo to hand-author and maintain that shim reintroduces the manual step
  Spec 027 exists to eliminate.
- **Scope the boundary change to `flake.nix`/`.envrc`/`.gitignore` by name
  instead of generalizing to any generic-atom-category path.** Rejected:
  hard-coding filenames into the installer couples a generic mechanism to
  one publisher's use case and would need a repeat of this same decision
  for the next repo-root file some other molecule wants to deliver.
