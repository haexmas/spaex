# Molecule install-hooks

**Introduced in**: spaex 4.1.0 (Spec 016)
**Authoritative sources**: [specs/016-molecule-install-hooks/spec.md](../specs/016-molecule-install-hooks/spec.md), [design doc](plans/2026-09-08-spec-016-molecule-install-hooks-design.md)

A molecule may declare an optional `install_hook` in its `manifest.json`. `spaex install` invokes each declared hook as a normal subprocess after any required atom materialization and before publishing the install.lock generation; hook-only molecules run without atom materialization. Hooks are the escape hatch for side effects that are not delivered files: appending `.gitignore` lines, registering git hooks, provisioning tools in the consumer repo, etc.

## Declaring a hook

Add an `install_hook` block to `manifest.json`:

```json
{
  "spaex_version": "4",
  "id": "com.example.my-molecule",
  "version": "1.0.0",
  "priority": 50,
  "atoms": {
    "constitution": ["constitution/preamble.md"]
  },
  "install_hook": {
    "interpreter": "python3",
    "script": "install.py",
    "args": [],
    "on_failure": "abort"
  }
}
```

Fields:

- `interpreter` (required): program name looked up on `$PATH` (e.g. `python3`, `bash`, `node`). spaex calls `shutil.which()` before spawning; a missing interpreter is a hook failure.
- `script` (required): molecule-directory-relative path to the hook file. spaex resolves it against the pinned molecule cache directory. The canonical path must stay inside that directory even through symlinks; escapes are refused at execution time on every invocation.
- `args` (optional): additional positional arguments passed after the script. Defaults to `[]`.
- `on_failure` (optional): `"abort"` or `"warn"`. Default `"abort"`. See failure policy below.

Hook-only molecules (declaring `install_hook` with no `atoms.constitution`) are supported. Their record lands in install.lock with `paths: []` and a `hook_status`.

## Execution semantics

- **Working directory**: the consumer repo root.
- **Environment**: spaex passes its complete environment to the subprocess, no filtering.
- **stdio**: inherited from the spaex process. In a TTY, hooks can prompt the user via `input()`; when stdin is unavailable or reaches EOF, `input()` raises `EOFError`, so molecule authors must supply a non-interactive fallback (e.g. `os.environ` toggle, `--yes` flag, `default_yes` behavior).
- **Ordering**: hooks run in the resolver's canonical order, which is ascending `(effective_priority, molecule_id.encode("utf-8"))`. The consumer's `.spaex/manifest.json` `compounds[].config[<molecule-id>].priority` overrides the publisher's default `priority`.

## Failure policy

spaex distinguishes four hook failure kinds:

1. **Non-zero exit** (`nonzero_exit`): the hook subprocess exits with a non-zero code.
2. **Missing interpreter** (`interpreter_not_on_path`): `shutil.which(interpreter)` returned `None`. spaex refuses to spawn.
3. **Path containment failure** (`path_containment_failure`): the resolved script path escapes the pinned molecule cache directory. spaex refuses to spawn.
4. **Process-launch OSError** (`process_launch_oserror`): the OS refused to start the subprocess (permission denied, resource exhaustion, ...).

Each failure is subject to the molecule's `on_failure` policy:

- `on_failure: "abort"` (default): halts execution, triggers Spec-008 install-transaction rollback (atoms discarded, install.lock not written, delegated `.spaex/manifest.json` update from `spaex add` reverted), raises `install-failed` with `molecule_id` and `hook_failure` in context. Exit code non-zero.
- `on_failure: "warn"`: records `hook_status: "failed"` for the molecule, emits ONE post-exit line on stderr (`WARN: molecule <id> install_hook failed (<reason>)`), continues with the next molecule, publishes install.lock as normal. Exit code 0. The hook's own stderr is never prefixed.

## Idempotency contract

Hooks MUST be safe to run repeatedly. spaex invokes them on every `spaex install`, not only on adopt (FR-024).

When atom bytes are unchanged AND every molecule's `hook_status` is unchanged, spaex publishes no new generation (clean no-op). A `hook_status` delta with unchanged atom bytes still publishes a new install.lock generation carrying only the delta (FR-025).

## Opt-out

Consumers can skip hook execution for a single invocation:

```bash
spaex install --no-install-hooks
# or on adopt:
spaex add https://example.com/repo my-molecule --no-install-hooks
```

Every declared hook records `hook_status: "skipped"` in install.lock; atoms still materialize. The flag is per-invocation. The next `spaex install` without the flag runs the hooks again.

Use it when auditing a molecule before letting its hook touch the repo, or in a sandboxed CI context where side effects must not happen.

## Non-reversibility

`spaex remove` cannot undo hook side effects. When removing a molecule whose install.lock record carries a `hook_status`, spaex emits:

```
WARN: molecule <id> had an install_hook; side effects (git hooks, gitignore entries, provisioned tools, agent-harness registrations) may remain. Consult the molecule's README for reverse steps.
```

The CLI exit code is unchanged. Molecule authors should document manual reverse steps in the molecule's README.

## install.lock record

Per-molecule records in `.spaex/install.lock` gain an optional `hook_status` field:

```json
{
  "id": "com.example.my-molecule",
  "source": "https://example.com/repo",
  "revision": "abc...def",
  "paths": ["constitution/preamble.md"],
  "hook_status": "ok"
}
```

Values: `"ok"`, `"failed"`, `"skipped"`. Emitted only when the molecule declares `install_hook` at the pinned revision. Absent for hookless molecules.

## Trust model

`install_hook` is arbitrary code executed with the invoking user's permissions. The review gate is the `spaex add --revision <sha>` decision itself: the consumer explicitly reviewed and pinned the publisher's SHA, which includes the full molecule cache (`install.py` and all). SHA pinning is spaex's immutability guarantee (constitution Principle IV). Consumers who cannot accept arbitrary hook execution should audit the pinned tree before adopting, or use `--no-install-hooks` and perform the equivalent setup manually.
