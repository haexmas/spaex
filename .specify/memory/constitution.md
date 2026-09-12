<!--
Sync Impact Report (2026-09-12, orthogonal spaex policy layer)
Version change: 2.0.0 -> 1.0.0 (ownership reset: this file is now Spec-Kit-owned)
Modified sections:
- Removed spaex harness/security/governance principles from this file.
- Removed the requirement to mirror Atom fragments into this document.
- Removed spaex-specific reserved paths and configuration references.
- Established `.spaex/constitution.md` as the separate spaex policy artifact.

The former spaex rules remain active through the pinned Atom fragments under
`.spaex/constitution.d/`; they are not copied into this Spec-Kit constitution.
-->

# Spec Kit Constitution

Project-level principles for authoring and delivering specifications with Spec
Kit. The spaex policy layer is maintained separately under `.spaex/` and is
loaded alongside this document; neither constitution is derived from the
other.

## Core Principles

### I. Specifications Are the Product Contract

Every non-trivial feature MUST have a clear specification before planning and
implementation. The specification MUST describe user-visible behavior,
scope, constraints, and verifiable acceptance scenarios.

### II. Plans Must Be Traceable

An implementation plan MUST map the specification's requirements to concrete
design decisions, affected artifacts, and validation work. Unresolved
ambiguity MUST be clarified or explicitly recorded before implementation.

### III. Cross-Artifact Consistency Is Required

Specification, plan, task list, contracts, and checklists MUST remain mutually
consistent. A change to one artifact MUST update every dependent artifact or
record why no update is required.

### IV. Tasks Must Be Independently Verifiable

Tasks MUST have an observable outcome and identify the relevant test or
verification step. Implementation is complete only when the required checks
for the changed behavior pass.

### V. Scope Is Explicit

Every feature MUST state its goals, non-goals, and assumptions. Work outside
the agreed scope MUST be split into a separate feature or explicitly accepted
as a scope amendment.

## Workflow

- `/speckit-specify`, `/speckit-plan`, `/speckit-tasks`, and related commands
  MUST use the repository's `.specify/` templates and workflow configuration.
- `/speckit-plan` and `/speckit-analyze` MUST validate the Spec-Kit artifacts
  against this document.
- Architectural decisions that materially change the project's domain model
  or public interfaces SHOULD be recorded as ADRs under `docs/adr/`.

## Separation from spaex

The spaex behavior harness is a separate policy source. Its pinned Atom rules
are materialized under `.spaex/constitution.d/` and composed into
`.spaex/constitution.md`. They remain applicable to the agent session and
repository workflow, but MUST NOT be copied into or treated as amendments to
this document.

**Version**: 1.0.0 | **Ratified**: 2026-09-12 | **Last Amended**: 2026-09-12
