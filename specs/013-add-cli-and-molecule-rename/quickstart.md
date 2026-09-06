# Quickstart: v3 Vocabulary and `haex add` / `haex remove`

**Spec**: 013

This walk-through covers the three end-to-end flows this spec enables: migrating a v2 project to v3, adopting a molecule with one command, and retracting a molecule with one command. It assumes the v3 tool is installed and the operator has git access to whichever `<source-url>` publishes the molecule.

---

## Prerequisite: migrate an existing v2 project to v3

If your project's `.haex-hive.json` still says `"haex_hive_version": "2"`, the tool refuses at load time and points at `haex migrate`. Run:

```bash
haex migrate --check
```

The command scans `.haex-hive.json`, `manifest.json` (if this repo is also a publisher), and every per-molecule `manifest.json` under the paths declared by that publisher manifest. For each input, it prints a unified diff when a migration proposal is produced, a diagnostic when the input is refused, or `already at v3 (nothing to migrate)` when no migration is needed. Nothing is written. Review the proposals and diagnostics.

When the diffs look right, run:

```bash
haex migrate
```

Every affected file gets a `.migrated` sibling:

- `.haex-hive.json.migrated`
- `manifest.json.migrated` (root, if you publish)
- `<molecule-dir>/manifest.json.migrated` for each of your molecule directories

> **Note (2026-09-06):** proposals for publisher manifests referenced from immutable remote SHAs (under `$HAEX_HIVE_STATE/migrations/<source-digest>/<revision>/`) are declared by the contract but not yet emitted by this build; that leg is tracked as T044R/T054R and lands in a follow-up. Local siblings work today.

The migrator never overwrites originals. To adopt each local proposal:

```bash
git diff --no-index .haex-hive.json .haex-hive.json.migrated
mv .haex-hive.json.migrated .haex-hive.json
```

Repeat for every proposal. When the follow-up lands, adoption of a remote-publisher proposal will mean copying its `.migrated` content into a publisher checkout, opening a PR upstream, and bumping your consumer's pin to the resulting SHA.

Verify with:

```bash
haex install
```

A clean install on the newly adopted v3 manifests confirms the transition. A re-invocation on an already-v3 repository is a no-op:

```console
$ haex migrate
already at v3 (nothing to migrate)
```

Exit codes: `0` on success or all-noop, `1` when at least one input yielded a proposal AND at least one refused, `2` on hard refusal with no proposal. `--dry-run` and `--check` are mutually exclusive; passing both exits `64` (`usage`).

---

## Adopt a molecule in one command

Once your project is on v3, adopting a molecule is a single command:

```bash
haex add https://github.com/haexmas/atoms com.github.haexmas.atoms.graphify-first-authoring
```

> **Note (2026-09-06):** the real `haexmas/atoms` repository's publisher-root `manifest.json` is still on v2 at HEAD, so this exact command refuses today with `publisher-manifest-invalid` at the publisher-manifest gate. Migrating `haexmas/atoms` to v3 is a follow-up on that repo itself. Substitute any v3-native publisher URL to exercise the flow end to end; the CLI shape is identical.

The command:

1. Resolves the current HEAD SHA of the source via `git ls-remote <source-url> HEAD`.
2. Fetches (or reuses) the publisher clone under `$HAEX_HIVE_STATE/repos/<source-digest>/` via `git fetch origin <sha> --depth 1`.
3. Validates that the publisher-root `manifest.json` at that SHA is a valid v3 manifest and lists every requested molecule id.
4. Loads each requested molecule's own `manifest.json` under the path the publisher declared for it. Detects whether the added set introduces a workflow molecule or a constitution-contributing molecule, and refuses pre-write when either category is already resolved by a different molecule in `.haex-hive.json`.
5. Writes a new `compoundEntry` (or merges into an existing one for the same source and revision) into `.haex-hive.json` via `.haex-hive.json.tmp` + rename. Within a compound, `molecules[]` is deduplicated and lexically sorted.
6. Calls the existing `haex install` pipeline in-process while still holding the manifest lock, so `.haex-hive/` is up to date immediately. Any install failure rolls the manifest edit back atomically.

To pin an exact revision:

```bash
haex add https://github.com/haexmas/atoms com.github.haexmas.atoms.graphify-first-authoring \
  --revision=ff6fda2180563479497e0bd5a25144653d3175fb
```

`--revision` accepts only a full 40-hex commit SHA (Principle IV). Anything shorter or non-hex refuses with `revision-not-found`.

