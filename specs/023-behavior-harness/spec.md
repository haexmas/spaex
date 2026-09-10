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

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Consumer receives a composed behavior harness after install (Priority: P1)

A developer works in a project that has adopted several molecules through `.spaex.json`. Each molecule contributes one or more atoms, some of which carry behavior directives (for example a `strict-testing` molecule contributes "run the test suite before every commit"; a `speckit-strict` molecule contributes "every non-trivial feature goes through spec-first authoring"). The developer runs `spaex install`. When it finishes, the repo contains a composed constitution at a well-known path that lists every active directive grouped by modality (MUST, SHOULD, MAY), each with a visible source. The developer's agent runtime (Claude Code, Codex CLI, or Gemini CLI) picks up the harness automatically because the composed constitution has been emitted into the artifacts that runtime reads at session start.

**Why this priority**: this is the entire raison d'être of the feature. Without this outcome, the operator cannot get a per-project behavior harness that any agent respects.

**Independent Test**: given a fixture project with two pinned molecules that ship at least one behavior fragment each, running `spaex install` produces a composed constitution artifact at the documented path, and the documented artifact contains directives from both molecules with visible provenance.

**Acceptance Scenarios**:

1. **Given** a project pinning two molecules each shipping one behavior fragment, **When** the operator runs `spaex install`, **Then** a composed constitution artifact exists at the documented location and lists both directives with a source label naming the originating molecule.
2. **Given** a fresh project pinning molecules whose fragments have no conflicts, **When** `spaex install` completes, **Then** the emission targets (agent-neutral primary artifact plus at least one harness-specific artifact) contain the composed constitution in a clearly delimited section.
3. **Given** an operator switching agent runtime from Claude Code to Codex CLI, **When** they open the project without further configuration, **Then** the new runtime picks up the same behavior harness.

---

### User Story 2 - Molecule author declares behavior fragments (Priority: P1)

A molecule author who wants their molecule to contribute behavioral rules (either as a dedicated behavior atom or attached to a typed atom like a speckit workflow) authors a fragment file with a small metadata header (identifier, source, tags, optional modality) followed by prose that expresses the directive. The author does not need to touch the composer, does not need to know how other atoms will interact, and does not need to worry about the emission targets. Their published molecule then contributes the fragment automatically wherever it is installed.

**Why this priority**: authors are the supply side. Without a clear authoring path, no fragments exist and Story 1 has nothing to compose.

**Independent Test**: given the fragment-format documentation, an author writes a well-formed fragment file inside their molecule, publishes the molecule, and a consumer install includes the fragment in the composed constitution.

**Acceptance Scenarios**:

1. **Given** the documented fragment format, **When** a molecule author creates a fragment file with a valid header and Markdown body, **Then** the fragment validates without errors during molecule publish.
2. **Given** a typed atom (for example a speckit-workflow atom) that declares an inline behavior block alongside its primary payload, **When** the atom is consumed, **Then** the inline block is treated identically to a standalone behavior fragment.
3. **Given** a molecule that ships zero behavior fragments, **When** it is installed, **Then** its presence does not alter the composed constitution.

---

### User Story 3 - Hard conflict aborts install with named provenances (Priority: P2)

Two molecules the operator has pinned turn out to ship contradictory directives on the same identifier (for example, `no-mocked-db` MUST vs `mocked-db-ok` declared under the same identifier with negating modality). The operator runs `spaex install`. The install refuses to write anything to the repo, prints an error message that names both fragments, both source atoms, and both molecules, and explains what the operator must do (remove one molecule, or add a project-level clarification that resolves the conflict).

**Why this priority**: silent conflict resolution would let two molecule authors contradict each other while consumers unwittingly follow one, breaking the trust contract that atoms are authoritative. This is a safety guarantee.

**Independent Test**: given a fixture project pinning two molecules whose fragments carry the same identifier with contradictory modality, `spaex install` exits non-zero, does not modify any tracked file, and prints both molecule sources.

**Acceptance Scenarios**:

1. **Given** two active fragments sharing an identifier with contradictory modality, **When** `spaex install` runs, **Then** the process exits non-zero and prints a diagnostic that names both molecules and both fragment paths.
2. **Given** the same conflict, **When** the install aborts, **Then** no tracked file in the consumer repo has been modified.
3. **Given** the operator removes one of the two conflicting molecules, **When** they re-run `spaex install`, **Then** the install proceeds and the composed constitution includes the surviving directive.

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

