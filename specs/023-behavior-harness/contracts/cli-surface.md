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

**Runtime target resolution**: `claude` uses its fixed target. `codex` resolves
`CODEX_HOME` (default `~/.codex`) and updates a non-empty
`AGENTS.override.md` when present, otherwise `AGENTS.md`. `gemini` reads
`~/.gemini/settings.json`; absent `context.fileName` means `GEMINI.md`, a
string selects one basename, and an array updates every configured basename.
Malformed configuration or path-bearing filenames fail before any target is
written.

### `spaex constitution build`

Explicitly invokes the Composer against the current fragment set and writes `.spaex.md`. Rarely needed under normal workflow (auto-invoked by `spaex install`), but useful for CI verification and for consumers who want to regenerate without running a full install.

**Arguments**:
- `--force`: rerun even when both the source and Composer-input fingerprints match the current `.spaex.md`.
- `--check`: exit 0 if `.spaex.md` matches the current source and Composer-input fingerprints, exit non-zero otherwise. With matching fingerprints it MUST NOT invoke the Composer; use `--force --check` when an explicit fresh Composer comparison is required.

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
- `<query>`: either an exact scoped fragment id (`<molecule-id>/<fragment-id>`) or a substring of a clause text. A bare `<fragment-id>` is not accepted, because it can be ambiguous across molecules.
- `--format text|json`: output format. Default `text`.

**Exit codes**:
- 0: match found.
- 1: no match or an unscoped/ambiguous fragment id.

Sample output:

```text
Directive: "MUST run the project's test suite before creating any commit."
Modality:  MUST
Sources:
  - strict-testing/tests-before-commit
    Atom:    hooks.test-runner
    Molecule: github.com/haexmas/atoms@abc123 (pinned in .spaex.json)
  - qa-baseline/tests-before-commit
    Atom:    qa.tests-before-commit
    Molecule: github.com/haexmas/qa-atoms@def456 (pinned in .spaex.json)
```

For a merged clause, text and JSON output list every provenance record; no
source is dropped when the clause is deduplicated.

## Modified subcommands

### `spaex install`

Existing per-project install. Extended to:
1. Materialize behavior fragments (new Phase 0.5 in the install pipeline, between molecule extraction and install-hook execution).
2. Run mechanical pre-check on fragments. Abort with new exit code 20 on intra-molecule conflict.
3. Compute the local `source_hash` for all canonical fragment records and a separate `build_input_hash` for the effective Composer prompt, prompt version, and all valid persisted clarification answers. Invoke Composer if either fingerprint mismatches `.spaex.md`; otherwise preserve the committed artifact byte-for-byte.
4. Emit new hint at end of install if the global bootstrap is not detected for any installed runtime.

**Backward compatibility**: consumers with no molecules shipping behavior fragments see the new phases skip silently (empty fragment set per FR-017d).

**New exit codes**:
- 20: intra-molecule fragment conflict (Case A per spec User Story 3).
- 21: cross-molecule semantic conflict not reconciled (Case B).
- 30-34: composer failures per research.md §8.
- 22: project attempt to modify an atom-provided fragment (spec FR-020).

**Non-destructive on abort** (per FR-006): on any of the above non-zero exit codes, `spaex install` MUST NOT modify any tracked file in the consumer repo. Existing `.spaex.md`, `.spaex/constitution.d/`, `.spaex/clarifications.json` remain as they were before the aborted run. Composer log at `$SPAEX_COMPOSER_LOG` (default `.spaex/composer.log`) MAY be written for failure categories 32/34 as diagnostic; that path is documented and gitignored.

**Never writes to** (per FR-017c): `spaex install` NEVER writes to project-level `CLAUDE.md`, `AGENTS.md`, or any other operator-authored instruction file at the project level, under any exit code. Emission is confined to `.spaex.md` at the repo root and to files under `.spaex/`.

### `spaex add <molecule-ref>` and `spaex remove <molecule-id>`

Existing commands. Extended per Clarification Q2:
- After adding/removing, if the resulting fragment set changes, invoke the Composer's plausibility check.
- On detected semantic contradiction: print WARN with provenance, mark `.spaex.md` state as "stale, unresolved" (a sidecar `.spaex/.stale` file with the failure summary), do NOT abort.
- On no contradiction: `.spaex.md` regenerates cleanly.

**No new exit codes**. Warnings do not change exit code semantics.

**No `.spaex.md` regeneration from a detected contradiction** (per FR-024a). When the plausibility check finds a cross-molecule semantic contradiction, it produces WARN output and writes/updates a `.spaex/.stale` sidecar file summarizing the finding, and `.spaex.md` is left as-is; regeneration happens at the next `spaex install`, which reads `.spaex/.stale` and requires reconciliation before writing. This applies only to the contradiction case — `spaex add`/`spaex remove` otherwise complete a full install exactly like `spaex install` would, including a clean `.spaex.md` regeneration (line above).

## Environment variables

- `SPAEX_LLM_MODEL`: override the auto-selected LLM model (litellm model id). Defaults to the runtime's canonical model.
- `SPAEX_COMPOSER_TIMEOUT`: composer timeout in seconds. Defaults to 30.
- `SPAEX_COMPOSER_LOG`: path to write raw Composer output on invalid-output failures. Defaults to `.spaex/composer.log`.

## Flags NOT introduced by this spec

The following are deferred to a follow-up spec (research.md §12, §13):

- `--allow-degraded`: opt-in fallback to raw fragment concatenation when Composer fails. Not in 4.2.0.
- `--scope contextual`: contextual-scope semantics on individual fragments. Not in 4.2.0.
- `spaex uninstall --global`: bootstrap-block removal. Documented in this contract because the removal path is defined, but a full spec-level treatment lives in the follow-up.