To adopt every molecule the publisher ships at the pinned or resolved SHA:

```bash
haex add https://github.com/haexmas/atoms --all
```

`--all` and positional molecule ids are mutually exclusive; combining them refuses with `usage` (exit 64).

To adopt without specifying a molecule id, on a TTY:

```bash
haex add https://github.com/haexmas/atoms
```

The command lists the available molecule ids and prompts you to pick one or more (comma-separated ids, or numeric indexes from the printed list). On non-TTY invocations, this form refuses with `interactive-selection-unavailable`; scripts must pass explicit ids or `--all`.

To override the manifest-lock timeout (default 30 s):

```bash
haex add https://github.com/haexmas/atoms com.github.haexmas.atoms.graphify-first-authoring \
  --lock-timeout=5
```

`--lock-timeout=0` means fail-fast (refuse immediately on contention). See `## Concurrency and the manifest lock` below.

### Single constitution per repository

haex-hive enforces the invariant from ADR 0010: a repository adopts **exactly one** constitution-contributing molecule. The `atoms.constitution` list in a molecule manifest may hold one file or several; when several, the tool concatenates them (in the molecule's declared order) into the single effective constitution at `.haex-hive/constitution.md`. That splitting is an authoring convenience, not a claim that multiple constitutions coexist.

When you try to adopt a second molecule that also contributes a constitution and `.haex-hive.json` already resolves to a different constitution-contributing molecule, `haex add` refuses at the CLI boundary. Example stderr:

```console
error: exit=2 key=constitution-already-adopted category=constitution adopted_by=<currently-adopted-id> adding=<new-id>
  add refuses: category 'constitution' already adopted by ...
  hint: Adopt only one constitution-contributing molecule, or combine the constitutions externally.
```

**How to swap constitutions.** Whether the replacement is a new revision of the same publisher's molecule, a different molecule from a different publisher, or an externally-combined atom, the recipe is the same two-step flow:

```bash
haex remove <currently-adopted-constitution-id>
haex add <source-url> <new-constitution-molecule-id>
```

The `haex remove` step drops the current constitution molecule from `.haex-hive.json` and runs `haex install`, which publishes an empty-state generation (`install.lock` with `molecules: []`, no `.haex-hive/constitution.md`). The follow-on `haex add` adopts the new constitution and re-publishes. Between the two commands the consumer is transiently in the empty-constitution state; that is a legitimate state, not a failure mode.

If you want to keep the previous constitution's content locally for review before removing it, copy it out first:

```bash
cp .haex-hive/constitution.md /tmp/previous-constitution.md
haex remove <currently-adopted-constitution-id>
# ...review /tmp/previous-constitution.md, decide what to adopt next...
haex add <source-url> <new-constitution-molecule-id>
```

`.haex-hive/` is tool-owned; the file will be deleted by the remove step's install pass.

**haex-hive does not merge constitutions.** Combining two rule sets into one document is an editorial decision the operator makes outside the tool. The result is published as a normal atom in the source of your choice and adopted through the recipe above; no `--llm=file`, `--accept-merged`, or in-tool merge command exists.

The workflow category obeys the same singleton rule: `workflow-molecule-already-adopted` refuses the second one; recovery is `haex remove <current-workflow-molecule-id>` first.

---

## Retract a molecule in one command

To remove a previously adopted molecule:

```bash
haex remove com.github.haexmas.atoms.graphify-first-authoring
```

The command:

1. Acquires the manifest lock (same bounded-wait rules as `haex add`).
2. **Preflight** every named molecule id against `.haex-hive.json.compounds[].molecules[]`. If any named id is not present in any compound, refuse with `unknown-molecule-id` naming **every** missing id and change nothing.
3. On success, remove the ids, drop any compound whose `molecules[]` became empty, and prune matching keys from the compound's `config{}`.
4. Write `.haex-hive.json` atomically, then run `haex install` in-process, which deletes every file the retracted molecule had contributed (Spec 008 US3 delete-orphans).

To retract multiple molecules in one call:

```bash
haex remove com.github.haexmas.atoms.graphify-first-authoring,com.github.haexmas.atoms.speckit-session-hopper
```

All-or-nothing: `haex remove <present>,<absent>` refuses at the preflight step without removing `<present>`.

If the retracted molecule was the currently adopted workflow molecule, the ensuing install runs without it. A tool-side bundled fallback for the `speckit` workflow is planned under Spec 011 amendment FR-008 and lands separately; today the retraction simply leaves the consumer without a workflow molecule until another `haex add` restores one.

Retracting the last constitution-contributing molecule is a legitimate outcome: the follow-on install publishes an empty generation (`install.lock` with `molecules: []`) and `.haex-hive/constitution.md` disappears with the rename-swap of `.haex-hive/`. The consumer sits in the empty-constitution state until a subsequent `haex add` restores one; that state is valid at read time (Spec 013, 2026-09-06 empty-state landing).

---

## Concurrency and the manifest lock

`haex add`, `haex remove`, and `haex install` all acquire the permanent advisory manifest lock at `.haex-hive.json.lock` before reading or replacing `.haex-hive.json`. Concurrent invocations serialize; a second contender either waits (up to `--lock-timeout=<sec>`, default 30 s) or refuses on contention with `manifest-lock-contended` (exit 9) rather than corrupting the manifest.

- `--lock-timeout=0` is fail-fast (refuse immediately on contention).
- `--lock-timeout=<positive>` polls until the deadline, then refuses.
- Nested acquisition within the same process reuses the held descriptor via reference counting (so `haex add` can pass the held lock down to its in-process `haex install` call without re-acquiring).

The lock file is created once by the tool on first use and never renamed or deleted. Its content is inconsequential; only the OS-level advisory lock matters (POSIX `fcntl.flock`, Windows `LockFileEx`). Kernel-level release on process exit is the sole automatic recovery path; the tool never force-breaks a lock held by a living process.

---

## Common refusals and their meaning

| Refusal key | Meaning | Exit | Recovery |
|---|---|---|---|
| `source-url-invalid` | `git ls-remote <source-url>` failed with a non-transient error. | 2 | Check the URL, network, and any auth. |
| `revision-not-found` | `--revision=<SHA>` is not a full 40-hex SHA, or the remote does not have that SHA. | 2 | Verify the SHA or drop the flag to resolve HEAD. |
| `publisher-manifest-missing` | The resolved SHA has no `manifest.json` at the publisher repo root. | 2 | Confirm the source is a haex-hive publisher; pick a revision that actually publishes one. |
| `publisher-manifest-invalid` | The publisher-root `manifest.json` at the resolved SHA is present but non-JSON, or does not validate against `publisher-manifest.v3.schema.json` (schema violation or `haex_hive_version` not `"3"`). | 2 | Confirm the publisher has migrated to v3; pick a different revision if the publisher moved. |
| `molecule-id-not-in-source` | A named molecule id is not in the publisher manifest at that SHA. | 2 | Check spelling and case; the publisher may have renamed. |
| `interactive-selection-unavailable` | No molecule ids, no `--all`, and stdin is not a TTY. | 2 | Pass explicit molecule ids or `--all`. |
| `workflow-molecule-already-adopted` | The added set includes a workflow molecule while a different one is already adopted. | 2 | `haex remove <current-workflow-molecule-id>` first. |
| `constitution-already-adopted` | The added set includes a constitution-contributing molecule while a different one is already adopted. | 2 | `haex remove <current-constitution-id>` first, or combine the two constitutions into one atom externally. haex-hive does not merge. |
| `unknown-molecule-id` | `haex remove` was called with an id not present in any compound. | 2 | Check spelling; nothing changed. |
| `install-transaction-failed` | The follow-on `haex install` failed after a successful manifest edit. The manifest edit is rolled back atomically under the still-held lock. | matches install | The exit and diagnostic name the underlying install failure. |
| `manifest-lock-contended` | The manifest lock could not be acquired within the timeout window (default 30 s). | 9 | Wait and retry, invoke with a longer `--lock-timeout=<sec>`, or use `--lock-timeout=0` for fail-fast. Investigate stuck processes if it persists. |
| `directory-form-contributes-unsupported` | `haex migrate` encountered a v2 molecule with `contributes.<cat> = "<dir>/"`. | 2 | Enumerate the intended files in the v2 source manifest before rerunning migrate. |
| `unsupported-min-version-constraint` | `haex migrate` cannot rewrite `haex_hive_min_version` with a major other than `2.x.y` or `>=2.x.y`. | 2 | Rewrite the constraint to `2.x.y` or `>=2.x.y` and retry. |
| `migration-manifest-invalid` | `haex migrate` found a structurally malformed v2 manifest (non-object shape, missing required field). | 2 | Fix the manifest and retry. |
| `migration-path-outside-repository` | A v2 publisher's `molecules[].path` resolves outside the repository root. | 2 | Fix the publisher's declared path. |

