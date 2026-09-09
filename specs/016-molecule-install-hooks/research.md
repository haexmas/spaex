# Phase 0 Research: Molecule install-hooks in `spaex install`

**Feature**: 016 | **Date**: 2026-09-08

The feature was fully brainstormed with the operator on 2026-09-08 and captured in [docs/plans/2026-09-08-spec-016-molecule-install-hooks-design.md](../../docs/plans/2026-09-08-spec-016-molecule-install-hooks-design.md), then merged as PR #83 with review-driven refinements. Every decision below is a resolved product/technical choice, not a fresh research task. `NEEDS CLARIFICATION` markers from the plan template were resolved before this file was written; the single ambiguity surfaced by `/speckit-clarify` (env inheritance) is recorded in [spec.md's Clarifications section](./spec.md#clarifications).

## Trust model

- **Decision**: Pin-based trust. The consumer's decision to trust arbitrary publisher code is made once at pin time (`spaex add --revision <sha>`); hooks run automatically thereafter without per-invocation consent gates. Global `--no-install-hooks` opt-out. No sandboxing in v1.
- **Rationale**: Matches pip/npm postinstall precedent. The pinned 40-hex SHA is the single trust anchor and is what the consumer explicitly reviewed. Additional per-invocation gates (prompts, allow-lists) add friction without a corresponding security benefit while the underlying process model is unrestricted.
- **Alternatives considered**:
  - Prompt on first adoption per molecule (rejected: consent noise; the pin already IS the consent).
  - Per-molecule consumer allow-list in `.spaex.json` (rejected: YAGNI; nobody has asked for it; global opt-out sufficient).
  - Sandboxed hook execution via Spec 009 hook-boundary contract (rejected for v1: adds substantial implementation surface, blocks the concrete unblock — graphify-out gitignore — that motivated this spec).

## Environment variable inheritance

