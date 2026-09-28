# ADR 0018: Publisher Manifest Is an Index, Not a Second Version Source

**Status**: Accepted
**Date**: 2026-09-28
**Related**: ADR 0015; the v4 publisher and molecule manifest schemas

## Context

The v4 publisher manifest repeated every molecule's semantic version next to
its repository-relative path. The molecule manifest already carries that
version as part of the molecule's own contract. Keeping both values created a
second source of truth: a publisher update could change the molecule version
without changing the root index, making an otherwise valid pinned revision
unresolvable.

## Decision

The publisher manifest is an index from molecule ID to repository-relative
path. The molecule manifest is the sole source of truth for the molecule's
semantic version.

Spaex v4 continues to accept the legacy publisher-entry `version` field so
existing publishers remain readable, but it no longer requires or compares
that field. New publisher manifests SHOULD omit it.

## Consequences

- Publishers do not duplicate molecule versions.
- Existing v4 publisher manifests remain compatible during migration.
- A publisher's root manifest still declares which molecule IDs are exposed
  and where their manifests live.
- Release automation only needs to update the molecule manifest version.
