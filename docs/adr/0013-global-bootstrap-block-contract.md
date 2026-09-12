# ADR 0013: Global Bootstrap Block Contract

**Status**: Accepted
**Date**: 2026-09-11
**Related**:
[Spec 023](../../specs/023-behavior-harness/);
[Spec 023 bootstrap-block contract](../../specs/023-behavior-harness/contracts/bootstrap-block.md);
[Spec 023 research §3](../../specs/023-behavior-harness/research.md);
`.specify/memory/constitution.md` §Principle V, §Principle VI

## Context

Every agent runtime spaex targets (Claude Code, Codex CLI, Gemini CLI, and
future runtimes) reads a global instruction file from a per-user location.
Spec 023 needs to install one short piece of content into each of those files
that tells the runtime to opt in when `<cwd>/.spaex/manifest.json` exists, then
look for `<cwd>/.spaex/constitution.md` (or any ancestor up to a git-root) and
treat it as the per-project constitution.

This content must be:

- Installable and upgradable without stomping unrelated content the user has
  authored in the same file.
- Removable cleanly on `spaex uninstall --global`, leaving the file in the
  same state as if spaex had never touched it (modulo unrelated edits made
  since).
- Uniform across runtimes (same text works for Claude, Codex, Gemini).
- Versioned in-place so a spaex release that changes the block content can
  upgrade without operator action.

## Decision

Use paired HTML comment markers with a version attribute on the opening
marker:

```markdown
<!-- spaex-bootstrap:start version="2" -->
...content...
<!-- spaex-bootstrap:end -->
```

The version attribute on the opening marker drives upgrade decisions. Content
outside the paired markers is preserved verbatim on every install, upgrade,
and uninstall. The exact target-path table per runtime is captured in
[research §3](../../specs/023-behavior-harness/research.md) and in
[bootstrap-block.md](../../specs/023-behavior-harness/contracts/bootstrap-block.md).

## Consequences

The global files remain user-owned. spaex changes only its marked block and
never writes project-level `CLAUDE.md`, `AGENTS.md`, or Spec-Kit files.

## Alternatives considered

The block is intentionally static and contains no project-specific content;
all project policy remains in `.spaex/constitution.md`.