Two developers pull the same commit of a project onto their machines. The project's `.spaex.json` and its `.spaex/constitution.d/` and `.spaex/constitution.md` are all under version control. Both developers run `spaex install`. Neither developer sees any new re-generation of the composed constitution because the committed artifact is up to date with the fragment set. Both developers' agent runtimes read the same emitted content. If a third developer changes a molecule pin, the composed constitution rebuilds on their machine, they commit the updated artifact, and the other two developers see the change through git pull, not through re-computation.

**Why this priority**: reproducibility is what turns a "harness" from a helpful suggestion into an actual constraint. Without committed artifacts, two developers on the same commit could produce different behavior sets.

**Independent Test**: given two clones of the same commit of a project with a committed composed constitution, `spaex install` on both produces byte-identical emission-target content and does not rerun the Composer.

**Acceptance Scenarios**:

1. **Given** a committed composed constitution and unchanged fragments, **When** a fresh clone runs `spaex install`, **Then** the Composer is not invoked and the emission targets are populated from the committed artifact.
2. **Given** a developer changes a molecule pin (adding new fragments), **When** they run `spaex install`, **Then** the Composer runs, the new composed constitution differs from the committed one, and the diff is stageable for commit.
3. **Given** the composed constitution and fragment set drift out of sync (fragments changed on disk without a Composer run), **When** `spaex install` runs, **Then** the drift is detected and the Composer is invoked.

---

### Edge Cases

- **Empty fragment set**: a project pinning molecules that ship zero behavior fragments produces a minimal composed constitution artifact (or no artifact at all), never an error.
- **All-permissive constitution**: a project whose only fragments use permissive modality (MAY) produces a composed constitution that lists them under MAY with no MUST or SHOULD sections.
- **Composer unavailable**: if no agent runtime is present on the machine to run the Composer, `spaex install` aborts with a clear diagnostic that names the reason and points to the documented remedies (install a supported runtime, or use a fallback mode if the operator opts in).
- **Duplicate identical fragments**: two atoms ship fragments with the same identifier AND semantically identical bodies. The system silently deduplicates rather than aborting on conflict; the composed constitution attributes the surviving clause to both source atoms.
- **Manually authored content in emission target**: the consumer has hand-written content in `CLAUDE.md` or `AGENTS.md` before spaex ever touched the repo. Emission never overwrites operator-authored content; spaex-managed content lives inside a clearly delimited section, and content outside that section is preserved verbatim.
- **Stale clarification**: the operator answered a clarification round, then a molecule bump changes the phrasing of one involved fragment. The clarification is invalidated, the operator is re-asked, and the previous answer is not silently reused.
- **Composer prompt version bump**: the canonical Composer prompt shipped by spaex changes across a spaex upgrade. All prior clarifications are invalidated; the next build re-asks. This is documented behavior.
- **Very large fragment count**: a project pins many molecules with many fragments. The Composer completes within a documented per-fragment budget; if the budget is exceeded, the operator sees a clear timeout diagnostic rather than a hung process.
- **Non-English fragment prose**: fragments authored in any natural language flow through unchanged. The Composer treats them semantically but does not translate.

## Requirements *(mandatory)*

### Functional Requirements

**Fragment authoring and materialization**

- **FR-001**: The system MUST accept behavior fragments contributed by any atom, using a declarative format that carries at minimum an identifier, a source-atom reference, an optional modality declaration, optional tags, and a directive body written in Markdown.
- **FR-002**: The system MUST support a first-class atom category dedicated to behavior fragments, allowing a molecule to contribute rules without also carrying code, hooks, or MCP configs.
- **FR-003**: The system MUST support typed atoms (skills, MCPs, speckit workflows, and any other type where behavior is intrinsic) carrying inline behavior fragments alongside their primary payload, treated identically to standalone behavior fragments during composition.
- **FR-004**: The system MUST materialize every active behavior fragment to a canonical location under the consumer's repo during install, so the fragment set is inspectable, diff-able, and version-controllable.

**Mechanical pre-check**

