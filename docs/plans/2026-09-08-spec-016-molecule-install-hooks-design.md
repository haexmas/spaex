# Spec 016 — Molecule install-hooks in `spaex install`

**Status**: Draft (design doc; spec/plan/tasks to be generated via `/speckit-specify`)
**Author**: brainstorming session 2026-09-08 with operator
**Target spaex version**: 4.1.0 (MINOR feature bump, backwards-compatible)

## Problem

Molecules today can only ship `atoms.<category>` declarations that `spaex install` copies verbatim into the consumer repo (currently `constitution`, `speckit_workflow`, `speckit_hooks`). Any side effect beyond file placement (append a line to `.gitignore`, install a git hook, provision an external CLI, register with an agent harness) has to live in a separate `install.py` next to the manifest, which `spaex install` does not know about and never executes.

Concrete case that triggered this spec: [`graphify-first-authoring`](https://github.com/haexmas/atoms/tree/main/graphify-first-authoring) ships an `install.py` that:
- Appends `graphify-out/` to `.gitignore`.
- Writes `post-commit` and `post-checkout` hooks into Git's effective hooks directory.
- Interactively offers to `pip install graphifyy` when the `graphify` CLI is missing.
- Runs `graphify install` (registers graphify with the operator's agent harness) when the local registration marker is absent.

Consumers of that molecule today (haex-crdt, specifyr, holzi as of 2026-09-08) get the constitution but **none** of the above — `spaex install` ignores `install.py`. Each consumer has to remember to run it by hand. In practice they miss steps: two of the three consumers ended up without the `graphify-out/` gitignore line until it was fixed manually per repo.

The fix: give `spaex install` a first-class way to invoke per-molecule setup scripts.

## Non-goals

- **No sandbox.** V1 hooks run as normal subprocesses with the consumer's user permissions. Same trust model as `pip install`'s post-install scripts. If concrete security incidents surface later, tighten via Spec 009 hook-boundary machinery in a follow-up spec.
- **No reversibility.** `spaex remove` cannot undo hook side effects. Documented explicitly. Consumers who want full reversibility should use a declarative tool (nix, terraform); spaex does not aspire to that in v1.
- **No pre-install hook.** Only post-atom-materialization. Add `pre_install_hook` later if a real use case appears.
- **No consumer-side per-molecule allow-list.** Trust is granted at pin time (`spaex add --revision <sha>`); once a compound is pinned, its hooks run on install. Global `--no-install-hooks` flag is the only opt-out for now.
- **No timeout.** Interactive hooks like `graphify install` prompt the operator; a hard-coded timeout would break them. Add per-molecule `timeout_seconds` later if runaway hooks become a problem.
- **No structured-constitution composition.** Separate concern, separate spec (deferred: see Follow-ups).

## Design decisions

Recorded from the brainstorming session (2026-09-08) with the operator, in the order they were settled.

### 1. Scope: arbitrary molecule setup scripts

Hooks may do anything a normal subprocess can. Same power as `pip install`'s post-install scripts. No spaex-imposed restrictions on what the script writes, spawns, or reads. Trust anchor is the 40-hex SHA the consumer pinned in `.spaex.json`.

### 2. Consent: permissive default with `--no-install-hooks` opt-out

`spaex add` and `spaex install` run declared hooks automatically. No prompt, no per-molecule allow-list, no first-adoption gate. The single escape hatch is the `--no-install-hooks` CLI flag on both commands. When set on `spaex add`, it implicitly passes through to the `spaex install` that `spaex add` triggers.

Rationale: v1 optimises for simplicity and matches pip/npm defaults. Tighten later based on concrete security experience, not preemptive design.

### 3. Discovery: manifest-declared, interpreter-hinted

Molecule authors declare hooks explicitly in `molecule-manifest.v4.schema.json`. Never convention-based (like "we look for `install.py` if it exists"), because:
- Explicit declaration lets a reviewer grep publisher-manifest history for `install_hook` and see every molecule that will execute code.
- Multi-language support is trivial (interpreter is just a name on PATH).
- No hard-coded filename lock-in.

### 4. Hook API: cwd only, no env/args/stdin injection

spaex runs the hook with `cwd = <consumer-repo-root>`. That's the only context passed. The hook uses `Path.cwd()` to find the consumer, `Path(__file__).parent` to find its own molecule directory. No `SPAEX_*` env vars, no positional args, no stdin JSON. The existing `graphify-first-authoring/install.py` follows this convention without modification.

Rationale from the brainstorming: additional context is speculative and adds a maintenance surface for both spaex and hook authors. When a concrete need arises (e.g. "the hook needs the molecule id to distinguish itself from another molecule"), add exactly that one thing then, not now.

### 5. Failure: per-molecule `on_failure: "abort" | "warn"`

The molecule author knows whether the hook is essential (gitignore of a critical directory → `abort`) or best-effort (register with an optional agent harness → `warn`). Default is `abort` (fail-loud).

- **`abort`**: hook exit != 0 (or interpreter missing on PATH) fails the entire `spaex install` transaction. Spec 008's install-transaction machinery rolls back atoms, `.spaex.json` is not touched. Consumer sees a clean no-op.
- **`warn`**: hook exit != 0 is logged to stderr with a `WARN:` prefix. Install continues, `.spaex/install.lock` is written with a per-molecule `hook_status: "failed"` field. `spaex install` exits 0.

### 6. Idempotency: hook runs on every install

The hook fires whenever `spaex install` runs — new adoption, revision bump, re-install with unchanged SHA, manual re-run. The molecule author is responsible for making the hook idempotent (only append gitignore lines that are absent, only write hook files that don't already exist, only run `graphify install` if no registration marker is present). The existing `graphify-first-authoring/install.py` is already built to this contract.

Rationale: simpler than tracking "last SHA that ran the hook" in install.lock. Self-healing on manual repo cleanup (if a user deletes `.gitignore`, the next `spaex install` restores the line).

### 7. Order: atoms first, then hook

Within a single molecule's install: atoms (files declared under `atoms.<category>`) are copied first, then the hook runs. The hook can assume all its atom-declared files are already in place, and can read them if needed.

### 8. Multi-molecule order: existing priority field

When multiple molecules with hooks are installed in the same `spaex install` run, they execute in the same priority order that spaex' constitution-assembly already uses (molecule `priority` field in the molecule manifest). Consistent with existing behaviour, no new ordering rule to learn.

## Schema changes

Additive extension to [`src/spaex/schema/data/molecule-manifest.v4.schema.json`](../../src/spaex/schema/data/molecule-manifest.v4.schema.json). Backwards-compatible: existing molecules without `install_hook` stay valid.

```json
"install_hook": {
  "type": "object",
  "additionalProperties": false,
  "required": ["interpreter", "script"],
  "properties": {
    "interpreter": {
      "type": "string",
      "minLength": 1,
      "description": "Program name on PATH (python3, bash, node, ...). spaex verifies existence via shutil.which before execution."
    },
    "script": {
      "$ref": "#/$defs/repoRelativePath",
      "description": "Molecule-directory-relative path to the hook script."
    },
    "args": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Additional positional args passed after the script. Optional."
    },
    "on_failure": {
      "enum": ["abort", "warn"],
      "default": "abort",
      "description": "abort: nonzero exit rolls back the install transaction. warn: nonzero exit is logged, install continues, install.lock records hook_status."
    }
  },
  "description": "Optional side-effect script that spaex install invokes after atoms materialization. Runs with cwd = consumer repo root, inherits stdio. Side effects are not reversible by spaex remove."
}
```

Concrete `install_hook` for the graphify-first-authoring bump to 1.0.3:

```json
"install_hook": {
  "interpreter": "python3",
  "script": "install.py",
  "on_failure": "warn"
}
```

`warn` because the existing install.py's essential path (constitution assembly) already happens via the `constitution` atom category before the hook runs; the hook's contribution (gitignore, hooks, graphify install) is opt-in enhancement, and a missing graphify CLI or detached HEAD should not block adoption.

No changes to `publisher-manifest.v4.schema.json` or `consumer-manifest.v4.schema.json`.

## Execution model

Within a single `spaex install` invocation:

1. spaex materialises every declared atom for every compound (unchanged from today).
2. Collects the list of molecules whose manifest declares an `install_hook`.
3. Sorts by molecule `priority` (same sort as constitution-assembly).
4. For each molecule with a hook:
   1. `shutil.which(interpreter)`. If missing on PATH, treat as hook failure per `on_failure`.
   2. Builds argv: `[interpreter, <molecule-cache-dir>/<script>, *args]`.
   3. `subprocess.run(argv, cwd=consumer_repo_root, check=False)` — **stdio inherited** from the spaex process (no `capture_output=True`). This lets the hook prompt interactively (`graphify install` needs this) and streams output live.
   4. Exit != 0 → applies `on_failure`.

`--no-install-hooks` on `spaex add` or `spaex install`: skip steps 2-4 entirely, record `hook_status: "skipped"` for each declared hook in install.lock.

## Failure handling

### `on_failure: "abort"` (default)

Hook non-zero exit (or interpreter missing) triggers the Spec-008 install-transaction rollback:
- Atoms already materialised are removed.
- `.spaex/install.lock` is not written.
- `.spaex.json`'s compound entry is not updated (or is reverted if this is an update).
- CLI exits with a distinct diagnostic key `install-hook-failed`, context includes the molecule id.

Note that hook stderr is not captured (stdio is inherited), so the diagnostic does not include stderr content. Operator sees the hook's terminal output above the spaex error line. Molecule authors who want structured logging can write their own log file within the consumer repo.

### `on_failure: "warn"`

- Hook stderr is logged with `WARN: molecule <id> install_hook exit <N>` (from spaex's own output, since hook output goes directly to the terminal).
- Install continues; `.spaex/install.lock` is written with `hook_status: "failed"` for this molecule.
- CLI exits 0.

### Rollback boundaries

Rollback only reverses what spaex wrote itself (atoms under `.spaex/`, compound entries in `.spaex.json`). **Hook side effects are not rolled back** — spaex does not know what the hook touched. Molecule authors must design hooks so that partial progress leaves a harmless state (the existing graphify install.py is built this way — it refuses collisions, never overwrites unrelated files).

Documented as a known limitation of this feature.

## Interactive hooks in CI

The `graphify-first-authoring/install.py` uses interactive prompts (`input()`) for consent to `pip install graphifyy` and to run `graphify install`. In non-interactive environments (CI, `spaex install < /dev/null`), `input()` raises `EOFError`. The existing install.py catches this and returns `default_yes=True`, so the hook still completes with sensible defaults in CI. Molecule authors should follow the same pattern.

## Testing

### Schema tests

Update `src/spaex/schema/tests/` (or the equivalent test module for molecule-manifest v4):
- Accepts the minimum `install_hook` (interpreter + script).
- Accepts the full form (with args and on_failure).
- Rejects missing `interpreter`, missing `script`, unknown top-level keys.
- Rejects non-object values (`"install_hook": "install.py"`, `"install_hook": null`) — verifies `type: object` is enforced.
- Rejects `on_failure` values outside `abort`/`warn`.
- Backwards-compat: a manifest without `install_hook` stays valid.

### Execution tests

Integration tests in `src/spaex/install/` (or wherever `spaex install` is tested today):
- Hook exit 0 → install.lock written with `hook_status: "ok"`.
- Hook exit 1 + `on_failure: "abort"` → transaction rollback, no install.lock, no compound entry.
- Hook exit 1 + `on_failure: "warn"` → install.lock written, `hook_status: "failed"`, exit 0, WARN in stderr.
- Interpreter missing on PATH → same as hook exit != 0, applies `on_failure`.
- `--no-install-hooks` → hook not invoked, install.lock records `hook_status: "skipped"`.
- Hook runs with cwd == consumer repo root (hook writes into `pwd`, test verifies file lands in consumer repo).
- Hook script path resolves against molecule-cache-dir, not consumer-repo-dir.
- Live output: hook that writes to stdout over multiple seconds is visible in the test's captured output as it happens (not buffered until process end).

### Multi-molecule tests

- Two molecules with hooks, priorities 10 and 20 → order matches spaex' existing priority sort (which one runs first depends on that sort's direction — verify consistent with constitution-assembly behaviour).
- One hook fails with `abort` in a multi-hook install → subsequent hooks are not invoked, rollback is total.

### Idempotency tests

- `spaex install` twice in succession → hook runs twice → no errors, no duplicated side effects. Fixture: use the actual graphify-first-authoring install.py as the hook, verify `.gitignore` only gains the line once.

### Publisher-side molecule test

After the atoms 1.0.3 bump, `graphify-first-authoring/tests/test_manifest_schema.py` must still pass — verifies that the vendored v4 schema accepts the new optional field.

## Version bumps and rollout

Ordered timeline:

1. **spaex** — implement Spec 016 (schema extension, execution, tests). Merge PR against `main`. Bump `pyproject.toml` version 4.0.1.dev0 → 4.1.0. Publish 4.1.0 to PyPI.
2. **atoms** — new PR against `haexmas/atoms/main` (branch-protected as of 2026-09-08). Adds `install_hook` field to `graphify-first-authoring/manifest.json`, bumps molecule to 1.0.3, bumps publisher root manifest's version pin for that molecule. CodeRabbit review, merge. Record new atoms SHA.
3. **Consumers** — in each of haex-crdt/specifyr/holzi: `spaex add --revision <atoms-1.0.3-sha> https://github.com/haexmas/atoms com.github.haexmas.atoms.graphify-first-authoring`. The manual `.gitignore` fix from 2026-09-08 becomes redundant (idempotent, harmless). Commit + push in the existing PR branches (specifyr chore/adopt-spaex #13, holzi chore/adopt-spaex #13, haex-crdt chore/update-spaex #18 — or fresh PR if those are already merged).

Migration for other existing molecules (`speckit-session-hopper`): no action required. `install_hook` is optional; molecules without it keep working unchanged.

## Documentation updates in the same spec PR

- `spaex install --help` and `spaex add --help`: document `--no-install-hooks`.
- `molecule-manifest.v4.schema.json` `description` field: mention `install_hook` and its known limitations (non-reversible, no timeout, no sandbox).
- Repo README or a dedicated `docs/install-hooks.md`: worked example (graphify-first-authoring pointing at its install.py), the idempotency contract, and the non-reversibility limitation.

## Known limitations (v1)

Documented as top-level constraints so consumers do not misinterpret the trust boundary:

- **`spaex remove` does not reverse hook side effects.** Consumers of a molecule with `install_hook` must consult that molecule's README for reverse steps. spaex `remove` emits a WARN reminding them of this.
- **No timeout.** A runaway hook blocks `spaex install` until manually interrupted. Add per-molecule `timeout_seconds` in a follow-up spec if this proves an issue.
- **No sandbox.** Hooks run as the consumer's user with full filesystem and network access. Trust anchor is the pinned 40-hex SHA of the publisher repo.
- **No pre-install hook.** Only post-atom-materialization. Add `pre_install_hook` in a follow-up if a real use case appears.
- **No per-consumer per-molecule allow-list.** Only a global `--no-install-hooks` flag. Add allow-lists later if consumers ask for finer control.

## Follow-ups (not part of Spec 016)

- **Declarative side-effect atom categories.** New atom-category keys (`gitignore_lines`, `git_hooks`, `shell_provisioners`) that `spaex install` can apply AND reverse deterministically. Would obsolete the `install_hook` field for common cases while keeping the hook as an escape hatch for edge cases. Separate spec.
- **Structured constitution composition.** Today's constitution-assembly does an LLM-merge when multiple molecules contribute — non-deterministic, can rewrite molecule authors' wording. Move to structured rule fragments with RFC-2119 severity metadata and mechanical assembly. Separate spec (raised by operator during this brainstorming; not part of 016).
- **Uninstall hooks.** Mirror-symmetric `uninstall_hook` for `spaex remove`. Same trust model as `install_hook`, same non-reversibility caveat. Add when consumers actually run `spaex remove` and hit the friction.
- **Spec 009 alignment.** If the sandbox story matures, `install_hook` could route through `haex hook run <trigger>` with the Spec 009 hook-boundary contract. Not v1.

## Related documents

- [Spec 007 — Unified Manifest v2 design](2026-08-28-spec-007-unified-manifest-design.md): established the atom-category model that this spec extends.
- [Spec 008 — Install Transaction requirements](2026-08-29-spec-008-install-transaction-requirements.md): rollback semantics that `on_failure: "abort"` relies on.
- [Spec 009 — Hook Boundary Contract](2026-08-29-spec-009-hook-boundary-requirements.md): pre-existing (but unimplemented) sandbox contract for `haex hook run`. This spec deliberately does NOT depend on it.
- [Spec 013 — CLI and molecule rename design](2026-09-02-spec-013-add-cli-and-molecule-rename-design.md): defined `spaex add` / `spaex install` command surface that this spec extends.
- [Spec 014 — Rename to spaex design](2026-09-07-rename-to-spaex-design.md): established v4 schema vocabulary that the new `install_hook` field extends.
