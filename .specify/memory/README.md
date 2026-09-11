# `.specify/memory/`

`constitution.md` in this directory is spaex's own authoritative,
human-readable constitution. This is where speckit tooling
(`/speckit-plan`, `/speckit-constitution`, etc.) reads it from directly.

The machine-composable Spec 023 behavior-fragment derivative (one file per
directive, materialized and composed by `spaex install`) used to be
self-published from here as `com.github.haexmas.spaex.constitution`
(ADR 0014/0015). It has since moved to the `haexmas/atoms` publisher as
`com.github.haexmas.atoms.spaex-constitution` (ADR 0016); spaex now
consumes it via its own `.spaex.json` like any other consumer would,
instead of self-publishing it.

Amending a principle here MUST update the corresponding fragment file in
`haexmas/atoms`' `spaex-constitution/fragments/` in the same logical
change (see constitution.md's own Governance section).