- **FR-005**: The system MUST detect identifier-collisions between fragments that carry incompatible modality declarations (contradictory MUST / MUST NOT on the same identifier) and abort install with a diagnostic that names both fragment paths, both source atoms, and both source molecules.
- **FR-006**: The system MUST NOT modify any tracked file in the consumer repo when the mechanical pre-check aborts an install.
- **FR-007**: The system MUST detect obviously malformed fragments (missing required header fields, invalid identifiers) during materialization and abort with a diagnostic that identifies the offending fragment.

**Composed constitution**

- **FR-008**: The system MUST produce a composed constitution artifact that synthesizes overlapping directives across fragments, organizes surviving statements by modality (MUST, SHOULD, MAY), and preserves per-clause provenance.
- **FR-009**: The system MUST invoke the Composer only when the fragment set (content) or the Composer configuration has changed since the last successful build, so downstream consumers who pull unchanged content reuse the committed artifact without incurring a build.
- **FR-010**: When the Composer detects a semantic ambiguity that cannot be resolved from the fragment content alone, the system MUST ask the operator one round of targeted clarification questions rather than guessing silently.
- **FR-011**: The system MUST persist operator answers to clarification questions in a version-controlled location within the project so subsequent builds against the same fragment set do not re-ask the same question.
- **FR-012**: The system MUST invalidate a persisted clarification when the involved fragments' content changes materially, and re-ask the operator on the next build.
- **FR-013**: The composed constitution artifact MUST be a version-controllable file that consumers commit alongside their `.spaex.json`, so cross-machine reproducibility is preserved without re-running the Composer.

**Emission**

- **FR-014**: The system MUST emit the composed constitution into an agent-neutral primary artifact at the consumer's repo root (`AGENTS.md`), inside a clearly delimited spaex-managed section.
- **FR-015**: The system MUST also emit the composed constitution into at least one harness-specific artifact (`CLAUDE.md` at minimum), inside a clearly delimited spaex-managed section, so runtimes that prefer their native file discover the harness.
- **FR-016**: The system MUST NOT overwrite content outside the spaex-managed section of any emission-target file, so consumer-authored instructions are preserved verbatim across installs.
- **FR-017**: When an emission-target file does not yet exist, the system MUST create it containing only the spaex-managed section.

**Project overrides**

- **FR-018**: The system MUST allow the project to contribute additive behavior fragments alongside molecule pins, either inline in `.spaex.json` or as file references to project-local fragment files.
- **FR-019**: The system MUST route project-local fragments through the same mechanical pre-check and the same Composer path as atom-provided fragments.
- **FR-020**: The system MUST reject any project attempt to modify, disable, downgrade, or shadow an atom-provided fragment, with a diagnostic that names the target fragment and explains the additive-only semantics.

**Provenance and traceability**

- **FR-021**: The system MUST provide a per-clause provenance trail linking each rendered directive in the composed constitution back to exactly one originating atom, its molecule, and the composition profile that activated the molecule.
- **FR-022**: The system MUST provide a documented mechanism (a CLI command or equivalent) that, given a directive text or identifier, prints its provenance.

**Multi-agent portability**

- **FR-023**: The system MUST produce emission artifacts that at minimum the following agent runtimes discover without any additional consumer configuration: Claude Code (reading `CLAUDE.md`), Codex CLI (reading `AGENTS.md`), and Gemini CLI (reading `AGENTS.md`). Additional harnesses (dsh, and others) MAY be added later without breaking any of these three.
- **FR-024**: The system MUST NOT require the consumer to author target-runtime-specific content by hand for these three runtimes to pick up the harness.

### Key Entities

