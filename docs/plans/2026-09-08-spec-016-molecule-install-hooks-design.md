# Spec 016 — Molecule install-hooks in `spaex install`

**Status**: Implementation in flight. Phases 1-6 landed on `main` as of 2026-09-09 (foundational schema/model/runner, US1 hook execution, US2 per-molecule failure policy, US3 `--no-install-hooks` opt-out, US4 multi-molecule ordering + hook-only molecules, PR #95). Remaining: Phase 7 (FR-025 hook-only transaction), Phase 8 (`spaex remove` WARN), Phase 9 (polish: `--help` docs, `README.md`, quickstart walk, schema-desc updates, backwards-compat validation, and the `pyproject.toml` bump to 4.1.0). See `specs/016-molecule-install-hooks/tasks.md` for the per-task status.
**Author**: brainstorming session 2026-09-08 with operator
**Target spaex version**: 4.1.0 (MINOR feature bump; molecule manifests remain
backwards-compatible, while the generated install-lock contract gains an
explicit hook-status revision as described below)

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

- **`abort`**: hook exit != 0, process-launch `OSError`, cache escape, or
  interpreter missing on PATH fails the entire `spaex install` transaction.
  Spec 008's install-transaction machinery rolls back staged atoms; a
  delegated `spaex add` also restores `.spaex.json`. The established
  `install-failed` result includes the molecule and failure kind. Hook side
  effects are not rolled back.
- **`warn`**: hook stderr remains inherited and unmodified. After the process
  exits, spaex may emit one post-exit `WARN:` line. Install continues,
  `.spaex/install.lock` is written with a per-molecule
  `hook_status: "failed"` field, and `spaex install` exits 0.

### 6. Idempotency: hook runs on every install

The hook fires whenever `spaex install` runs — new adoption, revision bump, re-install with unchanged SHA, manual re-run. The molecule author is responsible for making the hook idempotent (only append gitignore lines that are absent, only write hook files that don't already exist, only run `graphify install` if no registration marker is present). The existing `graphify-first-authoring/install.py` is already built to this contract.

Rationale: simpler than tracking "last SHA that ran the hook" in install.lock. Self-healing on manual repo cleanup (if a user deletes `.gitignore`, the next `spaex install` restores the line).

### 7. Order: atoms first, then hook

Within a single molecule's install: atoms (files declared under `atoms.<category>`) are copied first, then the hook runs. The hook can assume all its atom-declared files are already in place, and can read them if needed.

### 8. Multi-molecule order: existing resolver contract

When multiple molecules are resolved in the same `spaex install` run, hooks
execute in the resolver's canonical order: ascending **effective priority**,
then ascending molecule ID by its UTF-8 byte sequence. Effective priority is
`compounds[].config[<molecule-id>].priority` when the consumer supplies an
override, otherwise the publisher's `manifest.priority`. Thus the hook order
is the same deterministic order already used for constitution contributions;
there is no separate hook-only ordering rule. A priority override is part of
the install contract and is covered by the multi-molecule tests below.

The resolver must return one `ResolvedMolecule` record for every selected
molecule, not only for molecules that contribute `atoms.constitution`. The
record retains the molecule manifest, publisher source and revision, the
resolved immutable molecule-cache directory, and the effective priority. The
constitution contribution list is derived from this complete collection, so a
hook-only molecule is not dropped before hook execution. Duplicate IDs across
different source/revision pairs continue to be refused by the existing
resolver collision rule.

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
      "description": "Molecule-directory-relative path to the hook script; the resolved target must remain inside the pinned molecule cache even through symlinks."
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

### Manifest model and resolver contract

`MoleculeManifest` gains an optional `install_hook: InstallHook | None` field.
`InstallHook` contains exactly `interpreter`, `script`, `args`, and
`on_failure`. `from_json()` validates the v4 schema and constructs this value;
when `install_hook` is absent it stores `None`, and when the object is present
but omits `on_failure`, parsing explicitly stores `on_failure="abort"`. The
JSON-Schema `default` is documentation/validation metadata only and MUST NOT
be relied on to mutate parsed input.

The resolver exposes the parsed hook through each `ResolvedMolecule` record
alongside its source, full pinned revision, cache directory, and effective
priority. Hook execution consumes those resolved records; it MUST NOT re-read
or re-interpret the raw manifest later in the install transaction. This keeps
the change limited to manifest modelling, parsing, and resolution at this
layer, while preserving the established `None` representation for molecules
without a hook.

The script path has two independent checks. `RepoRelativePath` rejects empty,
absolute, and `.`/`..` path components during manifest parsing. At execution
time, spaex resolves the script against the extracted molecule cache for the
pinned revision and requires the canonical target to remain below that cache
root (`relative_to(cache_root)` succeeds). A symlink that points outside the
cache is refused with a path-containment failure; a symlink that remains
inside the cache is allowed. The cache is the immutable, revision-pinned
publisher tree used for the install, and no path under the consumer repository
is used as the script source. The pinned SHA authenticates the publisher
bytes; canonical containment is the separate execution-time boundary that
prevents a symlink from escaping it.

## Execution model

Within a single `spaex install` invocation:

1. spaex resolves the complete, sorted `ResolvedMolecule` collection and
   materialises every declared atom into the Spec-008 staging generation
   (`<root>.next`), not directly into the published root.
2. It derives the constitution payload and the hook candidate statuses from
   that same collection. A molecule with no `install_hook` remains in the
   resolved collection and in the generation's molecule records; it is simply
   skipped by the hook runner.
3. For each resolved molecule with a hook, in ascending effective priority
   and then UTF-8 molecule-ID order:
   1. `shutil.which(interpreter)`. If missing on PATH, treat as hook failure per `on_failure`.
   2. Resolve `<molecule-cache-dir>/<script>` and apply the canonical
      containment check described above. A path-containment failure is a hook
      failure, subject to the same policy.
   3. Build argv: `[interpreter, <molecule-cache-dir>/<script>, *args]`.
   4. Run `subprocess.run(argv, cwd=consumer_repo_root, check=False)` with
      **stdio inherited** from the spaex process (no `capture_output=True`).
      This lets the hook prompt interactively (`graphify install` needs this)
      and streams output live.
   5. A non-zero exit or an `OSError` raised while starting the process
      (including permission-denied and other launch failures) is a hook
      failure and applies `on_failure`.

Hooks run before the existing `publish_constitution(...)` commit (or its
generalized Spec-008 publisher) seals `install.lock` and swaps the staged
generation into place. An `abort` failure therefore reaches the established
install rollback path before publication. No hook is run after the commit.

The no-op path has one deliberate exception to the ordinary "no changes"
return: unchanged atom bytes MUST NOT cause hooks to be skipped. spaex first
determines whether the atom candidate is unchanged, then still runs every
declared hook for a new install, revision bump, unchanged reinstall, and
manual rerun. If the atom candidate is unchanged, the runner uses a hook-only
transaction: it does not rewrite atom files, but it may publish a new
`install.lock` generation when the resulting hook-status records differ. If
the atom candidate and hook-status records are both unchanged, it performs the
usual clean no-op after the hooks have run. An abort failure in this path does
not publish a new lock; a warn failure does.

`--no-install-hooks` on `spaex add` or `spaex install`: skip hook execution,
record `hook_status: "skipped"` for each declared hook in install.lock, and
still publish the atom generation when the atom candidate changed.

## Failure handling

### `on_failure: "abort"` (default)

Any non-zero exit, process-launch `OSError`, missing interpreter, or
cache-containment failure triggers the Spec-008 install-transaction rollback:
- Staged atom output is discarded and the previous published generation is
  retained.
- `.spaex/install.lock` is not written.
- `.spaex.json`'s compound entry is not updated (or is reverted if this is an
  update delegated through `spaex add`).
- CLI exits with the established `install-failed` result, with the molecule id
  and failure kind in context.

Hook stderr is not captured (stdio is inherited) and is written directly to
the terminal, byte-for-byte and without a `WARN:` prefix. The operator sees
it above the spaex error line. Molecule authors who want structured logging
can write their own log file within the consumer repo.

### `on_failure: "warn"`

- Hook stderr remains inherited and unmodified. After the process exits, spaex
  MAY emit one post-exit line such as `WARN: molecule <id> install_hook
  failed (<reason>)`; it MUST NOT prefix individual inherited stderr lines.
- Install continues; `.spaex/install.lock` is written with `hook_status: "failed"` for this molecule.
- CLI exits 0.

### Rollback boundaries

Rollback only reverses what spaex wrote itself (atoms under `.spaex/`, compound entries in `.spaex.json`). **Hook side effects are not rolled back** — spaex does not know what the hook touched. Molecule authors must design hooks so that partial progress leaves a harmless state (the existing graphify install.py is built this way — it refuses collisions, never overwrites unrelated files).

Documented as a known limitation of this feature.

## `install.lock` hook-status contract

The existing per-molecule record is extended with one optional field:

```json
{
  "id": "com.example.publisher.graphify-first-authoring",
  "source": "https://github.com/haexmas/atoms",
  "revision": "0123456789abcdef0123456789abcdef01234567",
  "paths": [".spaex/constitution.md"],
  "hook_status": "ok"
}
```

`hook_status` is present only when that molecule declares `install_hook` and
has one of exactly three values:

- `ok`: hook was enabled and exited 0;
- `failed`: hook was enabled but could not be launched, violated cache
  containment, or exited non-zero under `on_failure="warn"`;
- `skipped`: the global `--no-install-hooks` opt-out disabled it.

An omitted field means that the molecule declared no hook. An abort failure
never publishes a `failed` record because the generation is rolled back; the
previous lock (or no lock for a first install) remains authoritative. No hook
stderr, host-specific exception text, or interpreter path is persisted in the
lock.

Hook status is derived from the resolved molecule collection and the current
invocation flags, then sealed in the same transaction as the atom paths. The
existing canonical molecule ordering `(id, source, revision, paths)` remains
the ordering key; `hook_status` is not an additional sort key. A no-op
reinstall still executes hooks. If the resulting statuses equal the live lock,
the lock is not rewritten; if they differ (for example `ok` to `skipped`), the
hook-only transaction publishes a fresh generation with unchanged atom files.

Recovery discards an uncommitted staged lock together with its staged
generation and restores the retained previous generation before retrying. A
hook is rerun on that retry; status is never inferred from a partially written
lock. A status becomes durable only when its complete generation is published.

The molecule-manifest contract stays v4. The install-lock schema gets a
separately documented v4.1 shape in the 4.1 implementation: update
`install-lock.v4.schema.json`, `InstallLock`, and its runtime tests together;
keep `spaex_version: "4"` because it names the manifest major, and require
4.1-capable readers before consuming a generated lock containing
`hook_status`. Older strict readers may refuse such a lock with their normal
schema diagnostic and must not silently execute hooks from it. A future
incompatible lock change requires a new lock schema/version rather than
reinterpreting these three values.

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

- Two molecules with effective priorities 10 and 20 → the priority-10 hook
  runs first. Repeat with a consumer `config[<id>].priority` override that
  changes the publisher default and assert the override changes the order.
- Equal priorities → hook order is ascending by UTF-8 molecule ID, matching
  the constitution resolver contract.
- The resolver result passed to the hook runner retains every resolved
  molecule manifest and its effective priority, including a molecule with no
  constitution contribution; no contribution-derived single-molecule gate or
  `ConstitutionAlreadyAdoptedError` may discard the collection.
- One hook fails with `abort` in a multi-hook install → subsequent hooks are
  not invoked, rollback is total, and the established `install-failed` result
  is returned.

### Idempotency tests

- `spaex install` twice in succession → hook runs twice → no errors, no duplicated side effects. Fixture: use the actual graphify-first-authoring install.py as the hook, verify `.gitignore` only gains the line once.
- An unchanged install still runs the hook; atom files are not rewritten, and
  a changed hook status is persisted through the hook-only transaction.
- An omitted `on_failure` parses as `abort` and exercises rollback on a failing
  hook; this test must prove the runtime default rather than the schema
  annotation supplies it.
- A script symlinked outside the pinned molecule cache is refused before
  execution, while a symlink that resolves inside the cache is accepted.
- A process-launch `OSError` follows the same abort/warn matrix as a missing
  interpreter and a non-zero exit.

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
