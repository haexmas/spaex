# ADR 0021: Delegate external skill installation to consumer-selected adapters

**Status**: Accepted; molecule-side contract implemented in PR #172, consumer-controlled installation remains pending
**Date**: 2026-09-14

## Context

Agent Skills distribution tools already own discovery and installation. spaex
owns pinned molecule composition and deterministic file publication, but it is
not a skill registry. Treating a registry reference as an ordinary atom path
would make spaex copy content it does not own and would make lockfile paths
misleading.

## Decision

Molecule manifests may declare a structured `external_skills` reference list.
The list is source metadata only. The consumer chooses the installer, target
agent, scope, and execution time through a persisted consumer policy and an
explicit skill-management operation. The referenced skill may live in the same
publisher repo as the molecule. The old `skill` and `skills` atom categories
are rejected.

spaex does not resolve registry references, pin their content, or install them
implicitly during normal `spaex install`. It may orchestrate an explicit
consumer-selected adapter without making that adapter a provider decision.

An explicit consumer-selected installer may read `external_skills` from the
original pinned molecule manifest. spaex exposes that existing manifest path
as `SPAEX_MOLECULE_MANIFEST`; it does not generate a temporary JSON payload for
the installer.

## Consequences

- Publisher manifests are intentionally breaking and target the spaex 5.x
  release line.
- External registry versioning remains outside `.spaex/install.lock`.
- No Node, uv, or registry SDK dependency is imposed on consumers by the
  provider manifest; the consumer chooses and supplies the adapter.
- Migration of publisher repositories is required before their next release.
