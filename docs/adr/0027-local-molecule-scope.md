# ADR 0027: Local (per-developer) molecule scope and per-checkout git exclusion

**Status**: Proposed
**Date**: 2026-10-12
**Related**: Spec 029 (local molecule scope), ADR 0013 (global bootstrap block), ADR 0026 (generic atom root write boundary)

## Context

Every adoption spaex knows about is recorded in the committed `.spaex/manifest.json`, and everything spaex installs from it is part of the shared repository state. A developer who wants harness content only for themselves (a personal guideline, an extra agent integration) must either impose it on the whole team or copy files by hand, unmanaged and easy to commit by accident.

Two existing invariants are affected:
1. Everything spaex writes is meant to be committed (the install lock, the composed constitution and generated files are all tracked).
2. spaex writes only inside the working tree: `.spaex/`, dot-directories, and, since ADR 0026, the repo root for exclusive generic atoms.

## Decision

1. **Second adoption scope.** spaex gains a `local` scope next to the default `project` scope. Local adoptions are recorded in `.spaex/local/manifest.json`. Everything local scope installs is recorded in `.spaex/local/install.lock` and is never committed.
2. **Project scope prevails.** A molecule adopted in both scopes is installed from project scope only. Local writes to project-owned or git-tracked paths are refused before anything is written. Local behavior rules are composed into a separate `.spaex/local/constitution.md`, which states that the project constitution prevails on conflict. Only one Spec Kit policy is active per checkout.
3. **One generation.** Both scopes publish in the same `.spaex` rename-swap generation, so crash safety and rollback stay a single mechanism.
4. **Extended write boundary.** To keep local outputs out of git without touching committed ignore files, spaex:
   - writes `.spaex/local/.gitignore` containing `*`;
   - maintains a marker-delimited, per-worktree block in git's per-clone exclude file (`git rev-parse --git-path info/exclude`).

   The exclude file is the first file spaex writes outside the working tree. spaex edits only its own block and refuses on malformed markers, like the bootstrap block of ADR 0013.
5. **Bootstrap block version 3.** Agents are told to read `.spaex/local/constitution.md` after the project constitution when it exists.

## Consequences

- A checkout without `.spaex/local/` behaves exactly as before; project outputs are byte-identical with or without local adoptions.
- Local harness content is not reviewed by the team. This is intended: it affects only the developer who adopted it, and only through an explicit operator command.
- `info/exclude` is shared by all worktrees of a clone. An entry added in one worktree also hides an untracked file at the same path in another. Accepted for now; per-worktree `core.excludesFile` via `extensions.worktreeConfig` is the upgrade path.
- Local hooks receive `SPAEX_SCOPE`; tracked or project-owned hook changes are refused, and newly created repository-local paths are captured in the local lock and exclusion block. Side effects outside the repository remain outside this feature's guarantee.
- An older spaex without this feature drops `.spaex/local/` on its next install, because it does not stage that directory.
- `spaex status` / `spaex trace` JSON output moves to `format_version: 2` (adds `scope`).

## Alternatives considered

- **Global per-user scope** (`$XDG_CONFIG_HOME/spaex/`, applied to every repo): rejected by the operator for this feature; per-checkout scope matches the "only me, only here" need without cross-repo side effects.
- **Editing the committed `.gitignore`**: rejected. It changes team-shared state, and `.gitignore` may itself be an exclusive atom of a project molecule.
- **Composing project and local behavior into one document**: rejected. The developer's copy of the team constitution would diverge, and every local change would recompose the team document.
