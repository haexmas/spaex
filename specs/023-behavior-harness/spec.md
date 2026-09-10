# Feature Specification: Behavior Harness

**Feature Branch**: `023-behavior-harness`
**Created**: 2026-09-10
**Status**: Draft
**Input**: User description: "spaex's constitution layer becomes a behavior harness assembled from per-atom fragments; new atom type `atoms.behavior`; hybrid LLM+algebra Composer; strict conflict algebra; additive-only project overrides; multi-agent-portable emission (AGENTS.md primary, CLAUDE.md secondary). Full design in docs/plans/2026-09-10-behavior-harness-and-plugin-alignment-design.md."

**Related design records**:
- `docs/plans/2026-09-10-behavior-harness-and-plugin-alignment-design.md` (source of truth for all seven decisions)
- `docs/plans/2026-09-08-composition-ui-and-skills-externalization-roadmap.md` (phase context; this spec lands as an additive minor release, before the roadmap's Phase A)
- `specs/016-molecule-install-hooks/` (install-time side-effect machinery reused for fragment materialization)
- `specs/017-molecule-store/` (content-access pattern reused by fragment reads)

## Clarifications

### Session 2026-09-10

- Q: Fragment identifier scoping rule → A: Molecule-namespaced (`<molecule-id>/<fragment-id>`); cross-molecule collisions are impossible by construction, deletions stay surgical, semantic contradictions across molecules surface only through the Composer, not the mechanical pre-check.
- Q: When and how hard does the semantic plausibility check run → A: Warn-not-block on `spaex add` and `spaex remove`. When the fragment set changes, the Composer runs a plausibility check that flags any cross-molecule semantic contradiction with provenance and marks the composition state as "stale, unresolved" via a sidecar file. The `add`/`remove` operation itself completes and its own file writes (`.spaex.json`, `install.lock`) proceed; `.spaex.md` is NOT regenerated at this stage. On the next `spaex install`, the stale flag requires operator reconciliation before a fresh `.spaex.md` is written (FR-010a). See FR-024a for the mandated behavior.
- Q: How does the composed constitution reach the agent → A: Two-layer emission. A one-time GLOBAL bootstrap writes a small spaex-managed block into the user-global agent instruction file (`~/.claude/CLAUDE.md`, `~/.config/codex/AGENTS.md`, `~/.gemini/GEMINI.md`) that tells the agent "if `.spaex.md` exists in the current project root, read it and treat its content as project instructions". Gemini CLI's default is `~/.gemini/GEMINI.md`; operators who configure `context.fileName` differently may select the corresponding target explicitly. Per project, `spaex install` writes the composed constitution to a single file `.spaex.md` at the repo root; the entire file is spaex-owned. spaex NEVER modifies project-level `CLAUDE.md` or `AGENTS.md`.
- Q: Delimiter format for the spaex-managed section in the user-global instruction file → A: Paired HTML comment markers with a version attribute: `<!-- spaex-bootstrap:start version="1" -->` ... `<!-- spaex-bootstrap:end -->`. The version attribute lets spaex safely upgrade the block across releases without heuristic content analysis, and HTML comments are invisible in Markdown rendering while remaining git-merge-friendly.
- Q: What invalidates a persisted clarification answer → A: Content-hash of the involved fragment bodies (SHA256 over the Markdown body of every fragment cited in the clarification). Any character change to any involved fragment invalidates and triggers exactly one re-ask. Deterministic and conservative; whitespace normalization is optional.
- Q: What happens when the Composer fails (timeout, runtime error, malformed output) → A: Abort install with a diagnostic that names the specific failure category (timeout, invalid-output, runtime-error, quota-exceeded). If `.spaex.md` already exists, it is not touched; if it does not, none is created. Consumer decides whether to retry, switch runtime, or reduce the fragment set. Silent degradation to raw concatenation is explicitly rejected.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Consumer receives a composed behavior harness after install (Priority: P1)

A developer has previously run the one-time global bootstrap (Clarification Q3), so their agent runtimes (Claude Code, Codex CLI, Gemini CLI) already know to look for a `.spaex.md` file when they enter any project. They now work in a project that has adopted several molecules through `.spaex.json`. Each molecule contributes one or more atoms, some of which carry behavior directives (for example a `strict-testing` molecule contributes "run the test suite before every commit"; a `speckit-strict` molecule contributes "every non-trivial feature goes through spec-first authoring"). The developer runs `spaex install`. When it finishes, the repo contains a single `.spaex.md` file at the root that lists every active directive grouped by modality (MUST, SHOULD, MAY), each with a visible source. The developer opens their agent runtime in this project; it reads `.spaex.md` per the global bootstrap and respects the harness. Switching runtimes does not change the harness because every runtime reads the same `.spaex.md`.

**Why this priority**: this is the entire raison d'être of the feature. Without this outcome, the operator cannot get a per-project behavior harness that any agent respects.

**Independent Test**: given a fixture project with two pinned molecules that ship at least one behavior fragment each, running `spaex install` produces a `.spaex.md` at the repo root containing directives from both molecules with visible provenance. A runtime that has been through the global bootstrap and opens the project discovers `.spaex.md` without any project-level configuration.

**Acceptance Scenarios**:

1. **Given** a project pinning two molecules each shipping one behavior fragment, **When** the operator runs `spaex install`, **Then** `.spaex.md` exists at the repo root and lists both directives with a source label naming the originating molecule.
2. **Given** a fresh project with `.spaex.md` produced and a runtime that has run the global bootstrap, **When** the operator opens the runtime in the project, **Then** the runtime reads `.spaex.md` and treats its content as project instructions without any per-project configuration.
3. **Given** an operator switching agent runtime from Claude Code to Codex CLI in the same project, **When** they open the project without further configuration, **Then** the new runtime picks up the same behavior harness by reading the same `.spaex.md`.

---

### User Story 2 - Molecule author declares behavior fragments (Priority: P1)

A molecule author who wants their molecule to contribute behavioral rules (either as a dedicated behavior atom or attached to a typed atom like a speckit workflow) authors a fragment file with a small metadata header (identifier, source, tags, optional modality) followed by prose that expresses the directive. The author does not need to touch the composer, does not need to know how other atoms will interact, and does not need to know which agent runtimes their consumers use. Their published molecule then contributes the fragment automatically wherever it is installed.

**Why this priority**: authors are the supply side. Without a clear authoring path, no fragments exist and Story 1 has nothing to compose.

**Independent Test**: given the fragment-format documentation, an author writes a well-formed fragment file inside their molecule, publishes the molecule, and a consumer install includes the fragment in the composed constitution.

**Acceptance Scenarios**:

1. **Given** the documented fragment format, **When** a molecule author creates a fragment file with a valid header and Markdown body, **Then** the fragment validates without errors during molecule publish.
2. **Given** a typed atom (for example a speckit-workflow atom) that declares an inline behavior block alongside its primary payload, **When** the atom is consumed, **Then** the inline block is treated identically to a standalone behavior fragment.
3. **Given** a molecule that ships zero behavior fragments, **When** it is installed, **Then** its presence does not alter the composed constitution.

---

### User Story 3 - Hard conflict aborts install with named provenances (Priority: P2)

Because identifiers are molecule-scoped (Clarification Q1), a conflict between contradictory directives surfaces in one of two ways, and both must abort the install with clear provenance.

**Case A (intra-molecule, mechanical):** A molecule author accidentally ships two fragments under the same molecule-scoped identifier with negating modality (a fragment `strict-testing/no-mocks` declared MUST and another declared MUST NOT within the same molecule). The mechanical pre-check catches this at install time, exits non-zero fast, and names both fragment paths and their source atoms.

**Case B (cross-molecule, semantic):** Two pinned molecules ship fragments under different molecule-scoped identifiers (`strict-testing/no-mocked-db` MUST vs `fast-local-dev/mocked-db-ok` MUST) that the Composer identifies as semantically contradictory. The Composer surfaces this during the composed-constitution build. When the operator declines to reconcile via a clarification, the install aborts with a diagnostic that names both source molecules and their fragment paths.

In both cases the install refuses to write anything to the repo and explains what the operator must do (remove one molecule, add a project-local fragment that reconciles, or provide a clarification answer).

**Why this priority**: silent conflict resolution would let two authors contradict each other while consumers unwittingly follow one, breaking the trust contract that atoms are authoritative. The safety guarantee now spans both the fast mechanical path (Case A) and the semantic path (Case B).

**Independent Test**: two fixtures cover the two cases. Fixture A pins one molecule with two contradictory fragments under one molecule-scoped id; install exits non-zero on the mechanical pre-check without invoking the Composer. Fixture B pins two molecules with semantically contradictory fragments under different molecule-scoped ids; the Composer detects the contradiction and, absent a reconciling answer, install exits non-zero.

**Acceptance Scenarios**:

1. **Given** a single molecule shipping two fragments with the same molecule-scoped identifier and contradictory modality, **When** `spaex install` runs, **Then** the mechanical pre-check aborts before the Composer is invoked and the diagnostic names both fragment paths and their source atoms.
2. **Given** two molecules shipping fragments under different molecule-scoped identifiers that semantically contradict each other, **When** `spaex install` invokes the Composer, **Then** the Composer flags the semantic contradiction and asks the operator for reconciliation before writing the composed constitution.
3. **Given** either conflict case, **When** the install aborts, **Then** no tracked file in the consumer repo has been modified.
4. **Given** the operator resolves the conflict (remove a molecule for Case A, or provide a reconciling answer for Case B), **When** they re-run `spaex install`, **Then** the install proceeds and the composed constitution reflects the surviving or reconciled directive.

---

### User Story 4 - Clarification round resolves ambiguity, answers persist (Priority: P2)

The operator's fragment set has no hard conflicts but does contain semantically overlapping directives (for example, two molecules independently phrase the same idea in different words). During the composed-constitution build, the Composer detects the overlap, cannot decide from the fragments alone whether to merge them or keep both, and asks the operator one round of targeted questions ("These two directives appear to overlap. Are they the same rule expressed differently, or should both remain visible in the harness?"). The operator answers. The composed constitution is written. On subsequent builds against the same fragment set the operator is not asked again; the earlier answer is reused.

**Why this priority**: prose overlap is common in real-world atom sets. Without clarification, either the composer produces a redundant harness (visible duplication) or it silently guesses. Persisting answers keeps the flow non-annoying.

**Independent Test**: given a fragment set with a detectable overlap, running the composed-constitution build presents one targeted question, records the answer, and skips the question on the next build.

**Acceptance Scenarios**:

1. **Given** two fragments the Composer flags as semantically overlapping, **When** the build runs the first time, **Then** the operator sees one clarification question with the two candidate fragments cited.
2. **Given** the operator has answered a clarification, **When** they run the build again without changing fragments, **Then** the same question is not asked again and the earlier answer is applied.
3. **Given** the operator has answered a clarification and later a molecule change alters one of the two fragments materially, **When** the build runs again, **Then** the answer is treated as stale and the operator is re-asked.

---

### User Story 5 - Project adds additive local behavior fragments (Priority: P3)

A project maintainer decides that on top of the harness the molecules provide, the project itself should enforce additional rules ("all HTTP calls in this repo MUST go through the shared client"). They add the local fragment through the project's `.spaex.json` (either inline or as a file reference). The next `spaex install` includes the project-local fragment in the composed constitution alongside the atom-provided ones, with the source labeled as the project itself. They cannot use this mechanism to modify, disable, or downgrade an atom-provided fragment; if they try, the install aborts with a diagnostic that points them to the correct remedy (remove the molecule, or address the rule outside the harness).

**Why this priority**: real projects have real project-specific rules that no upstream molecule will ever carry. Additive-only preserves atom authority while giving projects the escape valve they need.

**Independent Test**: given a project that declares one project-local fragment and pins no molecules, `spaex install` produces a composed constitution that includes the project-local fragment with a project-source label. Given a project attempting to modify an atom-provided fragment, install aborts.

**Acceptance Scenarios**:

1. **Given** a project declaring one project-local fragment and pinning zero molecules, **When** `spaex install` runs, **Then** the composed constitution contains the project-local fragment with a source label naming the project.
2. **Given** a project declaring project-local fragments while also pinning molecules that ship fragments, **When** `spaex install` runs, **Then** all fragments (atom-provided and project-local) flow through the same mechanical pre-check and Composer path.
3. **Given** a project attempting to declare an override that would downgrade or disable an atom-provided fragment, **When** `spaex install` runs, **Then** the install aborts with a diagnostic that explains additive-only semantics and names the target fragment.

---

### User Story 6 - Cross-machine reproducibility via committed artifact (Priority: P3)

Two developers pull the same commit of a project onto their machines. The project's `.spaex.json`, its `.spaex/constitution.d/` fragment set, and its root `.spaex.md` are all under version control. Both developers run `spaex install`. Neither developer's Composer re-runs because `.spaex.md` is up to date with the fragment set. Both developers' agent runtimes read the same `.spaex.md`. If a third developer changes a molecule pin (adding new fragments), the Composer runs on their machine, `.spaex.md` is regenerated, and they commit the updated file so the other two see the change through git pull rather than through re-computation.

**Why this priority**: reproducibility is what turns a "harness" from a helpful suggestion into an actual constraint. Without committed artifacts, two developers on the same commit could produce different behavior sets.

**Independent Test**: given two clones of the same commit of a project with a committed `.spaex.md`, `spaex install` on both produces a byte-identical `.spaex.md` (or leaves the committed one untouched) and does not rerun the Composer.

**Acceptance Scenarios**:

1. **Given** a committed `.spaex.md` and unchanged fragments, **When** a fresh clone runs `spaex install`, **Then** the Composer is not invoked and `.spaex.md` is preserved unchanged.
2. **Given** a developer changes a molecule pin (adding new fragments), **When** they run `spaex install`, **Then** the Composer runs, `.spaex.md` is regenerated with a diff against the committed version, and the diff is stageable for commit.
3. **Given** `.spaex.md` and the fragment set drift out of sync (fragments changed on disk without a Composer run), **When** `spaex install` runs, **Then** the drift is detected and the Composer is invoked to regenerate `.spaex.md`.

---

### Edge Cases

- **Empty fragment set**: a project pinning molecules that ship zero behavior fragments produces either an empty `.spaex.md` or no `.spaex.md` at all (see FR-017d); the agent must not error when it looks for `.spaex.md` and does not find it.
- **All-permissive constitution**: a project whose only fragments use permissive modality (MAY) produces a composed constitution that lists them under MAY with no MUST or SHOULD sections.
- **Composer unavailable**: if no agent runtime is present on the machine to run the Composer, `spaex install` aborts with a clear diagnostic that names the reason and points to the documented remedies (install a supported runtime, or use a fallback mode if the operator opts in).
- **Duplicate identical fragments**: two atoms ship fragments with the same identifier AND semantically identical bodies. The system silently deduplicates rather than aborting on conflict; the composed constitution attributes the surviving clause to both source atoms.
- **Manually authored content in the user-global instruction file**: the user's global `~/.claude/CLAUDE.md` (or Codex/Gemini equivalent) already contains hand-written content when the global bootstrap installs. The bootstrap MUST live inside a clearly delimited spaex-managed section; content outside that section is preserved verbatim across upgrades and removals.
- **Manually authored project-level `CLAUDE.md` / `AGENTS.md`**: the consumer has hand-written content in project-level `CLAUDE.md` or `AGENTS.md`. spaex NEVER touches these files (per FR-017c). Operator-authored project instructions and the spaex composed constitution coexist; the agent reads both.
- **Bootstrap not yet installed**: the consumer runs `spaex install` in a project on a machine where the global bootstrap was never run. `.spaex.md` is produced, but agents opened in this project will not read it automatically. The system MUST surface this state at install time with a clear one-line hint pointing to the `spaex install --global` (or equivalent) subcommand.
- **Stale clarification**: the operator answered a clarification round, then a molecule bump changes the phrasing of one involved fragment. The clarification is invalidated, the operator is re-asked, and the previous answer is not silently reused.
- **Composer prompt version bump**: the canonical Composer prompt shipped by spaex changes across a spaex upgrade. All prior clarifications are invalidated; the next build re-asks. This is documented behavior.
- **Very large fragment count**: a project pins many molecules with many fragments. The Composer completes within a documented per-fragment budget; if the budget is exceeded, the operator sees a clear timeout diagnostic rather than a hung process.
- **Non-English fragment prose**: fragments authored in any natural language flow through unchanged. The Composer treats them semantically but does not translate.

## Requirements *(mandatory)*

### Functional Requirements

**Fragment authoring and materialization**

- **FR-001**: The system MUST accept behavior fragments contributed by any atom, using a declarative format that carries at minimum an identifier scoped to the fragment's owning molecule (per Clarification Q1: `<molecule-id>/<fragment-id>`), a source-atom reference, an optional modality declaration, optional tags, and a directive body written in Markdown.
- **FR-002**: The system MUST support a first-class atom category dedicated to behavior fragments, allowing a molecule to contribute rules without also carrying code, hooks, or MCP configs.
- **FR-003**: The system MUST support typed atoms (skills, MCPs, speckit workflows, and any other type where behavior is intrinsic) carrying inline behavior fragments alongside their primary payload, treated identically to standalone behavior fragments during composition.
- **FR-004**: The system MUST materialize every active behavior fragment to a canonical location under the consumer's repo during install, so the fragment set is inspectable, diff-able, and version-controllable.

**Mechanical pre-check**

- **FR-005**: The system MUST detect identifier-collisions within a single molecule where two fragments carry incompatible modality declarations (contradictory MUST / MUST NOT on the same molecule-scoped identifier) and abort install with a diagnostic that names both fragment paths and their source atoms.
- **FR-005a**: Because identifiers are molecule-scoped, cross-molecule semantic contradictions (two fragments in different molecules whose directive bodies contradict each other despite non-colliding identifiers) are NOT caught by the mechanical pre-check. The system MUST surface these during the Composer step (see FR-010a) and abort install if the operator does not provide a reconciling answer.
- **FR-006**: The system MUST NOT modify any tracked file in the consumer repo when the mechanical pre-check aborts an install.
- **FR-007**: The system MUST detect obviously malformed fragments (missing required header fields, invalid identifiers) during materialization and abort with a diagnostic that identifies the offending fragment.

**Composed constitution**

- **FR-008**: The system MUST produce a composed constitution artifact that synthesizes overlapping directives across fragments, organizes surviving statements by modality (MUST, SHOULD, MAY), and preserves per-clause provenance.
- **FR-009**: The system MUST invoke the Composer only when the fragment set, Composer prompt version, or any valid persisted clarification answer has changed since the last successful build. It MUST compare both `source_hash` and `build_input_hash`, so downstream consumers who pull unchanged content reuse the committed artifact without incurring a build.
- **FR-010**: When the Composer detects a semantic ambiguity that cannot be resolved from the fragment content alone, the system MUST ask the operator one bounded round of targeted clarification questions rather than guessing silently. A second unanswered Shape B response is an install failure.
- **FR-010a**: When the Composer detects a semantic contradiction between fragments in different molecules (per FR-005a), the system MUST present the contradiction to the operator as a reconciliation prompt. If the operator provides a reconciling answer (choose one modality, merge, or reject both), that answer is persisted per FR-011 and the composed constitution reflects the resolution. If the operator declines to reconcile, the install aborts per FR-005a.
- **FR-011**: The system MUST persist operator answers to clarification questions in a version-controlled location within the project so subsequent builds against the same fragment set do not re-ask the same question. Each stored answer MUST be keyed by the SHA256 hash of the Markdown bodies of every fragment cited in the clarification (per Clarification Q4).
- **FR-012**: The system MUST invalidate a persisted clarification whenever the SHA256 key computed from the current fragments differs from the stored key, and re-ask the operator exactly once on the next build. Whitespace-only differences MAY be normalized before hashing; semantic content differences MUST always invalidate.
- **FR-012a**: When the Composer fails (timeout, runtime error, malformed output, quota exceeded), the system MUST abort `spaex install` with a diagnostic that identifies the specific failure category and MUST NOT modify any existing `.spaex.md` or create a new one. Silent degradation to raw fragment concatenation is not a supported behavior; a consumer wanting a degraded harness MUST invoke it through an explicit, documented flag introduced in a future spec (not part of this one).
- **FR-013**: The composed constitution artifact (`.spaex.md` at the repo root) MUST be a version-controllable file that consumers commit alongside their `.spaex.json` and their `.spaex/constitution.d/` fragments, so cross-machine reproducibility is preserved without re-running the Composer.

**Emission**

**Global bootstrap** (one-time per user, opt-in per agent runtime)

- **FR-014**: The system MUST provide a mechanism (a CLI subcommand, for example `spaex install --global` for the chosen runtimes) that writes a small, static bootstrap block into the user-global agent-instruction file(s) of each runtime the user opts into. The block instructs the agent to read `.spaex.md` from the current project root when present and treat its content as project instructions.
- **FR-015**: The bootstrap block MUST live inside a clearly delimited spaex-managed section within the target global file, using paired HTML comment markers with a version attribute (per Clarification Q3: `<!-- spaex-bootstrap:start version="N" -->` ... `<!-- spaex-bootstrap:end -->`). The system MUST use these markers to detect its own block on upgrade and MUST NOT modify any content outside them.
- **FR-016**: The bootstrap block MUST NOT embed project-specific content. It is static across all projects; per-project content lives exclusively in each project's `.spaex.md`.
- **FR-017**: The system MUST support installing or updating the bootstrap block in the global instruction files of at least the three primary agent runtimes (Claude Code's `~/.claude/CLAUDE.md`, Codex CLI's global `AGENTS.md`, Gemini CLI's global `AGENTS.md`), and MUST be extensible to additional runtimes without breaking these three.

**Per-project emission** (every `spaex install`)

- **FR-017a**: The system MUST write the composed constitution to a single file `.spaex.md` at the consumer's repo root.
- **FR-017b**: The entire `.spaex.md` file is spaex-owned. The system MAY overwrite it in full on every install; there is no delimited section within `.spaex.md`.
- **FR-017c**: The system MUST NOT modify the consumer's project-level `CLAUDE.md`, `AGENTS.md`, or any other operator-authored instruction file at the project level. The agent picks up the constitution via the global-bootstrap indirection.
- **FR-017d**: When a project has no active behavior fragments (empty fragment set), the system MAY produce an empty `.spaex.md` or omit the file; both behaviors MUST NOT cause an agent to error.

**Project overrides**

- **FR-018**: The system MUST allow the project to contribute additive behavior fragments alongside molecule pins, either inline in `.spaex.json` or as file references to project-local fragment files.
- **FR-019**: The system MUST route project-local fragments through the same mechanical pre-check and the same Composer path as atom-provided fragments.
- **FR-020**: The system MUST reject any project-local fragment whose `fragment_id` matches one or more atom-provided fragments, regardless of their molecule scope, as well as any attempt to modify, disable, downgrade, or shadow an atom-provided fragment. The diagnostic MUST name every matching target and explain the additive-only semantics.

**Provenance and traceability**

- **FR-021**: The system MUST provide a per-clause provenance trail linking each rendered directive in the composed constitution back to one or more originating atoms, their molecules, and the composition profile that activated those molecules. A merged clause MUST retain every contributing source record.
- **FR-022**: The system MUST provide a documented mechanism (a CLI command or equivalent) that, given a directive text or identifier, prints its provenance.

**Multi-agent portability**

- **FR-023**: After the global bootstrap is installed for a given runtime (per FR-014), the system MUST guarantee that the runtime picks up any project's `.spaex.md` without further per-project configuration by the consumer. At minimum this applies to Claude Code, Codex CLI, and Gemini CLI. Additional runtimes (dsh, and others) MAY be added by extending the bootstrap to their global instruction files without breaking these three.
- **FR-024**: The per-project `.spaex.md` MUST be identical across runtimes; the multi-agent-portability contract is that the same composed constitution reaches every runtime that has run the global bootstrap.
- **FR-024a**: The system MUST run the Composer plausibility check whenever `spaex add` or `spaex remove` changes the active fragment set. On detected cross-molecule semantic contradiction, the system MUST print a WARN identifying the two involved fragments and their source molecules, mark the composition state as "stale, unresolved" via a sidecar file under `.spaex/`, and complete the `add`/`remove` operation without abort. The system MUST NOT regenerate `.spaex.md` from this check; that regeneration is deferred to the next `spaex install`, which then requires reconciliation before writing per FR-010a. See Clarification Q2.

### Key Entities

- **Behavior fragment**: a single-file declarative unit contributed by an atom, containing a small header (molecule-scoped identifier, source, optional modality, optional tags) and a Markdown body with directive prose. Identifiers are always resolved as `<molecule-id>/<fragment-id>`; cross-molecule id collisions are impossible by construction. Fragments are the atomic unit of the harness.
- **Behavior atom**: a first-class atom whose only payload is one or more behavior fragments. A molecule uses a behavior atom when it wants to contribute rules without also shipping code, hooks, MCPs, or skills.
- **Inline behavior block**: a behavior-fragment declaration embedded in the manifest of a typed atom (a speckit-workflow atom, for example). Composition treats inline blocks and standalone fragments identically.
- **Composed constitution**: the single generated artifact produced by the Composer from all active fragments. Committed to the consumer repo. Consumed by the emitters.
- **Constitution clarification**: a persisted operator answer to a Composer question about semantic ambiguity between fragments. Keyed by the involved fragments' content-hashes so it invalidates on material change.
- **Project-local fragment**: a fragment contributed by the project itself (not by any pinned molecule), stored inline in `.spaex.json` or as a project-controlled file. Additive only.
- **Per-project constitution file (`.spaex.md`)**: the single spaex-owned file at the consumer's repo root that contains the composed constitution. The entire file is spaex-managed; there is no delimited section within it.
- **Global bootstrap block**: the small, static spaex-managed section inside the user's global agent-instruction file (Claude Code's `~/.claude/CLAUDE.md`, Codex CLI's global `AGENTS.md`, Gemini CLI's global `AGENTS.md`) that tells the agent runtime to look for and read `.spaex.md` from the current project root. Installed once per user per runtime, upgradeable across spaex versions via the delimited section.
- **Provenance record**: the linkage from a rendered clause in the composed constitution back to its originating fragment, atom, and molecule. Rendered visibly next to the clause and queryable via a provenance-trace command.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consumer running install on a project pinning three molecules that each contribute at least one behavior fragment produces a composed constitution artifact within 30 seconds of the install starting, on a machine that already has the required agent runtime available.
- **SC-002**: 100% of intra-molecule hard conflicts (identifier-collision with contradictory modality within a single molecule) cause `spaex install` to exit non-zero on the mechanical pre-check without invoking the Composer and print a diagnostic that names both fragment paths and their source atoms. 100% of cross-molecule semantic contradictions surfaced by the Composer that the operator does not reconcile cause `spaex install` to exit non-zero and print a diagnostic naming both source molecules.
- **SC-003**: A composed constitution produced from an unchanged committed fragment set, prompt version, and valid clarification-answer set is byte-identical across any two consumer machines pulling the same commit; normal installs MUST reuse the committed artifact when both fingerprints match.
- **SC-004**: A molecule author following the documented authoring path adds a behavior fragment to their atom in under 5 minutes without reading spaex source code.
- **SC-005**: A project maintainer adds a local additive fragment through `.spaex.json` (inline or file reference) without editing any molecule source, and it appears in the composed constitution on the next install.
- **SC-006**: Every rendered clause in the composed constitution links back to every contributing originating atom via the documented provenance-trace command, including all sources of a merged clause.
- **SC-007**: A consumer who has run the global bootstrap for each of the three primary agent runtimes (Claude Code, Codex CLI, Gemini CLI) and then switches between them on the same project observes the same behavior harness without editing any file, because every runtime reads the same `.spaex.md`.
- **SC-008**: A clarification answered once by the operator is not re-asked on any subsequent build against the same fragment set (verified by identical SHA256 keys per FR-011). When any Markdown body of any involved fragment changes, the operator IS re-asked exactly once on the next build.
- **SC-011**: When the Composer fails for any reason (timeout, runtime error, malformed output, quota exceeded), `spaex install` exits non-zero with a diagnostic naming the failure category, and no existing `.spaex.md` is modified. Verified by fault-injection tests covering each failure category.
- **SC-009**: The global bootstrap never overwrites operator-authored content outside its clearly delimited section in the user's global instruction file, verified by preserving 100% of pre-existing content across a full round-trip of install, upgrade, and removal. Per-project `CLAUDE.md` / `AGENTS.md` files are never touched by spaex under any operation.
- **SC-010**: A project attempting to modify an atom-provided fragment aborts the install with a diagnostic that both names the target fragment and points to the additive-only remedy.

## Assumptions

- **Agent runtime availability**: the consumer has at least one supported agent runtime (Claude Code, Codex CLI, or Gemini CLI) installed on the machine where `spaex install` runs, so the Composer can invoke it for the LLM-synthesis step. When none is available, install aborts with a clear diagnostic (see edge case).
- **Global bootstrap is per-user, per-runtime, opt-in**: the consumer runs a one-time `spaex install --global` (or equivalent, exact CLI shape settled in the follow-up implementation spec) to install the bootstrap block into each agent runtime's global instruction file. Without the bootstrap, the runtime does not automatically read `.spaex.md`. The system surfaces this state at install time (see the "Bootstrap not yet installed" edge case).
- **Version control is git**: the consumer's repo is a git repository. The composed constitution artifact and its fragment set are committed via git.
- **RFC-2119 convention**: fragment authors use MUST / SHOULD / MAY (and negations) in prose as a convention understood by both the Composer and human readers. The pre-check does not parse prose to enforce modality; header-declared modality is the machine-checked signal.
- **English is a lingua franca, not a requirement**: fragments MAY be authored in any natural language. The Composer treats prose semantically but does not translate.
- **Composer prompt is canonical**: spaex ships one canonical Composer prompt. Projects MAY override it locally via a documented file, at the cost of taking ownership of clarification behavior for that project.
- **Materialization uses existing infra**: fragment materialization plugs into the Spec 016 install-hook boundary and the Spec 017 molecule-store content-access pattern. This spec does not re-derive the materialization mechanism; it constrains the observable behavior at the fragment interface.
- **Contextual-scope semantics are deferred**: fragments whose activation depends on runtime context (`scope: contextual`, `when: "..."`) are declared as a future extension. This spec covers only always-active fragments. A follow-up spec adds contextual scoping without breaking the always-active model.
- **Target release**: this spec targets spaex 4.2.0. The change is additive and does not break any consumer that today has zero behavior fragments in its molecule set. Consumers who adopt behavior fragments opt in by pinning molecules that ship them.
- **The 2026-09-08 roadmap sequencing shifts**: the behavior-harness lands before Phase A (skills externalization) rather than as Phase B. Phase A remains a 5.0.0 breaking change, unaffected by this spec.
