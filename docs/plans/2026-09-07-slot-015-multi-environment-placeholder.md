# Spec 015 (placeholder): Multi-environment declaration and orchestration

**Status**: 2026-09-07 slot reservation. Design not yet started. Not to be implemented before Spec 014 (rename to spaex) lands and stabilizes.

**Purpose**: reserve the Spec 015 slot and record the product intent so it does not get lost while Spec 014 is in flight.

## Origin

Surfaced during Spec 014's `/speckit-clarify` session (2026-09-07, Q3). The clarification question was originally "what do we call the `dev_environment` atom category" and the answer was "Spec 014 makes no naming commitment because there are multiple environments (dev, staging, prod, ...) and the whole story deserves its own design."

## Product intent

Enable an operator to "bring the repo up in environment X" through spaex. This is bigger than static file placement; it is a runtime story.

**Sketch of the intended shape** (subject to full redesign when Spec 015 is opened):

- **Multi-environment vocabulary**: molecule authors can declare files scoped to a named environment (dev, staging, prod, plus custom names). Concrete carrier shape is a design decision: distinct atom-category keys (`env_dev`, `env_prod`), a nested structure under one key (`atoms.environments: {dev: [...], prod: [...]}`), or a separate top-level manifest section outside `atoms{}`.
- **Consumer-side selection**: something in the consumer's `.spaex.json` or in a runtime flag names the active environment. Only that environment's files get placed by `spaex install`, or files from all environments are placed under environment-specific paths.
- **Conflict handling**: `flake.nix` traditionally sits at the repo root; if two environments both contribute `flake.nix`, the tool needs a rule (path-prefixing, environment-symlinking, refusal).
- **Orchestration verbs**: `spaex enter [env]`, `spaex shell [env]`, `spaex dev up`, `spaex dev down`, or whatever proves ergonomic. Drives `nix develop`, `docker compose up`, `devcontainer up` under the hood based on which files the active environment contributes.

## Non-goals for Spec 015 (tentative)

- No cluster-orchestration story (kubernetes, terraform, etc.). Those are separate ecosystems and would deserve their own molecules or specs.
- No secrets management. Environment-config files that need secrets pull them from the operator's OS keychain per Principle I; that stays the same.
- No CI/CD story beyond "the environment-config files are placed correctly". Whether CI uses them is CI's problem.

## Dependencies

- Spec 014 must be landed first. Spec 015 builds on the v4 vocabulary and the `spaex install` publication contract.
- Constitution Principle II (no local absolute paths in versioned config) constrains any environment-selection persistence: the active-environment name must be device-independent.

## When to open Spec 015

- After Spec 014 lands and stabilizes (a few days of daily use without follow-up issues).
- When the operator has a concrete first use case that motivates the design (e.g., a specific `flake.nix` + `docker-compose.yml` pair they want to publish and consume).

Opening this spec too early risks over-designing for hypothetical uses; too late risks Spec 014's generic FR-043 becoming stale in the README.

## Placeholder acknowledgements

- The design source at `docs/plans/2026-09-07-rename-to-spaex-design.md` (Spec 014) originally reserved this slot as "dev-environment orchestration". This document expands the intent to multi-environment declaration plus orchestration.
- Spec 014's FR-043 forward-references this document in the README; keep the link intact when Spec 015 opens.
