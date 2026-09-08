# Feature Specification: Molecule install-hooks in `spaex install`

**Feature Branch**: `016-molecule-install-hooks`
**Created**: 2026-09-08
**Status**: Draft
**Input**: User description: "Spec 016: Molecule install-hooks in spaex install. Full design already captured in docs/plans/2026-09-08-spec-016-molecule-install-hooks-design.md (PR #83 merged 2026-09-08)."
**Design reference**: [docs/plans/2026-09-08-spec-016-molecule-install-hooks-design.md](../../docs/plans/2026-09-08-spec-016-molecule-install-hooks-design.md)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Molecule author ships a setup script that spaex runs on adopt (Priority: P1)

A molecule author needs to configure the consumer repository beyond simply copying files: append a line to `.gitignore`, install git hooks, provision an external CLI, register with an agent harness. Today they ship an `install.py` next to the manifest, but `spaex install` never invokes it, and every consumer has to remember to run it by hand. Consumers routinely miss this step.

With Story 1 landed, the molecule author declares one field in their manifest pointing at the script; `spaex install` invokes it after atoms are materialised. The consumer runs `spaex add <source> <molecule>` once and the molecule's full setup happens, including any interactive prompts the script needs (e.g. "install graphify CLI now? [Y/n]").

**Why this priority**: this is the whole point of the feature. Without Story 1 the gap that motivated Spec 016 is not closed. The concrete downstream unblock is graphify-first-authoring 1.0.3, which lets three current consumers (haex-crdt, specifyr, holzi) stop maintaining a manual `.gitignore` line per repo.

**Independent Test**: create a fresh consumer repo with a seed `.spaex.json`; publish a minimal molecule whose manifest declares `install_hook` pointing at a script that writes a marker file into the consumer repo; run `spaex add`; verify the marker file exists in the consumer repo after `spaex add` returns.

**Acceptance Scenarios**:

1. **Given** a molecule with `install_hook: {interpreter: "python3", script: "install.py"}` and an `install.py` that appends "graphify-out/" to `.gitignore`, **When** the consumer runs `spaex add <source> <molecule-id> --revision <sha>` in a repo whose `.gitignore` does not yet contain that line, **Then** after the command completes, `.gitignore` contains `graphify-out/` exactly once, `.spaex/constitution.md` is materialised as before, and `.spaex/install.lock` records the molecule with `hook_status: "ok"`.
2. **Given** the same molecule and consumer, **When** the consumer runs `spaex install` a second time, **Then** the hook runs again, `.gitignore` still contains `graphify-out/` exactly once (no duplicate), and `install.lock`'s `hook_status` stays `"ok"`.
3. **Given** the same molecule, **When** the consumer runs `spaex add` in a terminal that supports interactive input and the hook calls `input("proceed? ")`, **Then** the prompt appears live on the operator's terminal, the operator's typed answer reaches the hook, and installation proceeds based on the answer.

---

### User Story 2 - Hook failure is handled by the molecule author's declared policy (Priority: P2)

A molecule author needs different failure semantics depending on how essential their hook is. A gitignore-critical hook should abort the install if it cannot complete, consumers should not adopt a molecule whose baseline hygiene is broken. A best-effort hook (register with an optional agent harness) should log a warning and let the constitution still land, so a missing dependency does not block adoption.

**Why this priority**: without Story 2, every hook failure is either always fatal (surprises molecule authors whose script is intentionally best-effort) or always ignored (surprises consumers who never get told a required hook failed). Both defaults produce broken adoption experiences. Story 2 makes the policy explicit at the molecule level.

**Independent Test**: publish two molecules, one with `on_failure: "abort"` and one with `on_failure: "warn"`, both pointing at scripts that exit non-zero. Verify `spaex add` of the abort-molecule rolls back all writes; verify `spaex add` of the warn-molecule completes with `hook_status: "failed"` in install.lock and exit code 0.

**Acceptance Scenarios**:

1. **Given** a molecule declaring `install_hook: {..., on_failure: "abort"}` and a script that exits 1, **When** the consumer runs `spaex add`, **Then** no atoms remain materialised in `.spaex/`, `.spaex/install.lock` is not written, `.spaex.json` is unchanged (compound not added), the CLI exits non-zero with the `install-failed` diagnostic key, and the diagnostic context names the molecule id.
2. **Given** a molecule declaring `install_hook: {..., on_failure: "warn"}` and a script that exits 1, **When** the consumer runs `spaex add`, **Then** atoms are materialised, `.spaex/install.lock` is written with `hook_status: "failed"` for that molecule, one post-exit `WARN:` line appears on the operator's terminal, and the CLI exits 0.
3. **Given** a molecule declaring `install_hook` whose `interpreter` value is not on the operator's `PATH`, **When** the consumer runs `spaex add`, **Then** the outcome matches the same molecule's `on_failure` policy exactly as if the script had exited non-zero.

