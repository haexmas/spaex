# `.specify/memory/`

`constitution.md` in this directory is spaex's own authoritative, human-readable
constitution. `manifest.json` is this molecule's v4 manifest
(`id: com.github.haexmas.spaex.constitution`); it declares the same
directives as Spec 023 behavior fragments under `atoms.behavior`, one file
per directive in `fragments/`. `spaex install` materializes those fragments
and composes them into a consumer's `.spaex.md`.

Amending a principle in `constitution.md` MUST update its corresponding
fragment file in the same commit (see `constitution.md` lines 57-61 and
the `amendment-mirrors-fragment-in-same-commit` fragment).
