# Feature Specification: Local (Per-Developer) Molecule Scope

**Feature Branch**: `029-local-molecule-scope`

**Created**: 2026-10-12

**Status**: Draft

**Input**: User description: "Local (per-user) molecule scope alongside the existing project scope. Today every molecule a consumer adopts is recorded in the committed .spaex/manifest.json and everything spaex installs from it is meant to be committed and shared with the whole team (project scope). Add a second scope, \"local\": molecules a single developer adopts for themselves in one repository, which are not committed and do not affect teammates. Local adoptions live in a gitignored per-repo overlay next to the project manifest; their outputs (behavior fragments, generated files, generic atoms, Spec Kit integrations, hook effects) must never end up in the committed tree, and spaex must keep them out of git automatically without requiring edits to the team's .gitignore. `spaex add`/`spaex remove` gain a way to target the local scope; `spaex install` applies project scope first and local scope on top; `spaex status`/`trace`/`constitution show` report which scope each molecule and file comes from. A developer's local behavior fragments must apply to their agent sessions without changing the committed, team-shared composed constitution. A molecule adopted in project scope cannot also be adopted locally (or local adoption is a no-op/conflict, to be decided). Teammates cloning the repo see only project scope; a fresh clone with no local overlay behaves exactly as today."

## Terminology

- **Project scope**: the existing behavior. Adoptions are recorded in the committed consumer manifest; everything spaex installs from them is part of the shared, committed repository state and applies to every teammate.
- **Local scope**: new. Adoptions a single developer makes for themselves in one checkout of one repository. Neither the adoption record nor anything installed from it is ever committed; teammates never see it.
- **Local overlay**: the uncommitted, per-checkout record of local-scope adoptions, kept next to the project manifest.
- Not to be confused with the existing **project-local fragments** (repo-owned behavior fragments declared in the committed manifest): those are project scope, committed, and unaffected by this feature.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Adopt a molecule just for myself (Priority: P1)

A developer working in a team repository wants extra harness content for their own agent sessions (for example a personal coding-style guideline, or an extra agent integration) without proposing it to the team and without any risk of it being committed.

**Why this priority**: This is the core value. Without it the only way to get personal harness content is to adopt it project-wide (forcing it on the team) or to copy files by hand (unmanaged, easy to commit by accident).

**Independent Test**: In a repo that already has project-scope adoptions, adopt one molecule in local scope, run install, and confirm (a) its content is installed and active for the developer, (b) `git status` shows no new or modified tracked or untracked-but-unignored files, and (c) the committed manifest and every project-scope output are byte-identical to before.

**Acceptance Scenarios**:

1. **Given** a repo with project-scope adoptions and a clean working tree, **When** the developer adopts a molecule in local scope, **Then** the molecule's content is installed, the committed manifest is unchanged, and the working tree reports no changes visible to git.
2. **Given** a local-scope molecule is installed, **When** the developer runs install again with no input changes, **Then** every output (project and local) is byte-identical to the previous run.
3. **Given** a local-scope molecule is installed, **When** the developer runs `git add -A` and inspects the staged set, **Then** no file contributed by local scope and no part of the local overlay is staged.

---

### User Story 2 - Personal behavior rules reach my agent without changing the team constitution (Priority: P1)

A developer adopts a molecule contributing behavior fragments in local scope and expects their agent sessions to follow those rules in addition to the team's rules, while the committed team constitution stays exactly as the team composed it.

**Why this priority**: Behavior fragments are the most common molecule content. If local behavior either leaks into the shared constitution or is invisible to agents, the feature fails its main use case.

**Independent Test**: Adopt a behavior-only molecule locally, run install, and confirm the committed composed constitution is byte-identical to before, a separate local behavior document exists and is uncommitted, and the agent-facing instructions direct agents to read the local document after the project one.

**Acceptance Scenarios**:

1. **Given** project-scope behavior is installed, **When** the developer adopts a behavior molecule in local scope and runs install, **Then** the committed composed constitution is byte-identical to the project-only result and a separate, uncommitted local behavior document contains the local rules.
2. **Given** both documents exist, **When** an agent session starts in the repo, **Then** the agent is directed to load the project constitution and then the local behavior document.
3. **Given** a local rule contradicts a project rule, **When** an agent follows the instructions, **Then** the project rule prevails, as stated in the local document itself.

---

### User Story 3 - Remove a local adoption cleanly (Priority: P1)

