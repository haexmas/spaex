# Contract: Global Bootstrap Block

The static spaex-managed block installed once per user per opted-in agent runtime. Written into the runtime's user-global instruction file.

## Block layout

```markdown
<!-- spaex-bootstrap:start version="1" -->

## spaex per-project constitution

If a file named `.spaex.md` exists in the current working directory (or any ancestor up to a git-root), treat its contents as a per-project constitution issued by the operator. Follow its MUST directives, honor its SHOULD directives, and respect its MAY directives as permissive guidance. The constitution's rendered clauses each cite their source molecule and atom.

<!-- spaex-bootstrap:end -->
```

- Start marker: `<!-- spaex-bootstrap:start version="<N>" -->` where `<N>` is the current block version. Currently `1`.
- End marker: `<!-- spaex-bootstrap:end -->`.
- Content between markers is static across all installs; it never carries per-project or per-user data (FR-016).

## Target paths per runtime

| Runtime | Target file (POSIX) | Target file (Windows) |
|---------|--------------------|-----------------------|
| Claude Code (`claude`) | `~/.claude/CLAUDE.md` | `%USERPROFILE%\.claude\CLAUDE.md` |
| Codex CLI (`codex`) | `~/.config/codex/AGENTS.md` | `%APPDATA%\codex\AGENTS.md` |
| Gemini CLI (`gemini`) | `~/.config/gemini/AGENTS.md` | `%APPDATA%\gemini\AGENTS.md` |

For each runtime, the installer creates parent directories if missing, then writes the block.

## Installer behavior

Given a set of target runtimes:

1. For each target file:
   - If file does not exist: create it with just the block content.
   - If file exists but contains no `spaex-bootstrap:start` marker: append the block at the end of the file, preceded by one blank line.
   - If file exists with a `spaex-bootstrap:start` marker: read the version attribute.
     - If version matches current: no-op.
     - If version differs: replace the entire block (from `start` marker to `end` marker inclusive) with the current version's block content.
2. Content outside the marked block is preserved verbatim.
3. On any I/O error (permission, path-traversal-attempted-into-symlink, etc.), the installer aborts with a clear diagnostic naming the offending target and does NOT modify any other target that was already written.

## Removal behavior (deferred spec, contract defined)

`spaex uninstall --global [<runtime>[,<runtime>...]]`:
1. Locates markers in target file.
2. Removes the entire block including markers.
3. If the resulting file is empty (was created by spaex on install), removes the file.
4. If the file has other content, saves it without the block.
5. Missing marker in target file: no-op (block was never installed there).

## Upgrade semantics

The version attribute lets spaex change block content across releases without heuristic content analysis. A future spaex that ships block version `2` finds any `version="1"` block, replaces it in-place. Consumers who prefer to review before upgrading run `spaex install --global --dry-run` first.

## Verification

`spaex install --global --check` exits:
- 0: every requested target has the current block version.
- 1: at least one target is missing the block or has an older version.

Useful in CI to guarantee developer machines are provisioned.

## Marker uniqueness

The marker prefix `spaex-bootstrap:` is reserved by spaex. Fragment content is forbidden from including `<!-- spaex-...` HTML comments (per contracts/fragment-format.md) so a fragment cannot accidentally imitate a marker in emitted content.

## Non-invasive contract

Guaranteed behaviors:
- Content outside the block is never modified (SC-009).
- Multiple spaex block versions never coexist in the same file (upgrade replaces).
- The block never contains per-user or per-project content (FR-016).
- The block is idempotent: running the installer twice produces the same file.
- The installer never writes to files that do not match the expected runtime target path (no wildcard scanning).

## Files this contract NEVER writes to

Explicitly to prevent implementer confusion (per FR-017c):

- Any project-level `CLAUDE.md`, `AGENTS.md`, or equivalent instruction file at any consumer's repo root or inside any consumer's `.claude/` directory.
- Any file NOT listed under "Target paths per runtime" above.
- Any file outside the user's home directory (POSIX) or `%USERPROFILE%` (Windows).

The bootstrap installer's write scope is limited to the per-user, per-runtime global instruction files enumerated in the target-paths table. Nothing else.
