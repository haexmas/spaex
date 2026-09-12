# ADR 0017: De-hivify the Constitution's Principles and Simplify the Amendment ADR Rule

**Status**: Accepted
**Date**: 2026-09-12
**Related**:
[Spec 023](../../specs/023-behavior-harness/);
ADR 0011 (rename to spaex, scope realignment away from the multi-device hive);
ADR 0014/0015/0016 (fragment split, fixups, relocation to `haexmas/atoms`);
`.specify/memory/constitution.md`

## Context

Reviewing the just-relocated `spaex-constitution` fragments in `haexmas/atoms`
against what they actually describe today surfaced two separate problems.

**Stale multi-device framing.** ADR 0011 already narrowed spaex's scope to
"one repo, one device"; the Nostr+iroh multi-device swarm vision moved to the
separate `holzi` project. But several Core Principles, ratified before that
narrowing (2026-08-26), still described that retired architecture:

- Principle VII ("Relay Unavailability Never Blocks Local Work") is entirely
  about the Nostr relay's liveness plane. `grep -rl "nostr\|relay" src/`
  returns nothing: there is no relay, and no code depends on one.
- Principles I, II, III, and IV's rationale each carried leftover framing
  ("OS keychain"/"NIP-44"/"the relay" in I, "per-device"/"satellites" in II,
  "device-pubkey"/"over the relay" in III, "satellite A"/"satellite B" in
  IV) describing a multi-device addressing scheme that plays no role in how
  spaex actually resolves anything.
- Not everything in that neighborhood is dead, though: Principle III's
  `.harness-id` mechanism is real and live
  (`src/spaex/io/state.py::default_state_root`, confirmed by reading the
  code before touching the principle), so the fix here is surgical removal
  of the inapplicable framing, not a wholesale gutting of principles I-IV.

**Disproportionate ADR requirement.** The Governance section required an ADR
for *every* amendment, unconditionally: "(a) an ADR in `docs/adr/`... (b) an
update to this file, and (c) explicit version bump... All three land in the
same commit." The Development Workflow section separately already required
an ADR "when a design decision materially affects any principle" — a more
reasonable, already-present threshold. The unconditional Governance rule
duplicated that, more strictly, and its own fragment mirror
(`amendment-procedure-requires-single-commit`) inherited the same
unconditional demand. In practice this produced three ADRs (0014, 0015,
0016) for what was mostly delivery-mechanism churn (self-publish, fix
fidelity regressions in that split, relocate to a different repo) — only
0014 and 0016 were genuinely architecturally significant; 0015 was really
just "fix mistakes 0014 introduced," forced into ADR shape by the
unconditional rule rather than because the correction itself was a new
decision worth its own record.

## Decision

**Constitution content** (`.specify/memory/constitution.md`, 1.4.4 → 2.0.0,
MAJOR because a principle is removed):

- Remove Principle VII entirely. Renumber old Principle VIII (No
  Concealment Instructions in Agent Output) to VII; its body is unchanged.
- Trim the multi-device/relay/satellite framing from Principles I, II,
  III, and IV's prose and rationale, keeping every still-enforced
  normative claim (never commit secrets, no absolute local paths, project
  identity via git remote URL or `.harness-id`, pin cross-repo references
  to an immutable SHA) exactly as strict as before. Nothing is relaxed;
  only inapplicable delivery-mechanism description is cut.
- Development Workflow: "8 principles" → "7". Governance's Enforcement
  bullet: drop its stale "once introduced under Phase 7" citation (the
  same retired haex-hive-design.md phasing model already delinked from
  the phasing-discipline bullet in the 1.4.2 amendment), keeping the
  honest "not yet mechanically enforced" framing without naming a dead
  phase.

**Amendment procedure simplified**: the Governance "Amendments" bullet no
longer unconditionally requires an ADR. It now requires (a) updating this
document and (b) bumping its version, in the same commit; an ADR is
additionally required exactly when the change materially affects a Core
Principle's substance, cross-referencing the Development Workflow's
existing rule instead of duplicating it at a stricter threshold. A pure
wording, typo, or non-semantic clarification fix does not need one.

**Matching fragment changes** (`haexmas/atoms`'
`spaex-constitution/fragments/`, same logical change per the
`amendment-mirrors-fragment-in-same-commit` rule):

- Remove `relay-unavailability-never-blocks-local-work.md` entirely.
- Reword `no-secrets-in-git`, `no-local-absolute-paths`,
  `device-independent-project-identity`, and
  `cross-repo-refs-pin-immutable-revisions` to match the trimmed
  principle text.
- Reword `constitution-enforcement-tooling` to drop the stale Phase-7
  citation.
- Reword `amendment-procedure-requires-single-commit` to drop its own
  unconditional ADR clause, since `adrs-for-principle-affecting-decisions`
  already covers that ground at the right threshold; this fragment now
  only says "update the doc and bump the version, same commit," with the
  ADR condition stated once, not twice.

Not physically split into a separate "generic engineering practices"
molecule at this time (a real alternative considered below): several
fragments here (`no-concealment-in-agent-output`,
`pr-required-for-main`, `merge-strategy-no-squash`,
`conventional-commit-messages`, and the four reworded above) carry no
spaex-specific content and could be adopted by an unrelated project
as-is. Deferred until a second consumer actually wants only that subset.

## Consequences

- The constitution describes what spaex actually is and does today, not
  what its predecessor project envisioned in August 2026 before the hive
  vision split into `holzi`.
- No principle's enforced behavior changes: this is a documentation-fidelity
  and packaging correction, not a policy relaxation, despite the MAJOR
  version bump (which the constitution's own rules require for any
  principle removal, dead or not).
- Future amendments that are pure wording/typo/clarification fixes (PATCH)
  no longer need a standalone ADR; only changes that materially affect a
  principle's substance do. This should reduce ADR churn for routine
  fragment-sync commits going forward.
- The generic-vs-spaex-specific fragment boundary is now easy to act on
  later (tags already distinguish them: `security`, `portability`,
  `workflow`, `git` vs. `governance`, `speckit`, `identity`) without
  having made a premature molecule split now.

## Alternatives considered

- **Keep Principle VII, just reword it generically** (e.g. "no critical
  dependency on a control-plane service"): rejected. There is no such
  service in spaex today; inventing a generic restatement of a rule with
  nothing to enforce would be constitution theater, not a real principle.
- **Split into two molecules now** (generic engineering-practice fragments
  in a new molecule, spaex-specific ones staying in `spaex-constitution`):
  rejected for now, per direct operator direction — YAGNI until a second
  consumer actually wants the generic subset alone; tags make the future
  split trivial when that happens.
- **Keep the unconditional ADR-per-amendment rule**: rejected per operator
  critique of this session's own ADR count (0014/0015/0016) — the
  Development Workflow's existing "materially affects a principle"
  threshold was already the right bar; the Governance rule just needed to
  stop duplicating it more strictly.

## Follow-ups

- None outstanding from this ADR itself. The matching `haexmas/atoms`
  fragment edits land in a PR referencing this one.