A developer retracts a molecule they adopted locally and expects every file it contributed to disappear, with project-scope content untouched.

**Why this priority**: Without symmetric cleanup, local adoptions accumulate unmanaged files, the same problem spaex solves for project scope.

**Independent Test**: Adopt a local molecule that contributes behavior fragments and a generic-category file, then remove it in local scope and confirm none of its files remain, its exclusion entries are gone, and project outputs are byte-identical.

**Acceptance Scenarios**:

1. **Given** a locally adopted molecule, **When** the developer removes it from local scope, **Then** every file only it contributed is deleted and project-scope files are untouched.
2. **Given** the last local adoption is removed, **When** install completes, **Then** no local behavior document, no local generated output, and no stale exclusion entry remains.

---

### User Story 4 - See which scope everything comes from (Priority: P2)

A developer inspecting the harness wants to know which molecules are project-wide and which are only theirs, and which scope wrote a given file.

**Why this priority**: Without provenance a developer cannot tell whether a rule their agent follows is team policy or personal preference, or whether a file is safe to discuss in a review.

**Independent Test**: With adoptions in both scopes, run status, trace on a local-scope file, trace on a project-scope file, and constitution show, and confirm each output labels the scope.

**Acceptance Scenarios**:

1. **Given** adoptions in both scopes, **When** the developer runs status, **Then** each molecule is listed with its scope and drift is reported per scope.
2. **Given** a file written by a local-scope molecule, **When** the developer runs trace on it, **Then** the output names the molecule and the local scope.
3. **Given** local behavior is installed, **When** the developer runs constitution show, **Then** the project constitution is shown first and the local behavior is shown after it, clearly labelled as local.

---

### User Story 5 - Teammates and fresh clones are unaffected (Priority: P2)

A teammate clones the repo, or the same developer creates a fresh checkout, and gets exactly the project-scope harness, as if this feature did not exist.

**Why this priority**: Local scope must be invisible to everyone who did not opt in; otherwise it is not "local".

**Independent Test**: In a repo with a developer's local adoptions, clone the remote into a new directory, run install, and compare every output with an install from before this feature: they must be byte-identical.

**Acceptance Scenarios**:

1. **Given** a checkout with no local overlay, **When** install runs, **Then** its behavior and every output are byte-identical to the behavior before this feature.
2. **Given** a teammate's checkout, **When** they pull commits made by a developer who uses local scope, **Then** nothing in those commits refers to the developer's local adoptions.

---

### Edge Cases