---

### User Story 3 - Consumer opts out of all install-hooks globally (Priority: P3)

A consumer running in a locked-down environment (CI, air-gapped machine, review-mode) needs a way to run `spaex add` and `spaex install` without executing any publisher-authored code. They accept that hook-dependent setup (git hooks, gitignore lines, external CLI installs) will not happen and are willing to handle it manually.

**Why this priority**: hooks are useful defaults for the common case, but the operator must have an escape hatch. Without Story 3 there is no way to adopt a molecule for its constitution alone in an environment where arbitrary code execution is unacceptable. Priority is P3 because most operators will not need it; CI adopters and security-conscious teams will.

**Independent Test**: publish a molecule whose hook writes a marker file. Run `spaex add --no-install-hooks`. Verify the marker file does not appear, atoms are still materialised, and install.lock records the molecule with `hook_status: "skipped"`.

**Acceptance Scenarios**:

1. **Given** a molecule with an install_hook that would ordinarily write a marker file, **When** the consumer runs `spaex add --no-install-hooks`, **Then** the marker file is not created, atoms are still materialised, `.spaex/install.lock` records `hook_status: "skipped"` for that molecule, and the CLI exits 0.
2. **Given** the same molecule, **When** the consumer runs `spaex install --no-install-hooks` after a prior `spaex add`, **Then** the same skip behaviour applies to this invocation, and a subsequent `spaex install` without the flag runs the hook (skip is per-invocation, not sticky in `.spaex.json`).

---

### User Story 4 - Multiple molecules with hooks execute in a deterministic order (Priority: P3)

When a consumer adopts several molecules in one project, each with its own install_hook, the operator needs to know in what order the hooks run. Order matters when one molecule's hook prepares state that another's expects (git hook directory, PATH entries, gitignore layout). Without a documented rule the order could depend on filesystem enumeration, dictionary iteration, or other opaque factors.

**Why this priority**: needed for correctness once more than one hook-carrying molecule exists in the ecosystem. Priority P3 because today only one such molecule (graphify-first-authoring) exists; friction rises as the ecosystem grows.

**Independent Test**: publish two molecules with hooks, priorities 10 and 20, whose scripts each append a distinct line to a shared log file in the consumer repo. Adopt both. Verify the log file's line order matches the documented rule.

**Acceptance Scenarios**:

1. **Given** two adopted molecules with priorities 10 and 20 whose hooks each write their own molecule id into a shared log, **When** the consumer runs `spaex install`, **Then** the log's line order matches ascending effective priority (10 before 20) and, when priorities tie, ascending UTF-8 byte order of molecule id.
2. **Given** a molecule whose manifest declares an install_hook but no `atoms.constitution` contribution, **When** the consumer adopts it, **Then** the resolver retains the molecule in its resolved collection and the hook still runs (not dropped for lacking a constitution atom).
3. **Given** three molecules with hooks and one of them declares `on_failure: "abort"` and exits non-zero, **When** the consumer runs `spaex install`, **Then** hook execution stops at the failure, later-ordered hooks do not run, and the transaction rollback removes all atoms staged in this invocation.

---

### Edge Cases

- **Hook script points outside the pinned molecule cache via symlink**: the script path is canonicalised at execution time and must resolve to a target under the pinned molecule cache. A symlink that escapes the cache produces the same failure as `on_failure` (path-containment failure).
- **Hook attempts an interactive prompt in a non-TTY environment (CI, piped stdin)**: `input()` in the hook raises `EOFError`. Molecule authors are expected to catch and fall back to a sensible default (the reference implementation in graphify-first-authoring/install.py already does). spaex does not synthesise a stdin.
- **Hook runs indefinitely**: v1 imposes no timeout. Operator interrupts with Ctrl+C. `spaex install` treats the resulting signal exit as a hook failure per `on_failure`. Documented as a limitation; per-molecule `timeout_seconds` may be added later.
- **Consumer deletes `.gitignore` between installs**: on the next `spaex install`, the hook runs again (idempotency contract) and restores the line. No special "repair" mode is needed.
- **Atom bytes are unchanged since the previous install but hook_status would change**: `spaex install` still runs the hook and, if the resulting hook_status differs from what is currently in `install.lock`, publishes a new `install.lock` generation carrying only the hook_status change (hook-only transaction).
- **`spaex remove` on a molecule whose hook installed git hooks or external CLIs**: spaex does NOT reverse those side effects (documented limitation). `spaex remove` emits a WARN reminding the operator that hook side effects may remain and to consult the molecule's README.
- **Two molecules with identical priority AND identical id**: rejected by the existing resolver collision rule (Spec 013 territory); not touched by this feature.

