# Feature Specification: Composition Status and Provenance Query

**Feature Branch**: `028-status-provenance`

**Created**: 2026-09-21

**Status**: Draft

**Input**: User description: "`spaex status` and provenance query (roadmap Phase C, docs/plans/2026-09-08-composition-ui-and-skills-externalization-roadmap.md). Today an operator cannot see what a repo's spaex composition actually contains: which molecules are pinned, which atoms each contributes per category, and which molecule wrote which file. Add read-only CLI commands that answer this: `spaex status` prints a human-readable summary of the active composition (pinned molecules, atoms per category, provenance per atom, and the composed constitution's provenance), and a provenance lookup answers 'which molecule wrote this file'. The output must also be available in a stable machine-readable form so a later GUI (roadmap Phase D) can consume it. Presets were dropped from the roadmap on 2026-09-21 and are out of scope. Reconcile with the existing `spaex constitution trace` from Spec 023 instead of duplicating it. No GUI, no writes, no changes to the manifest or install pipeline."

## Clarifications

### Session 2026-09-22

- Q: `spaex status` should show, per molecule, what its atoms are. A molecule's own manifest groups atoms under free-form category names (`behavior`, `nix_packages`, or anything else a publisher picks), but that name is only a dispatch key for which materializer handles the file at install time — it is validated, not trusted, and reading it back would require the molecule's manifest, which is not guaranteed to be present in a fresh clone without a local molecule cache. What should the per-molecule atom listing be based on? → A: Group by what spaex actually did with each atom, read entirely from files already committed to the repository: which fragments it materialized into the constitution (`.spaex/constitution.d/<molecule-id>/`, tracked in git per `.gitignore`'s explicit carve-out), which composed generated artifact it contributed to (an install-lock path with more than one owning molecule, e.g. `.spaex/generated/nix-packages.json`), and which plain files it wrote verbatim (the remaining install-lock paths, already covered by FR-004). This needs no molecule manifest, no local molecule cache, and works in a fresh clone.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See what a repo's composition contains (Priority: P1)

An operator opens a repository that uses spaex and wants to know what is active in it: which molecules are pinned and at which revision, what each one installed, and what the composed constitution consists of. Today the only way is to read `.spaex/manifest.json`, `.spaex/install.lock` and the generated files by hand and cross-reference them.

**Why this priority**: This is the core gap. Every other capability (file lookup, drift, a future GUI) builds on a trustworthy summary of the active composition.

**Independent Test**: In a repository with several installed molecules, run `spaex status` and confirm that the output names every pinned molecule with its source and revision, lists the files each one wrote, and summarizes the composed constitution, without modifying anything.

**Acceptance Scenarios**:

1. **Given** a repository whose molecules are pinned and installed, **When** the operator runs `spaex status`, **Then** every pinned molecule is listed with its identifier, source, pinned revision and the outcome of its install hook (if it has one).
2. **Given** the same repository, **When** the operator runs `spaex status`, **Then** each molecule's entry lists the repo-relative files it wrote, as recorded at install time.
3. **Given** a repository with a composed constitution, **When** the operator runs `spaex status`, **Then** the report states how many clauses the constitution has per modality (MUST, MUST_NOT, SHOULD, SHOULD_NOT, MAY), which molecules contribute to it, and which fragments are project-local rather than molecule-provided.
4. **Given** a molecule that contributed to this repository, **When** the operator runs `spaex status`, **Then** its atoms are listed grouped by what spaex did with them: the behavior fragments materialized into the constitution, its contribution to each composed generated artifact, and the plain files it wrote verbatim — derived from files already committed to the repository, not from the molecule's own manifest.
5. **Given** the operator runs `spaex status`, **When** the command finishes, **Then** no file in the repository, the local molecule cache or the user configuration has changed.

---

### User Story 2 - Find out which molecule wrote a file (Priority: P1)

An operator sees a file in the repository (for example `flake.nix` or `.spaex/constitution.md`) and wants to know where it came from: which molecule wrote it, from which source and revision. They ask `spaex trace <path>`.

**Why this priority**: "Where did this file come from?" is the most common question when a molecule-managed file looks wrong or surprising, and it decides whether the operator edits the file, changes the molecule pin, or removes the molecule.

**Independent Test**: For every path recorded in this repository's install lock, run `spaex trace <path>` and confirm it names the same molecule(s) the lock records, then run it on a hand-written file and confirm a clear "not recorded" answer.

**Acceptance Scenarios**:

1. **Given** a file written by exactly one molecule, **When** the operator runs `spaex trace <path>`, **Then** the answer names that molecule's identifier, source and revision.
2. **Given** a path written by several molecules (the composed constitution is shared by every molecule that contributes behavior), **When** the operator runs `spaex trace <path>`, **Then** every contributing molecule is listed, and the output points to `spaex constitution trace` for clause-level provenance instead of repeating it.
3. **Given** a path that no molecule is recorded as having written, **When** the operator runs `spaex trace <path>`, **Then** the command reports that no molecule is recorded for it, explains that hand-written files and files created by a molecule's install hook are not tracked, and exits with the "no match" status.
4. **Given** a directory path, **When** the operator runs `spaex trace <directory>`, **Then** every recorded file under that directory is listed with its writing molecule(s).

---

### User Story 3 - Consume the same answers as structured data (Priority: P2)

A tool (a script, CI job, or the future GUI in roadmap Phase D) needs the same information without parsing prose. The operator or tool passes `--format json` to either command.

**Why this priority**: The roadmap makes the GUI a consumer of this data. Without a stable structured form, the GUI would have to scrape human-readable text or re-derive provenance itself.

**Independent Test**: Run both commands with `--format json` twice on an unchanged repository and confirm the outputs are byte-identical, valid against the documented structure, and contain no machine-specific values.

**Acceptance Scenarios**:

1. **Given** any repository state, **When** either command runs with `--format json`, **Then** the output carries the same facts as the text form and a format version so consumers can detect changes.
2. **Given** an unchanged repository, **When** the same command runs twice, **Then** the outputs are byte-identical.
3. **Given** two machines with different operating systems and checkout locations, **When** the same command runs on identical repository content, **Then** the JSON output is identical (repo-relative paths with forward slashes, no absolute paths, no timestamps or host details).

---

### User Story 4 - Notice when the installed state has drifted (Priority: P2)

An operator has edited `.spaex/manifest.json` (added a molecule, bumped a revision) or pulled changes, and wants to know whether the installed state still matches. `spaex status` shows the difference instead of silently reporting either side.

**Why this priority**: A status view that only mirrors the manifest, or only the lock, misleads exactly when the operator most needs it. Showing drift makes "run `spaex install`" an obvious next step.

**Independent Test**: Seed four drift cases in a scratch repository and confirm `spaex status` flags each one.

**Acceptance Scenarios**:

1. **Given** a molecule pinned in the manifest but absent from the install lock, **When** the operator runs `spaex status`, **Then** it is shown as pinned but not installed.
2. **Given** a molecule present in the install lock but no longer pinned, **When** the operator runs `spaex status`, **Then** it is shown as installed but no longer pinned.
3. **Given** a molecule whose pinned revision differs from the installed revision, **When** the operator runs `spaex status`, **Then** both revisions are shown and the mismatch is flagged.
4. **Given** a composed constitution that is older than the fragments it is built from, **When** the operator runs `spaex status`, **Then** it is reported as stale, without regenerating it.
5. **Given** any of the above, **When** `spaex status` finishes, **Then** it still exits with success and suggests `spaex install`; it never repairs anything itself.

---

### Edge Cases

- **Not a spaex project**: no `.spaex/manifest.json` exists. Both commands say so plainly and exit with an error status distinct from "no match", rather than printing an empty composition.
- **Never installed**: the manifest exists but there is no install lock. `spaex status` lists the pinned molecules as not installed and shows no files or constitution.
- **Unreadable state**: the manifest or install lock is present but invalid. The commands report which file is invalid and why, and exit with an error status; they never present a partial or guessed composition.
- **No behavior molecules**: no molecule contributes constitution fragments. The constitution section says there is no composed constitution instead of reporting zero clauses as if one existed.
- **A molecule contributes nothing observable**: a molecule is pinned and installed but has no materialized behavior fragments, no composed-artifact contribution and no plain files recorded (for example, an install-hook-only molecule). Its atom listing says so instead of appearing empty without explanation.
- **Path forms**: `./flake.nix`, an absolute path inside the repository, a path with a trailing slash and a path given from a subdirectory (with `--repo-root`) all resolve to the same repo-relative answer. A path outside the repository is rejected with an error, not answered as "not recorded".
- **Hook-written and hand-written files**: a file created by an install hook or by hand is not attributed to any molecule, and the "not recorded" answer says why.
- **Project-local fragments**: a constitution fragment declared by the project itself has no molecule pin; it is labelled project-local instead of "unknown molecule".
- **Concurrent install**: while `spaex install` is publishing a new generation, the commands show either the complete previous or the complete new state, never a mixture, and do not fail because of the install.
- **Large compositions**: with many molecules and many constitution clauses, the text output stays scannable (grouped, one line per molecule by default) rather than dumping every clause.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide `spaex status`, which reports the active composition of the repository, and `spaex trace <path>`, which reports which molecule(s) wrote a given file or directory.
- **FR-002**: Both commands MUST be read-only: they MUST NOT modify any file in the repository, the local molecule cache or the user configuration, and MUST NOT access the network.
- **FR-003**: `spaex status` MUST list every molecule pinned in the manifest and every molecule recorded in the install lock, each with identifier, source and revision, and, when recorded, the outcome of its install hook.
- **FR-004**: `spaex status` MUST list, per molecule, the repo-relative files it wrote as recorded in the install lock.
- **FR-005**: `spaex status` MUST list, per molecule, its atoms grouped by what spaex did with them at install time: behavior fragments materialized into the constitution (by fragment id, from `.spaex/constitution.d/<molecule-id>/`), its contribution to each composed generated artifact (an install-lock path recorded with more than one owning molecule), and the plain files it wrote verbatim (the remaining install-lock paths). This grouping MUST be derived entirely from files already committed to the repository (manifest, install lock, materialized constitution fragments, generated artifacts) and MUST NOT require reading a molecule's own manifest or its content from the local molecule cache.
- **FR-006**: `spaex status` MUST summarize the composed constitution: whether one exists, the clause count per modality, the contributing molecules, and the project-local fragments.
- **FR-007**: `spaex status` MUST report drift between manifest and install lock (pinned but not installed, installed but no longer pinned, revision mismatch) and whether the composed constitution is stale relative to its fragments, without regenerating anything and without invoking the Composer.
- **FR-008**: `spaex trace <path>` MUST name, for a file, every molecule recorded as having written it, with identifier, source and revision; for a directory, every recorded file under it with its molecule(s).
- **FR-009**: When the path is written by several molecules, `spaex trace` MUST list all of them and MUST point to `spaex constitution trace` for clause-level provenance of the composed constitution rather than duplicating that lookup.
- **FR-010**: When no molecule is recorded for a path, `spaex trace` MUST say so, MUST state that hand-written files and files created by install hooks are not tracked, and MUST exit with the same "no match" status that `spaex constitution trace` uses.
- **FR-011**: `spaex trace` MUST accept absolute paths inside the repository, `./`-prefixed paths and trailing slashes, resolve them to a repo-relative path, and MUST reject paths outside the repository with an error.
- **FR-012**: Both commands MUST accept `--format text|json`, defaulting to `text`, the same option shape as `spaex constitution trace`, and MUST honor the existing `--repo-root` option.
- **FR-013**: The JSON output MUST include a format version, MUST contain the same facts as the text output, MUST list items in a deterministic order, and MUST contain only repo-relative paths with forward slashes and no timestamps, host names, user names or absolute paths, so identical repository content yields byte-identical output on every supported OS.
- **FR-014**: Exit statuses MUST distinguish three outcomes: a report or answer was produced (success, including when drift is shown), no match for `spaex trace` (the same status as `spaex constitution trace`), and an operational error (missing or invalid manifest or lock, path outside the repository).
- **FR-015**: `spaex status` and `spaex trace` MUST present a consistent snapshot: during a concurrent install they MUST show either the complete previous or the complete new generation.
- **FR-016**: The behavior of `spaex constitution trace`, including its output, exit codes and options, MUST remain unchanged.
- **FR-017**: The commands MUST NOT change the manifest, the install pipeline, the install lock format or any generated artifact.

### Key Entities

- **Composition report**: the result of `spaex status`: the repository's pinned and installed molecules, the constitution summary and the drift findings, at one point in time.
- **Molecule record**: one molecule in the report: identifier, source, pinned revision, installed revision, install state (installed, pinned but not installed, installed but no longer pinned), install-hook outcome, and its atoms grouped by what spaex did with them (materialized behavior fragments, contributions to composed generated artifacts, plain files written verbatim).
- **File attribution**: the answer for one path in `spaex trace`: the path and the molecule(s) recorded as having written it, or the fact that none is recorded.
- **Constitution summary**: whether a composed constitution exists, clause counts per modality, contributing molecules, project-local fragments and freshness.
- **Drift finding**: one difference between manifest, install lock and generated artifacts, with the two values that disagree.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can find out which molecules are active and at which revisions with one command; on this repository (9 molecules) the report is produced in under 5 seconds.
- **SC-002**: For 100% of the paths recorded in this repository's install lock, `spaex trace` names exactly the molecule(s) the lock records.
- **SC-003**: After running either command, a byte-level comparison of the repository, the local molecule cache and the user configuration shows zero changed files.
- **SC-004**: For an unchanged repository, the JSON output of each command is byte-identical across repeated runs and across Linux, macOS and WSL2, and every output carries a format version.
- **SC-005**: All four drift cases (pinned but not installed, installed but no longer pinned, revision mismatch, stale constitution) are flagged in 4 of 4 seeded scenarios.
- **SC-006**: In a fresh checkout without a local molecule cache, `spaex status` still completes and shows molecules, revisions, files, atoms grouped by kind, and the constitution summary, all identical to a checkout with a warm cache.
- **SC-007**: The existing tests for `spaex constitution trace` pass without modification.

## Assumptions

- **Command names**: this spec settles the names the roadmap left open: `spaex status` and `spaex trace <path>`. The roadmap's `spaex show <atom-id>` is not adopted, because the install lock records molecules and files, not stable atom identifiers; the per-path lookup answers "which molecule wrote this file". If the future GUI needs atom-level lookups, that is a follow-up.
- **Two trace commands, two granularities**: `spaex trace` answers at file level, `spaex constitution trace` (Spec 023) at clause level. They stay separate commands; `spaex trace` points to the latter for the shared composed constitution instead of reimplementing it.
- **Data sources**: the reports draw only on data already committed to the repository: `.spaex/manifest.json`, `.spaex/install.lock`, `.spaex/constitution.md` and the materialized fragments under `.spaex/constitution.d/`, and generated artifacts such as `.spaex/generated/nix-packages.json`. None of this requires the local molecule cache or a molecule's own manifest, so both commands work identically in a fresh clone. Nothing is fetched and nothing is materialized, since the commands must be read-only.
- **Drift is informational**: it does not change the exit status, so `spaex status` cannot gate CI. A `--check`-style mode is a possible follow-up.
- **Constitution freshness** is computed locally: the same fingerprint functions Spec 023 defines (`source_hash`, `build_input_hash`), recomputed from the already-materialized `.spaex/constitution.d/` tree rather than by resolving molecules from the local cache — `spaex constitution build --check` itself resolves molecules first, which can touch the network, so it is not reused as-is (research.md R4). Never calls the Composer.
- **Untracked files**: files created by a molecule's install hook or by hand are not tracked by the install lock and are therefore not attributed (see the hook write boundary in Spec 016).
- **Presets**: dropped from the roadmap on 2026-09-21. The `preset` field reserved in Spec 023's provenance data model is neither used nor removed by this spec; removing it is a separate cleanup.
- **GUI**: roadmap Phase D is a downstream consumer of the JSON output. No GUI work is part of this spec.
