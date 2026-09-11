# ADR 0016: Relocate the spaex-constitution Molecule to `haexmas/atoms`

**Status**: Accepted
**Date**: 2026-09-12
**Related**:
[Spec 023](../../specs/023-behavior-harness/);
ADR 0014 (introduced the fragment split, self-published from this repo);
ADR 0015 (post-merge fidelity fixups to that split);
`.specify/memory/constitution.md`;
`haexmas/atoms` PR #2 (adds `com.github.haexmas.atoms.spaex-constitution`)

## Context

ADR 0014 split this repo's own constitution into Spec 023 behavior
fragments, but kept them self-published: this repo (`spaex`) was both the
publisher and, via its own `.spaex.json`, the sole consumer of
`com.github.haexmas.spaex.constitution`.

That self-reference was the root cause of two separate problems surfaced
this session:

1. `.spaex.json`'s pin still read the pre-[[rename ADR 0011]] URL
   (`https://github.com/haexmas/haex-hive`). It kept resolving via GitHub's
   rename redirect, so nothing was actually broken, but fixing it properly
   meant pinning to a commit on `main` that did not exist until after the
   very PR making the fix had merged: a chicken-and-egg only a
   self-referencing consumer runs into.
2. `haexmas/atoms` already exists as this project's general-purpose atoms
   publisher (`graphify-first-authoring`, `speckit-session-hopper`).
   Having `spaex` the tool *also* act as a molecule publisher for its own
   governance content, alongside that dedicated publisher, split the
   "where do our atoms live" answer across two repos for no reason other
   than history.

## Decision

Move the fragment-based delivery of spaex's own constitution out of this
repo entirely, into a new molecule in `haexmas/atoms`:
`com.github.haexmas.atoms.spaex-constitution` (`haexmas/atoms` PR #2),
carrying `constitution.md` (an unchanged copy of this repo's master text)
and the same 19 behavior fragments, byte-identical to what ADR 0014/0015
produced here.

In this repo:
- Remove `.specify/memory/manifest.json` and `.specify/memory/fragments/`.
- Remove the root `manifest.json` entirely: the constitution was this
  repo's only published molecule, and the publisher-manifest schema
  requires at least one entry (`minProperties: 1` on `molecules`), so an
  empty publisher manifest is not a valid intermediate state. This repo is
  now purely a consumer, not a publisher.
- Keep `.specify/memory/constitution.md` in place, unchanged in content:
  speckit tooling (`/speckit-plan`, `/speckit-constitution`, etc.) reads
  this file directly from its conventional path, independent of the spaex
  molecule/atom system. Only its intro paragraph's pointer was updated to
  name the new external home instead of local `manifest.json`/`fragments/`.
- Bump `constitution.md` to 1.4.4 (PATCH: relocation, no principle content
  change), per this document's own version-bump rules.

`.spaex.json` itself is **not** updated in this same change. Its
`compounds[0]` entry still points at the old, self-referencing
`com.github.haexmas.spaex.constitution` / `haexmas/haex-hive` pin, which
by this point resolves to a molecule directory (`.specify/memory`) that no
longer has a `manifest.json` at all — the next `spaex install` against
this exact state would fail to resolve. This is intentional and bounded:
the follow-up commit (see below) lands in the same PR, once
`haexmas/atoms` PR #2 has merged and its merge commit SHA is known, so
`.spaex.json` is never left pointing at a broken pin on `main` for longer
than the time between these two commits in one branch.

## Consequences

**spaex is no longer a molecule publisher.** Every other consumer of
constitution/authoring content in this project's ecosystem already comes
from `haexmas/atoms`; spaex now does too, for its own constitution.
`haexmas/atoms`' own PR flow and branch protection govern future
amendments to the fragment content (mirroring what `pr-required-for-main`
already required here).

**Two-commit landing, one PR.** Removing the self-published molecule and
repointing `.spaex.json` land together once `haexmas/atoms` PR #2 is
merged, so this repo is never on `main` with a `.spaex.json` pin that
`spaex install` cannot resolve.

**Version divergence is expected and acceptable.** `constitution.md`'s own
version (1.4.4 after this change) and the `spaex-constitution` molecule's
manifest version in `haexmas/atoms` (1.4.3 as published) are independent
counters from this point on: this repo's document history and that
repo's molecule-package history no longer have to stay numerically
identical, only content-identical per fragment (enforced by the
`amendment-mirrors-fragment-in-same-commit` fragment, wherever its
"same commit" now spans two repos in practice).

## Alternatives considered

- **Keep self-publishing, just fix the URL** (the original plan for this
  session before this ADR): rejected once the operator pointed out
  `haexmas/atoms` already exists as the intended home for this kind of
  content; keeping a second, redundant self-publish path indefinitely
  serves no purpose once a straightforward alternative exists.
- **Delete `.specify/memory/constitution.md` entirely, rely only on the
  atoms-hosted copy**: rejected. speckit's own tooling reads this
  conventional local path directly, independent of `spaex install`;
  removing it would break `/speckit-plan`'s constitution check for this
  repo's own development workflow, which has nothing to do with which
  repo publishes the fragment-based derivative.
- **Land `.spaex.json`'s repoint in this same commit, pinned to the
  not-yet-merged `haexmas/atoms` PR #2 branch commit**: rejected, same
  reasoning as ADR 0014's equivalent alternative: a branch commit can be
  rebased or force-pushed away, invalidating the pin; wait for the merge.

## Follow-ups

- Once `haexmas/atoms` PR #2 merges: update `.spaex.json`'s
  `compounds[0]` to `source: https://github.com/haexmas/atoms`,
  `revision: <merge commit SHA>`, `molecules: ["com.github.haexmas.atoms.spaex-constitution"]`,
  then run `spaex install` to materialize and compose `.spaex.md` from the
  externally-hosted fragments for the first time.
