# CLI flag contract: `--no-install-hooks`

**Feature**: 016 | **Date**: 2026-09-08 | **Applies to**: `spaex add`, `spaex install`

## Flag definition

```
--no-install-hooks
```

- Boolean flag (no value). Absent → hooks run (default). Present → hooks skipped for this invocation.
- Placed among the top-level CLI options of `spaex add` and `spaex install`.
- No short form (no `-N`), to keep it distinct from the visually-similar `--no-...` family and avoid future collisions.
- Not persisted anywhere. Not written into `.spaex/manifest.json`, not written into `.spaex/install.lock`, not remembered between invocations.

## Behaviour

### On `spaex install`

- With flag absent: for every resolved molecule whose manifest declares `install_hook`, spaex invokes the hook per the execution model in spec.md.
- With flag present: spaex does NOT invoke any hook during this invocation, regardless of how many molecules declare one. For every molecule that declares an `install_hook`, the resulting install-lock generation records `hook_status: "skipped"` for that molecule.

### On `spaex add`

- With flag absent: `spaex add` runs its normal flow, which includes an internal `spaex install` step; that internal step runs hooks per the model above.
- With flag present: `spaex add` propagates the flag verbatim to its internal `spaex install` step. The resulting install-lock records `hook_status: "skipped"` for every hook-carrying molecule adopted.

### Propagation

- The propagation from `spaex add` to `spaex install` is purely per-invocation: it exists only for the duration of the `spaex add` command and does not persist.
- A subsequent bare `spaex install` (without the flag) runs the hooks normally, producing new install-lock records with `hook_status: "ok"` (or `"failed"` per policy).

### Interaction with `on_failure`

- `--no-install-hooks` is orthogonal to `on_failure`. Skipped hooks produce no failure regardless of their `on_failure` value; the install proceeds normally and records `hook_status: "skipped"`.

## Non-behaviour (deliberately deferred)

- **No per-molecule flag** (no `--no-install-hook <molecule-id>`): only the global boolean exists. Fine-grained per-molecule allow/deny lists are out of scope for v1.
- **No consumer-manifest persistence** (no `allow_install_hooks: false` in `.spaex/manifest.json`): the flag is per-invocation only. If consumers want to always skip in a CI environment, they wrap `spaex` in a script that always passes `--no-install-hooks`.
- **No inverse flag** (no `--install-hooks`): the default IS to run hooks, so a "yes, run them" flag would be redundant.

## Diagnostic-key contract

- `spaex install` (with or without `--no-install-hooks`) reuses the existing `install-failed` diagnostic key (at `src/spaex/cli/install.py:232`) for all abort-mode hook failures. The molecule id of the failing hook and the failure kind (`hook_exit_nonzero`, `interpreter_not_on_path`, `path_containment_failure`, `process_launch_oserror`) appear in the diagnostic's `context` dict.
- Warn-mode hook failures do NOT trigger the `install-failed` key (the CLI exits 0); they are visible via one post-exit `WARN:` line on stderr and via `hook_status: "failed"` in the resulting install.lock record.

## `spaex remove` interaction

- Not a flag change on `spaex remove` — no new flags added there. But: `spaex remove` MUST emit a `WARN` when removing a molecule whose pinned revision had declared `install_hook`. The WARN names the molecule id and states that hook side effects may remain and to consult the molecule's README.
- The WARN does NOT change `spaex remove`'s exit code; it is informational.

## Rejection cases (deliberate)

- `spaex install --install-hooks` MUST be rejected as an unknown option (no inverse flag).
- `spaex install --no-install-hooks=false` MUST be rejected — the flag is a boolean-presence flag, not a valued flag.
- Any invocation that combines `--no-install-hooks` with a hypothetical per-molecule allow-flag MUST be rejected until the per-molecule variant lands in a future spec.