## Requirements *(mandatory)*

### Functional Requirements

**Manifest schema**

- **FR-001**: The `molecule-manifest.v4.schema.json` MUST accept an optional top-level `install_hook` field that is an object with `additionalProperties: false`, required members `interpreter` (non-empty string) and `script` (repo-relative path), and optional members `args` (array of strings) and `on_failure` (enum `"abort" | "warn"`).
- **FR-002**: A molecule manifest without an `install_hook` field MUST remain valid under v4 (backwards-compatibility with all existing molecules).
- **FR-003**: A manifest whose `install_hook` value is a non-object type (string, null, array, number, boolean) MUST be rejected.
- **FR-004**: A manifest whose `install_hook.on_failure` value is outside `{"abort", "warn"}` MUST be rejected.

**Parsed manifest model**

- **FR-005**: `MoleculeManifest.from_json()` MUST populate an `install_hook: InstallHook | None` field. When the field is absent, the value is `None`. When the field is present but `on_failure` is omitted, the parsed value MUST explicitly hold `on_failure = "abort"` (the JSON-Schema default is documentation-only and MUST NOT be relied upon to mutate parsed input).
- **FR-006**: `InstallHook` MUST contain exactly the fields `interpreter`, `script`, `args`, `on_failure`, no others.

**Resolver contract**

- **FR-007**: For every selected molecule, the resolver MUST return a `ResolvedMolecule` record, regardless of whether the molecule contributes an `atoms.constitution` entry. Molecules that only declare `install_hook` MUST NOT be dropped from the resolved collection.
- **FR-008**: Each `ResolvedMolecule` record MUST expose the parsed `install_hook`, the canonical source URL, the pinned 40-hex revision, the immutable molecule cache directory for that revision, and the molecule's effective priority (consumer override if present, publisher default otherwise).

**Execution ordering and boundaries**

- **FR-009**: Within one `spaex install` invocation, all atoms MUST be fully materialised into the Spec-008 staging generation before any install_hook runs.
- **FR-010**: install_hooks MUST execute in ascending effective-priority order, with ties broken by ascending UTF-8 byte order of the molecule id (same order as constitution assembly).
- **FR-011**: install_hooks MUST execute before `publish_constitution()` (or its Spec-008 generalisation) seals `install.lock` and swaps the staged generation into the published root.
- **FR-012**: The hook subprocess MUST run with `cwd` set to the consumer repository root.
- **FR-013**: The hook subprocess MUST inherit stdin, stdout, and stderr from the invoking `spaex` process. spaex MUST NOT capture, buffer, or prefix the hook's stdio streams while the process is running.

**Script path containment**

- **FR-014**: Before executing the hook, spaex MUST resolve the script path (`<molecule-cache-dir>/<script>`) to its canonical form (symlinks followed, `..` segments resolved) and verify the result remains a descendant of the pinned molecule cache directory.
- **FR-015**: A canonicalised script path that escapes the pinned molecule cache MUST be treated as a hook failure, subject to the molecule's `on_failure` policy.

**Failure policy**

- **FR-016**: `on_failure = "abort"` MUST trigger the Spec-008 install-transaction rollback on any hook failure (non-zero exit, `OSError` on process launch, missing interpreter on `PATH`, or path-containment failure). The published atom generation MUST remain the pre-install one; `.spaex/install.lock` for this generation MUST NOT be written; a delegated `.spaex.json` update (via `spaex add`) MUST be reverted.
- **FR-017**: `on_failure = "abort"` failures MUST cause the CLI to exit with the existing `install-failed` diagnostic key (defined at `src/spaex/cli/install.py:232`), with the failing molecule id and failure kind in the diagnostic context.
- **FR-018**: `on_failure = "warn"` MUST NOT roll back the transaction. spaex MUST proceed to publish the atom generation (and any hook-only lock changes for other molecules), MUST write `.spaex/install.lock` with `hook_status: "failed"` for this molecule, and MUST exit 0.
- **FR-019**: When a hook fails under `on_failure = "warn"`, spaex MAY emit one post-exit `WARN:` line naming the molecule id and failure kind. spaex MUST NOT prefix any of the hook's inherited stderr lines with a `WARN:` prefix.

**install.lock hook-status contract**

