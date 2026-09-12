# ADR 0018: Orthogonal policy layers and canonical `.spaex/` directory

## Status

Accepted

## Context

spaex Atom fragments and Spec Kit's constitution serve different purposes.
Atom fragments describe repository and agent-harness rules; Spec Kit's
constitution describes how specifications are authored and delivered. Treating
the former as the latter made the two systems unnecessarily coupled.

The previous spaex layout also split project state across root-level files and
the `.spaex/` directory. That made ownership and atomic publication harder to
reason about, especially once the composed constitution became a generated
artifact.

## Decision

The policy layers remain independent and are loaded together:

- `.specify/memory/constitution.md` is owned by Spec Kit and contains only
  Spec-Kit principles.
- `.spaex/constitution.d/` contains the pinned Atom fragments, and
  `.spaex/constitution.md` is the generated spaex policy artifact. Atom rules
  are not copied into the Spec-Kit constitution.
- `.spaex/manifest.json` is the sole consumer manifest.
- `.spaex/manifest.json.lock`, `.spaex/install.lock`, and spaex behavior
  sidecars remain under `.spaex/`.

`spaex install --global` installs a small, runtime-specific bootstrap block in
the user's global instruction file. The block points runtimes at the active
project's `.spaex/constitution.md`; it does not write project-level
`CLAUDE.md`, `AGENTS.md`, or Spec-Kit files.

This is a clean cut. The removed root-level paths and the migration command
are not supported or detected. Existing consumers are updated explicitly by
the project owner rather than through a compatibility or migration layer.

Because `.spaex/` is published by rename-swap, the active manifest lock inode
is hard-linked into staged generations so the advisory lock remains effective
through a publication and recovery cycle.

## Consequences

Spec Kit and spaex can evolve and be invoked independently while both policy
layers remain visible to the agent session. Repository-local configuration is
discoverable in one directory, and the clean-cut boundary avoids ambiguous
precedence between legacy and canonical paths. The layout change is
intentionally breaking for consumers that still use the removed paths.