- **Behavior fragment**: a single-file declarative unit contributed by an atom, containing a small header (identifier, source, optional modality, optional tags) and a Markdown body with directive prose. Fragments are the atomic unit of the harness.
- **Behavior atom**: a first-class atom whose only payload is one or more behavior fragments. A molecule uses a behavior atom when it wants to contribute rules without also shipping code, hooks, MCPs, or skills.
- **Inline behavior block**: a behavior-fragment declaration embedded in the manifest of a typed atom (a speckit-workflow atom, for example). Composition treats inline blocks and standalone fragments identically.
- **Composed constitution**: the single generated artifact produced by the Composer from all active fragments. Committed to the consumer repo. Consumed by the emitters.
- **Constitution clarification**: a persisted operator answer to a Composer question about semantic ambiguity between fragments. Keyed by the involved fragments' content-hashes so it invalidates on material change.
- **Project-local fragment**: a fragment contributed by the project itself (not by any pinned molecule), stored inline in `.spaex.json` or as a project-controlled file. Additive only.
- **Emission target**: a consumer-repo file into which spaex writes a spaex-managed section containing the composed constitution. Includes at minimum the agent-neutral `AGENTS.md` and one harness-specific artifact (`CLAUDE.md`).
- **Provenance record**: the linkage from a rendered clause in the composed constitution back to its originating fragment, atom, and molecule. Rendered visibly next to the clause and queryable via a provenance-trace command.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consumer running install on a project pinning three molecules that each contribute at least one behavior fragment produces a composed constitution artifact within 30 seconds of the install starting, on a machine that already has the required agent runtime available.
- **SC-002**: 100% of hard conflicts (identifier-collision with contradictory modality) cause the install to exit non-zero and print a diagnostic that names both source molecules and both source fragment paths.
- **SC-003**: A composed constitution produced from an unchanged committed fragment set is byte-identical across any two consumer machines pulling the same commit.
- **SC-004**: A molecule author following the documented authoring path adds a behavior fragment to their atom in under 5 minutes without reading spaex source code.
- **SC-005**: A project maintainer adds a local additive fragment through `.spaex.json` (inline or file reference) without editing any molecule source, and it appears in the composed constitution on the next install.
- **SC-006**: Every rendered clause in the composed constitution links back to exactly one originating atom via the documented provenance-trace command.
- **SC-007**: A consumer switching between the three primary agent runtimes (Claude Code, Codex CLI, Gemini CLI) on the same project observes the same behavior harness without editing any file.
- **SC-008**: A clarification answered once by the operator is not re-asked on any subsequent build against the same fragment set; when a fragment involved in the clarification changes materially, the operator IS re-asked exactly once.
- **SC-009**: Emission never overwrites operator-authored content outside the spaex-managed section of any emission target, verified by preserving 100% of pre-existing content across a full round-trip of `spaex install`.
- **SC-010**: A project attempting to modify an atom-provided fragment aborts the install with a diagnostic that both names the target fragment and points to the additive-only remedy.

## Assumptions

- **Agent runtime availability**: the consumer has at least one supported agent runtime (Claude Code, Codex CLI, or Gemini CLI) installed on the machine where `spaex install` runs, so the Composer can invoke it for the LLM-synthesis step. When none is available, install aborts with a clear diagnostic (see edge case).
- **Version control is git**: the consumer's repo is a git repository. The composed constitution artifact and its fragment set are committed via git.
- **RFC-2119 convention**: fragment authors use MUST / SHOULD / MAY (and negations) in prose as a convention understood by both the Composer and human readers. The pre-check does not parse prose to enforce modality; header-declared modality is the machine-checked signal.
- **English is a lingua franca, not a requirement**: fragments MAY be authored in any natural language. The Composer treats prose semantically but does not translate.
- **Composer prompt is canonical**: spaex ships one canonical Composer prompt. Projects MAY override it locally via a documented file, at the cost of taking ownership of clarification behavior for that project.
- **Materialization uses existing infra**: fragment materialization plugs into the Spec 016 install-hook boundary and the Spec 017 molecule-store content-access pattern. This spec does not re-derive the materialization mechanism; it constrains the observable behavior at the fragment interface.
- **Contextual-scope semantics are deferred**: fragments whose activation depends on runtime context (`scope: contextual`, `when: "..."`) are declared as a future extension. This spec covers only always-active fragments. A follow-up spec adds contextual scoping without breaking the always-active model.
- **Target release**: this spec targets spaex 4.2.0. The change is additive and does not break any consumer that today has zero behavior fragments in its molecule set. Consumers who adopt behavior fragments opt in by pinning molecules that ship them.
- **The 2026-09-08 roadmap sequencing shifts**: the behavior-harness lands before Phase A (skills externalization) rather than as Phase B. Phase A remains a 5.0.0 breaking change, unaffected by this spec.