- **FR-020**: `.spaex/install.lock`'s per-molecule record MUST gain an optional `hook_status` field that is present exactly when the molecule declares `install_hook`. Its value MUST be one of `"ok"`, `"failed"`, `"skipped"`.
- **FR-021**: `hook_status: "ok"` MUST be recorded when the hook was enabled (no `--no-install-hooks`) and exited 0.
- **FR-022**: `hook_status: "failed"` MUST be recorded when the hook was enabled but could not be launched, violated cache containment, or exited non-zero under `on_failure = "warn"`.
- **FR-023**: `hook_status: "skipped"` MUST be recorded when the operator supplied `--no-install-hooks` for this invocation.

**Idempotency and reruns**

- **FR-024**: `spaex install` MUST invoke every declared, enabled hook on every invocation (new adoption, revision bump, unchanged reinstall, and manual rerun), regardless of whether the atom candidate bytes changed since the last install.
- **FR-025**: When atom bytes are unchanged but the resulting `hook_status` records differ from the current `install.lock` content, `spaex install` MUST publish a new `install.lock` generation carrying only the hook-status change (hook-only transaction). When both atom bytes and hook-status records are unchanged, `spaex install` MUST perform the usual clean no-op after the hooks have run.

**Global opt-out**

- **FR-026**: `spaex add` and `spaex install` MUST accept a `--no-install-hooks` flag. When set, spaex MUST NOT invoke any declared install_hook during that invocation and MUST record `hook_status: "skipped"` for every molecule that declared a hook.
- **FR-027**: `--no-install-hooks` supplied to `spaex add` MUST propagate to the `spaex install` step it delegates to.
- **FR-028**: `--no-install-hooks` MUST be per-invocation only. It MUST NOT be persisted to `.spaex.json` or `.spaex/install.lock`; a subsequent `spaex install` without the flag MUST run the hooks normally.

**spaex remove interaction**

- **FR-029**: When `spaex remove` removes a molecule that declared an `install_hook`, spaex MUST emit a WARN naming the molecule id and stating that hook side effects (git hooks, gitignore entries, provisioned tools, agent-harness registrations) may remain and to consult the molecule's README for reverse steps. spaex MUST NOT attempt to reverse those side effects itself in v1.

### Key Entities

- **InstallHook**: parsed representation of a molecule's install_hook declaration. Fields: `interpreter` (program name on PATH), `script` (molecule-relative path), `args` (positional args passed after the script), `on_failure` (policy string). Attached to `MoleculeManifest` as an optional field.
- **ResolvedMolecule**: existing resolver record extended for this feature. Retains manifest, publisher source URL, pinned revision, immutable molecule cache directory, and effective priority. install_hook execution reads only this record, never the raw manifest, during install.
- **install.lock per-molecule record**: existing record extended with optional `hook_status`. Records are one per adopted molecule; `hook_status` appears only when that molecule declares `install_hook`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consumer adopting a molecule with an `install_hook` completes the molecule's declared setup (gitignore lines, git hooks, external tool provisioning) in a single `spaex add` command, with zero manual follow-up steps. Baseline: today, three current graphify-first-authoring consumers had to hand-add `graphify-out/` to their `.gitignore` after `spaex add`; after this feature lands, that number drops to zero.
- **SC-002**: The `install_hook` field is expressible in one manifest edit; a molecule author does not need to publish separate documentation to make their setup script discoverable or invocable by consumers. Baseline: today, graphify-first-authoring's install.py requires consumers to read its README and run it by hand; after this feature lands, the README's "run install.py after adopt" line becomes obsolete.
- **SC-003**: A hook failure under `on_failure = "abort"` produces zero orphaned files in the consumer's `.spaex/` directory: the consumer sees exactly the state that existed before the failing `spaex install`. Verifiable by comparing the consumer's `.spaex/` tree byte-for-byte before and after the failing invocation.
- **SC-004**: When a hook fails under `on_failure = "warn"`, the consumer can determine which molecule's hook failed by inspecting `.spaex/install.lock` alone, without consulting the terminal transcript.
- **SC-005**: `spaex add --no-install-hooks` skips exactly the set of hooks that would otherwise have run in that invocation (no more, no fewer) and records the skip in `.spaex/install.lock` such that a later `spaex install --no-install-hooks` produces the same skip state.
- **SC-006**: Between the pre-Spec-016 baseline and the post-Spec-016 release, no existing molecule (graphify-first-authoring 1.0.2, speckit-session-hopper 0.1.0) fails schema validation under the extended `molecule-manifest.v4.schema.json`. Backwards-compatibility of the schema addition is verifiable by re-validating existing published manifests against the new schema.

## Assumptions

