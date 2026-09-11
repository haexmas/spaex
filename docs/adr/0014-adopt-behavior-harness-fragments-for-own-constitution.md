# ADR 0014: Adopt Spec 023 Behavior Fragments for spaex's Own Constitution

**Status**: Accepted
**Date**: 2026-09-11
**Related**:
[Spec 023](../../specs/023-behavior-harness/);
`.specify/memory/constitution.md` (this molecule's authoritative text);
`.specify/memory/manifest.json`;
ADR 0011 (rename to spaex, prior PATCH-level amendment precedent)

## Context

spaex dogfoods itself: this repository both publishes and consumes the
`com.github.haexmas.spaex.constitution` molecule, whose content lives in
`.specify/memory/`. Until this change, that molecule declared a single
`atoms.constitution` file (`constitution.md`), the pre-Spec-023 delivery
mechanism: a consumer copies (or LLM-merges, per ADR 0010) the whole file
verbatim into `.spaex/constitution.md`.

Spec 023 (Phases 1-7, merged to `main`) built a richer mechanism: molecules
declare discrete behavior fragments (`atoms.behavior`), each with its own
`id`/`modality`/`atom_source`, materialized and composed by `spaex install`
into a project's `.spaex.md`, with mechanical conflict detection
(`spaex-precheck-*`, exit codes 20-22) and an LLM Composer step that
surfaces semantic contradictions to the operator instead of silently
picking a side. None of that machinery benefited this repo's own
constitution, because it was still delivered as one opaque file.

A second, unrelated problem surfaced alongside this: the consumer-side
`.spaex.json` in this repo (and its worktrees) pins the molecule's source
at `https://github.com/haexmas/haex-hive`, the pre-rename repository URL
(ADR 0011). It still resolves via GitHub's automatic rename redirect, but
it is not the canonical URL, and `spaex`'s own `canonicalize()` does not
detect or correct GitHub renames.

## Decision

Rebuild `.specify/memory/manifest.json` to declare `atoms.behavior` instead
of `atoms.constitution`, listing 18 standalone fragment files under
`fragments/`, one per distinct MUST/MUST NOT directive across:

- The 8 numbered Core Principles (I-VIII).
- The Development Workflow section's actionable rules (speckit workflow
  adherence, phasing discipline, ADR requirement, PR-required-for-main,
  merge strategy, Conventional Commits).
- The Governance section's operative rules (constitution supersedes spec
  preferences, amendment procedure, version-bump rules, enforcement
  tooling).

`constitution.md` remains the authoritative, human-readable master text;
the fragments are a machine-composable derivative of it, not a
replacement. A future amendment to a principle MUST update both the prose
in `constitution.md` and its corresponding fragment file in the same
commit (this is itself now one of the fragments:
`amendment-procedure-requires-single-commit`).

The "Scope" and the bulk of "Governance" narrative prose (the parts
describing the document's own applicability and amendment mechanics,
rather than stating a directive an agent session follows) are deliberately
NOT turned into fragments — they describe the constitution as a document,
not a behavior an agent enacts session to session.

While rewording the phasing-discipline bullet to remove content unrelated
to this change, its pointer to `docs/plans/2026-08-26-haex-hive-design.md`
was dropped: that document's "phase 0 → 7" model predates specs 007-023,
and the personal-agent-plane work it partly described has since split into
the separate `holzi` project. The underlying MUST-NOT-implement-ahead-of-
prerequisites rule is unchanged; only the stale citation is removed.

Per the Governance section's own PATCH/MINOR/MAJOR taxonomy, this is a
PATCH bump (1.4.1 → 1.4.2): a delivery-mechanism and citation change, not a
principle added, removed, or materially expanded. Same class of change as
ADR 0011's 1.4.0 → 1.4.1 rename bump.

The stale `haex-hive` source URL and stale revision pin in `.spaex.json`
are a separate follow-up (see below), not part of this commit: the new
revision can only be pinned to a commit that already exists on `main`,
i.e. after this PR merges.

## Consequences

**No principle content changes.** Every MUST/MUST NOT directive's
substance is preserved; only its packaging and, for one bullet, a stale
document citation, changed.

**This repo becomes the first real (non-test) consumer of the Spec 023
pipeline for its own constitution**, once `.spaex.json` is repointed in
the follow-up step. `spaex constitution show`/`.spaex.md` will then carry
per-fragment provenance for every directive, and any future fragment this
molecule adds will go through the same mechanical pre-check and Composer
conflict detection as an external molecule's fragments would.

**Fragment granularity is coarser than the Composer's single-clause
convention in places.** Several fragments (e.g.
`external-sources-opt-in-per-project`, `self-modifying-instructions-review-gated`)
bundle multiple related sentences drawn from sub-bullets under one
numbered principle, rather than splitting into one fragment per sentence.
This was a deliberate choice: the operator confirmed a fragment MAY
contribute more than one sentence, and splitting a principle's own
internal sub-clauses into separate fragments would scatter provenance for
what the source document treats as one cohesive rule.

## Alternatives considered

- **One fragment per sentence** (maximal granularity, matching the
  Composer's "one bullet per clause" contract as closely as possible):
  rejected per operator direction; would have produced 30+ fragments and
  fragmented provenance across sub-clauses that read as one rule in the
  source document.
- **Also fragment "Scope" and "Governance" narrative**: rejected. Those
  sections describe the constitution document itself (who it binds, how
  it is amended, how it is versioned) rather than a directive for an
  agent session to enact; the fragment model is for the latter.
- **Silently drop the stale `docs/plans/2026-08-26-haex-hive-design.md`
  citation without noting it**: rejected; called out explicitly here and
  in the Sync Impact Report so a reviewer can object if the phasing rule
  itself should also change, not just its citation.
- **Combine this migration with the `.spaex.json` source/revision fix in
  one PR**: rejected. The new revision must reference a commit that
  already exists on `main`; pinning to an unmerged branch commit is
  fragile (a rebase or force-push would invalidate it). Two-step: this PR
  publishes the fragments, a follow-up PR repoints `.spaex.json` at the
  post-merge `main` HEAD and re-runs `spaex install`.

## Follow-ups

- After this PR merges: update `.spaex.json`'s `compounds[0].source` from
  `https://github.com/haexmas/haex-hive` to `https://github.com/haexmas/spaex`
  and its `revision` to the merged commit SHA, then run `spaex install` to
  regenerate `.spaex/constitution.d/` and `.spaex.md`, replacing the
  now-superseded `.spaex/constitution.md` output (Spec 023 Phase 11 T063
  already tracks removing any orphan writer of that path).
- Extend this same source/revision fix to every other worktree of this
  repo carrying the same stale `.spaex.json` (they share the same tracked
  file; fixing it on `main` fixes all of them once each worktree is synced).