- **Decision**: Full inheritance. spaex passes its complete `os.environ` to the hook subprocess verbatim, with no allowlist filtering and no denylist redaction. Documented in FR-013.
- **Rationale**: Matches pip/npm postinstall behaviour. Realistic hooks like graphify-first-authoring's install.py need `PATH` (to invoke `pip`, `graphify`, `git`), `HOME` and `XDG_*` (for pip cache, agent-harness config discovery), `SSH_AUTH_SOCK` (git operations), and harness-specific tokens. Sanitising env while the process model is otherwise unrestricted would be security theatre — a malicious hook could just read `/proc/<parent>/environ` or `subprocess.run(["env"])` its parent shell.
- **Alternatives considered**:
  - Minimal allowlist (`PATH`, `HOME`, `LANG`, `TERM`) matching Spec 009 (rejected: breaks graphify install's real flow; theatre without matching sandbox).
  - Full inheritance minus a "secret-looking" denylist (`AWS_*`, `*_TOKEN`, `*_KEY`) (rejected: bypassable by renamed env var; breaks legitimate token uses like `HOMEBREW_GITHUB_API_TOKEN`).
  - Per-molecule declared passthrough (`install_hook.env: [...]`) (rejected: complexity without concrete v1 need).

## Discovery and declaration

- **Decision**: Manifest-declared, interpreter-hinted. New `install_hook: {interpreter: str, script: repo-relative-path, args?: [str], on_failure?: "abort"|"warn"}` field on molecule-manifest v4.
- **Rationale**: Explicit declaration lets a reviewer grep publisher-manifest history for `install_hook` and see every molecule that will execute code. Multi-language support falls out naturally (interpreter is any name on PATH). No hard-coded filename lock-in.
- **Alternatives considered**:
  - Convention: look for `install.py` if present (rejected: implicit; no way to see from the manifest which molecules run code).
  - Path-only field, spaex detects interpreter from extension (rejected: cross-platform interpreter detection is fragile; explicit is safer).

## Hook API

- **Decision**: cwd = consumer repo root, complete stdio inheritance, complete env inheritance. No positional args injection, no env-var injection (SPAEX_*), no stdin-JSON context. Hook uses `Path.cwd()` for consumer, `Path(__file__).parent` for its own molecule directory.
- **Rationale**: Additional injected context is speculative and expands the maintenance surface without concrete v1 need. Existing `graphify-first-authoring/install.py` follows exactly this convention and works unchanged.
- **Alternatives considered**:
  - Injected env vars (`SPAEX_REPO_ROOT`, `SPAEX_MOLECULE_ID`, `SPAEX_MOLECULE_DIR`, `SPAEX_INSTALL_PHASE`) (rejected: unused today; molecule authors have cwd + `__file__`).
  - Positional args (`[interpreter, script, "--molecule-dir", X, "--molecule-id", Y]`) (rejected: same reason).
  - stdin JSON payload (rejected: molecule authors would need to parse it; boilerplate for trivial scripts).

## Failure semantics

- **Decision**: Per-molecule `on_failure: "abort" | "warn"`. Default `"abort"`. `abort` triggers Spec-008 install-transaction rollback (staged atoms discarded, published generation preserved, install.lock not written, delegated `.spaex.json` compound-entry update reverted, CLI exits with existing `install-failed` diagnostic key at `src/spaex/cli/install.py:232`). `warn` records `hook_status: "failed"` in install.lock, spaex emits one post-exit `WARN:` line, exits 0.
- **Rationale**: Molecule authors know whether their hook is essential (gitignore-critical → abort) or best-effort (agent-harness registration → warn). Reusing the existing install-failed key avoids a new diagnostic key and keeps consumer error-handling paths unified.
- **Alternatives considered**:
  - Always abort (rejected: surprises molecule authors whose script is intentionally best-effort; blocks constitution adoption on a missing external CLI).
  - Always warn (rejected: consumer never learns a required setup step silently failed).
  - Configurable in consumer `.spaex.json` (rejected: molecule author is the correct authority on essential-vs-best-effort; consumer already has `--no-install-hooks` for global disable).

## Idempotency and re-run semantics

- **Decision**: Hook runs on every `spaex install` invocation (new adoption, revision bump, unchanged reinstall, manual rerun). Hook author is responsible for idempotency. When atom bytes are unchanged but resulting `hook_status` differs, spaex publishes a new install.lock generation carrying only the hook-status change (hook-only transaction). When both atom bytes and hook_status are unchanged, spaex performs a clean no-op after the hooks have run.
- **Rationale**: Simpler than tracking "last SHA that ran the hook"; self-healing on manual repo cleanup (deleted `.gitignore` → next install restores). Existing graphify-first-authoring/install.py is already idempotent (collision check, append-if-not-present, marker-based skip).
- **Alternatives considered**:
  - Run once per SHA, track in install.lock (rejected: no self-healing; more state).
  - Run only on first adoption (rejected: revision bumps could not roll out gitignore updates).

## Execution ordering

- **Decision**: All atoms materialise into the Spec-008 staging generation first. Hooks then execute in ascending effective-priority order, ties broken by ascending UTF-8 byte order of molecule id. `publish_constitution()` (or Spec-008 generalisation) seals `install.lock` and swaps the staging generation AFTER all hooks complete.
- **Rationale**: Hooks can assume all atoms are in place. Priority ordering matches the existing constitution-assembly rule, no new sort direction to learn. Publishing after hooks means `on_failure: "abort"` reaches the established rollback path before publication.
- **Alternatives considered**:
  - Hook runs before atoms (rejected: hook cannot read atom-materialised files if it wants to).
  - Both pre + post hooks (rejected: YAGNI; add `pre_install_hook` in a follow-up if a real case appears).
  - Publish then hook (rejected: hook failure could not roll back atoms).

## Resolver contract

- **Decision**: For every selected molecule, the resolver returns a `ResolvedMolecule` record, regardless of whether the molecule contributes an `atoms.constitution` entry. Records expose parsed `install_hook`, canonical source URL, pinned lowercase 40-hex revision, local bare-clone `repo_dir`, publisher-declared `molecule_path`, and effective priority (consumer override in `compounds[].config[<molecule-id>].priority` if present, publisher `manifest.priority` otherwise).
- **Rationale**: Without this rule, a hook-only molecule (one that ships only an install_hook, no atoms.constitution) would be dropped from the resolved collection and its hook never invoked. Constitution-only molecules and hook-only molecules must both flow through the same resolver path.
- **Alternatives considered**:
  - Filter resolved collection to molecules-with-atoms-constitution (rejected as a regression once hook-only molecules exist).

**2026-09-09 integration amendment**: T009 introduces this complete molecule-level record; the existing resolver only returns constitution contributions. The landed Spec 017 store MVP supplies the directory lazily when an enabled hook can run, using the resolved source, revision, `repo_dir`, and `molecule_path`. No pre-populated `cache_dir` is required. Spec 017's separate resolver migration T016–T021 is still pending; it will move molecule-manifest and constitution-body reads to the store while leaving publisher-root reads on `git_show`. This updates the earlier resolver-directory assumption in the source design without changing its execution-time containment requirement.

## Cache-containment for script path

- **Decision**: Before executing the hook, spaex canonicalises the resolved script path (follow symlinks, resolve `..`) and requires the result remains a descendant of the pinned molecule cache directory. Path-containment failure is a hook failure, subject to the molecule's `on_failure` policy.
- **Rationale**: Prevents a molecule from shipping a symlink named `install.py` that points at `/etc/shadow` or `~/.ssh/id_rsa`. The pinned SHA authenticates the publisher bytes; canonical containment is the separate execution-time boundary that prevents symlink escape.
- **Alternatives considered**:
  - Trust the SHA alone (rejected: a malicious publisher can commit a symlink that resolves outside the cache; SHA authenticates content but not target).
  - Refuse ANY symlink in the script path (rejected: legitimate cases exist, e.g. cross-directory reference within the molecule tree; containment check is the finer-grained rule).

## Manifest-model parsing rule

- **Decision**: `MoleculeManifest.from_json()` explicitly sets `install_hook.on_failure = "abort"` when the field is absent from the JSON, rather than relying on the JSON Schema's `default` metadata. Absent `install_hook` maps to `install_hook = None`.
- **Rationale**: JSON Schema `default` is documentation/validation metadata only. Different jsonschema library versions and configurations do not populate defaults into the parsed object. Relying on it produces silent behaviour drift if the library version changes. Explicit parser logic is portable and testable.
- **Alternatives considered**:
  - Use jsonschema library's `fill_defaults` mode (rejected: library-version-dependent behaviour; some versions do not support it).

## Non-goals (deferred)

Explicitly out of scope for spec 016, each documented in spec.md's "Out of scope" section with rationale:

- Declarative side-effect atom categories (`gitignore_lines`, `git_hooks`, `shell_provisioners`)
- Structured constitution composition (RFC-2119 severity metadata, mechanical assembly)
- Uninstall hooks (`uninstall_hook` mirror-symmetric to `install_hook`)
- Per-molecule timeout (`install_hook.timeout_seconds`)
- Pre-install hook (`install_hook` variant running before atom materialisation)
- Per-molecule consumer allow/deny lists (only global `--no-install-hooks`)
- Sandbox alignment with Spec 009

Each is a candidate for its own future spec if a real use case surfaces.

## Version bumps recorded here for the plan chain

- **spaex**: 4.0.1.dev0 → 4.1.0 (MINOR bump; additive feature; backwards-compatible schema addition).
- **molecule-manifest schema**: remains v4 (additive, non-breaking).
- **haexmas/atoms graphify-first-authoring**: 1.0.2 → 1.0.3 (PATCH bump; adds `install_hook` field pointing at existing install.py; no logic change in the script itself).
- **Consumers**: haex-crdt, specifyr, holzi repin to atoms-1.0.3 SHA once atoms lands.
