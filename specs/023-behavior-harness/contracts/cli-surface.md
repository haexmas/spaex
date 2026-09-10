# Contract: CLI Surface

New and modified spaex CLI subcommands. Names finalized here; flag details in each subsection.

## New subcommands

### `spaex install --global [<runtime>[,<runtime>...]]`

Installs or upgrades the global bootstrap block into the specified runtimes' user-global instruction files.

**Arguments**:
- Positional: none.
- `--global`: required flag that switches the command into global-bootstrap mode. Without it, `spaex install` retains its existing per-project semantics.
- Optional argument list: comma-separated runtime names from `{claude, codex, gemini}`. If omitted, `spaex install --global` installs into all three.
- `--dry-run`: print the diff each target file would receive, do not write. (Detailed dry-run semantics deferred to a follow-up spec but the flag is reserved.)
- `--check`: exit 0 if all target blocks are already at the current version, exit non-zero otherwise. Suitable for CI verification.

**Exit codes**:
- 0: all requested targets are installed or upgraded to current version.
- 1: at least one target failed (permission, missing home dir, etc.). Diagnostic identifies which.
- 2: user passed unknown runtime name.

**Non-destructive contract**: content outside the paired HTML comment markers is preserved verbatim.

### `spaex constitution build`

Explicitly invokes the Composer against the current fragment set and writes `.spaex.md`. Rarely needed under normal workflow (auto-invoked by `spaex install`), but useful for CI verification and for consumers who want to regenerate without running a full install.

**Arguments**:
- `--force`: rerun even when the source_hash matches the current `.spaex.md`.
- `--check`: exit 0 if `.spaex.md` matches what the Composer would produce, exit non-zero otherwise (implies `--force` internally to compute the reference).

**Exit codes**:
- 0: `.spaex.md` produced or already current.
- 30: Composer timeout (research.md §8 categorization).
- 31: Composer runtime error.
- 32: Composer invalid output.
- 33: Composer quota exceeded.
- 34: No LLM runtime available.

### `spaex constitution trace <query>`

Prints the provenance for one or more clauses in `.spaex.md`.

**Arguments**:
- `<query>`: either a fragment id (`<molecule-id>/<fragment-id>`) or a substring of a clause text.
- `--format text|json`: output format. Default `text`.

**Exit codes**:
- 0: match found.
- 1: no match.

Sample output:

```text
Directive: "MUST run the project's test suite before creating any commit."
Modality:  MUST
Source:    strict-testing/tests-before-commit
Atom:      hooks.test-runner
Molecule:  github.com/haexmas/atoms@abc123 (pinned in .spaex.json)
```

## Modified subcommands

### `spaex install`

Existing per-project install. Extended to:
1. Materialize behavior fragments (new Phase 0.5 in the install pipeline, between molecule extraction and install-hook execution).
2. Run mechanical pre-check on fragments. Abort with new exit code 20 on intra-molecule conflict.
3. Invoke Composer if source_hash mismatches `.spaex.md`.
4. Emit new hint at end of install if the global bootstrap is not detected for any installed runtime.

**Backward compatibility**: consumers with no molecules shipping behavior fragments see the new phases skip silently (empty fragment set per FR-017d).

**New exit codes**:
- 20: intra-molecule fragment conflict (Case A per spec User Story 3).
- 21: cross-molecule semantic conflict not reconciled (Case B).
- 30-34: composer failures per research.md §8.
- 22: project attempt to modify an atom-provided fragment (spec FR-020).

### `spaex add <molecule-ref>` and `spaex remove <molecule-id>`

Existing commands. Extended per Clarification Q2:
- After adding/removing, if the resulting fragment set changes, invoke the Composer's plausibility check.
- On detected semantic contradiction: print WARN with provenance, mark `.spaex.md` state as "stale, unresolved" (a sidecar `.spaex/.stale` file with the failure summary), do NOT abort.
- On no contradiction: `.spaex.md` regenerates cleanly.

**No new exit codes**. Warnings do not change exit code semantics.

## Environment variables

- `SPAEX_LLM_MODEL`: override the auto-selected LLM model (litellm model id). Defaults to the runtime's canonical model.
- `SPAEX_COMPOSER_TIMEOUT`: composer timeout in seconds. Defaults to 30.
- `SPAEX_COMPOSER_LOG`: path to write raw Composer output on invalid-output failures. Defaults to `.spaex/composer.log`.

## Flags NOT introduced by this spec

The following are deferred to a follow-up spec (research.md §12, §13):

- `--allow-degraded`: opt-in fallback to raw fragment concatenation when Composer fails. Not in 4.2.0.
- `--scope contextual`: contextual-scope semantics on individual fragments. Not in 4.2.0.
- `spaex uninstall --global`: bootstrap-block removal. Documented in this contract because the removal path is defined, but a full spec-level treatment lives in the follow-up.