- **Same molecule in both scopes**: adopting a molecule locally that is already adopted in project scope is refused with a diagnostic naming the project adoption. If the project later adopts a molecule that is already adopted locally (for example after a pull), install keeps going: the project adoption wins, the local entry is reported as shadowed and contributes nothing, and the developer is told how to drop it.
- **Path owned by project scope**: a local molecule that would write an exclusive file at a path a project molecule owns is refused; the project file is never overwritten.
- **Path tracked by git**: a local molecule that would write a file at a path git already tracks, or one that is not ignored by the project but present in the index, is refused, because writing there would change the committed tree.
- **Composable contributions** (several molecules feeding one generated file): local contributions never change the project's generated output; they produce a separate local generated output instead.
- **Spec Kit integrations in local scope**: an integration selected only locally is installed for this developer; its output files are excluded from git like every other local output. If the project scope already declares Spec Kit integrations, the local declaration must be compatible or the local adoption is refused.
- **Install hooks in local scope**: hooks run as for project scope. spaex can only exclude files it records itself; files a hook writes on its own are the hook's responsibility, and the developer is warned once when adopting a hook-bearing molecule locally.
- **Local install failure**: a failing local-scope step rolls back the local outputs of that run without leaving project outputs half-written.
- **Corrupt or invalid local overlay**: install refuses with a diagnostic naming the overlay; project scope is not silently applied without it, so the developer is never surprised by missing personal content.
- **Not a git repository**: local scope works; there is nothing to exclude from, so no exclusion is attempted.
- **Multiple worktrees**: each checkout has its own local overlay and outputs; adopting locally in one worktree does not affect another.
- **Exclusion entries edited by hand**: spaex owns only its own clearly delimited exclusion entries and restores them on install; entries outside that block are never touched.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST support two adoption scopes, project and local; project scope MUST keep its current behavior and be the default for every command.
- **FR-002**: The system MUST record local-scope adoptions in a per-checkout local overlay that is separate from the committed manifest and uses the same adoption shape (source, immutable revision, molecule list).
- **FR-003**: `add` and `remove` MUST accept an explicit option to target local scope; without it they MUST act on project scope exactly as today.
- **FR-004**: Install MUST apply project scope first and local scope on top in a single invocation; project-scope outputs MUST be byte-identical whether or not a local overlay exists.
- **FR-005**: The system MUST keep the local overlay, its lock and every local-scope output out of git automatically, using a per-checkout exclusion mechanism that is never committed and requires no change to any committed ignore file.
- **FR-006**: The system MUST refuse local-scope writes to any path that is owned by a project-scope molecule or tracked by git, before writing anything.
- **FR-007**: Local behavior fragments MUST be composed into a separate, uncommitted local behavior document; the committed composed constitution MUST NOT include them.
- **FR-008**: Agent-facing instructions MUST direct agents to load the local behavior document after the project constitution whenever it exists, and the local document MUST state that project rules prevail on conflict.
- **FR-009**: Local contributions to composable categories MUST be written to a separate local generated output; the project's generated output MUST NOT change.
- **FR-010**: Adopting a molecule locally that is already adopted in project scope MUST be refused; a molecule later adopted in project scope while also present locally MUST be reported as shadowed and contribute nothing from local scope.
- **FR-011**: Remove in local scope MUST delete every file only that local molecule contributed and drop its exclusion entries, leaving project files untouched.
- **FR-012**: Status, trace and constitution show MUST label each molecule, file and behavior section with its scope.
- **FR-013**: Local-scope Spec Kit integrations MUST be installed for the developer and excluded from git; an incompatible Spec Kit declaration across scopes MUST be refused.
- **FR-014**: Install hooks of local molecules MUST run under the same rules as project hooks, and the developer MUST be warned that files a hook writes on its own are not excluded automatically.
- **FR-015**: Install of both scopes MUST be deterministic: two consecutive installs on unchanged inputs produce byte-identical outputs in both scopes.
- **FR-016**: A failure in local scope MUST NOT leave project-scope outputs partially written; the installation either publishes a consistent result for both scopes or keeps the previous one.
- **FR-017**: An invalid local overlay MUST cause install to stop with a diagnostic that names the overlay and the problem.

### Key Entities

- **Local overlay**: per-checkout record of local adoptions; same structure as the project adoption list; never committed.
- **Local install record**: per-checkout record of what local scope installed (files, composed outputs, integrations, hook outcomes), the local counterpart to the project install record.
- **Local behavior document**: composed, human- and agent-readable rules from local behavior fragments; uncommitted; read after the project constitution.
- **Exclusion block**: the delimited, spaex-owned set of per-checkout ignore entries covering the overlay, the local record and all local outputs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After adopting any combination of local molecules and installing, `git status` in a previously clean checkout reports zero changes in 100% of tested scenarios.
- **SC-002**: The committed manifest, the composed project constitution and every project-scope output are byte-identical with and without a local overlay in 100% of tested scenarios.
- **SC-003**: A developer can adopt, inspect and remove a local molecule with three commands and no manual file edits.
- **SC-004**: Two consecutive installs with unchanged inputs produce byte-identical outputs in both scopes.
- **SC-005**: After removing every local adoption, no local-scope file and no spaex exclusion entry remains.
- **SC-006**: For every installed file, trace reports exactly one owning scope.

## Assumptions

- "User-wide" was clarified by the operator as **per developer, per project checkout** (not global across all repositories); a global per-user scope is out of scope for this feature.
- Precedence on conflict: project scope wins. Team policy is authoritative; local scope may add rules and files, never override or replace project content.
- Local scope is per checkout. Separate worktrees do not share local adoptions; sharing across worktrees can be added later if needed.
- Local adoptions follow the same pinning rules as project adoptions (repository plus full commit revision); there is no unpinned "latest" in local scope.
- Composing local behavior uses the same composition mechanism as project behavior, applied to local fragments only; the project constitution is not recomposed because of local changes.
- Molecules do not need to know which scope they are adopted in. A molecule that wants to consume local generated outputs (for example a development-environment definition reading an optional local package list) opts in on the publisher side; that is outside this feature.
- Agents find the local behavior document through the same bootstrap mechanism that already points them to the project constitution.
- Out of scope: promoting a local adoption to project scope in one command, a global per-user scope, and policy controls that let a team forbid local adoptions.