- **`spaex install` is already invoked implicitly by `spaex add`**: verified in-session on 2026-09-07; the observation "installed generation g_..." confirms `spaex add` runs install as part of its flow. This spec assumes that behaviour continues and does not re-specify it.
- **Trust model is pin-based**: the consumer's decision to trust arbitrary publisher code is made once at pin time (`spaex add --revision <sha>`). The publisher SHA is treated as the sole trust anchor; hooks run with full consumer-user permissions with no additional consent step per invocation. Preemptive sandboxing is explicitly out of scope for v1 and revisited if concrete security incidents surface.
- **Reversibility is out of scope**: `spaex remove` cannot undo hook side effects (git hooks, gitignore entries, provisioned tools). This is a fundamental consequence of allowing arbitrary code execution. Consumers who need full reversibility should use a declarative tool (nix, terraform); spaex does not aspire to that in v1. Documented in `spaex remove` output as a warning when the removed molecule declared an install_hook.
- **Interactive prompts are supported in TTY only**: the `input()` builtin in the hook subprocess reads from the inherited stdin. In non-TTY contexts (CI, piped stdin, `< /dev/null`), `input()` raises `EOFError`. Molecule authors are expected to catch this and fall back to a sensible default; the reference implementation in graphify-first-authoring/install.py already follows this pattern. spaex does not synthesise a stdin.
- **The molecule cache directory is immutable per pinned SHA**: the `<molecule-cache-dir>` used for script resolution and cache-containment checks is the extracted publisher tree at the pinned revision, populated by the existing publisher-fetch machinery. This spec does not modify that machinery.
- **Hooks execute after atoms are staged but before the generation is published**: this ordering leverages the Spec-008 install-transaction so that a hook `abort` failure reaches the established rollback path.
- **Molecule priority ordering already used for constitution assembly is authoritative**: this spec does not introduce a new priority field or ordering rule; it reuses effective priority (consumer-override-aware) with UTF-8 tiebreak, matching Spec 007/013 behaviour.
- **Existing `install-failed` diagnostic key is used**: no new key is introduced; the failing-molecule context is added to the existing key's context dict. Verified at `src/spaex/cli/install.py:232`.

## Dependencies

- **Spec 007** (Unified Manifest v2): establishes the atom-category model that this spec extends via a new manifest field on the same schema version.
- **Spec 008** (Install Transaction): supplies the staging-generation-then-publish machinery that `on_failure: "abort"` rollback relies on. `hook_status` field additions extend the existing `install.lock` shape without breaking its Spec-008 contract.
- **Spec 013** (CLI and molecule rename): defined the `spaex add` / `spaex install` command surface that gains the `--no-install-hooks` flag and the hook-invocation behaviour.
- **Spec 014** (Rename to spaex): established the v4 vocabulary (`spaex_version`, `.spaex.json`, `.spaex/install.lock`) that this feature extends.
- **Design doc**: [docs/plans/2026-09-08-spec-016-molecule-install-hooks-design.md](../../docs/plans/2026-09-08-spec-016-molecule-install-hooks-design.md), brainstormed 2026-09-08, merged in PR #83 with review-driven refinements to the resolver contract, cache containment, stdio-prefix boundary, and hook-only-transaction semantics.

## Out of scope (deferred)

The following are intentionally NOT part of this spec and are candidates for their own future specs:

- **Declarative side-effect atom categories** (`gitignore_lines`, `git_hooks`, `shell_provisioners`): would let common side effects be applied AND reversed by spaex deterministically, obsoleting `install_hook` for the common case while keeping the hook as an escape hatch for edge cases.
- **Structured constitution composition**: today's constitution-assembly uses an LLM-merge when multiple molecules contribute, which can rewrite molecule authors' wording non-deterministically. Move to structured rule fragments with RFC-2119 severity metadata and mechanical assembly.
- **Uninstall hooks**: mirror-symmetric `uninstall_hook` for `spaex remove`. Same trust model as `install_hook`, same non-reversibility caveat. Add when consumers actually run `spaex remove` and hit the friction.
- **Per-molecule timeout**: `install_hook.timeout_seconds`. Add if runaway hooks become a real problem.
- **Pre-install hook**: `install_hook` variant that runs BEFORE atoms materialise. Add if a real use case appears.
- **Per-molecule consumer opt-out**: only the global `--no-install-hooks` flag exists in v1. Fine-grained per-molecule allow/deny lists deferred.
- **Sandbox alignment with Spec 009**: if the sandbox story matures, `install_hook` execution could route through `haex hook run <trigger>` with the Spec 009 hook-boundary contract. Not v1.
