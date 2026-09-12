# `.specify/memory/`

`constitution.md` in this directory is the Spec-Kit constitution. Spec-Kit
tooling (`/speckit-plan`, `/speckit-constitution`, and related commands) reads
it directly as the product-specification policy layer.

spaex has a separate policy layer. Its pinned Atom fragments are consumed from
the project's `.spaex/manifest.json`, materialized under `.spaex/constitution.d/`,
and composed into `.spaex/constitution.md`. Those rules remain active for the
repository and agent session, but are not copied into this directory.
