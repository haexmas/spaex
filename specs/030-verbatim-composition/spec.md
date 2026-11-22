# Feature Specification: Verbatim Constitution Composition

**Feature Branch**: `030-verbatim-composition`

**Created**: 2026-11-22

**Status**: Draft

**Input**: User description: "Verbatim constitution composition. `spaex install` currently has an LLM rewrite fragment bodies into one-line clauses (Composer, spec 023/026). Measured on the haex-vault repo (same fragments, two compositions): the Composer condenses large fragments (graphify-first-authoring: 32 rules in the fragment, 12 and 10 clauses in two compositions; ponytail 15 rules, 11 and 13 clauses), so rules are silently dropped, because the completeness check only requires each fragment to be cited once, and output differs on every install, so every install produces noise diffs. Change: the constitution text is no longer rewritten by an LLM. spaex itself renders every fragment body unchanged, ordered deterministically by scoped id, into `.spaex/constitution.md` (new format version 2); the LLM is reduced to detecting contradictions between fragments and returns only clarification questions or \"no findings\"; persisted clarification answers are rendered verbatim as a resolutions section. Same input gives byte-identical output without any LLM call when there are no new findings. Consumers of the clause grammar (`spaex constitution trace`, `spaex status` summary, completeness check, global bootstrap block, docs and format contract) move to the fragment-level format. The operator accepted that the constitution gets longer and that the format changes for every repo using spaex."

## Terminology

- **Fragment**: one constitution fragment file contributed by a molecule (spec 023), identified by its scoped id `<molecule-id>/<fragment-id>`.
- **Composed constitution**: the single document an agent reads at the start of a session (`.spaex/constitution.md`, and the local document of spec 029).
- **Verbatim**: a fragment body is emitted without summarizing, rewording, reordering, trimming whitespace or dropping content. Line endings are canonicalized to LF for stable output across checkouts.
- **Contradiction check**: the one step that still uses a language model. It reads the fragments, and either reports pairs that contradict each other or reports nothing. It never produces constitution text.
- **Resolution**: the operator's persisted answer to a contradiction question (spec 023 clarifications).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every rule of every fragment reaches the agent (Priority: P1)

An operator adopts molecules whose fragments carry long rule sets. After `spaex install`, the agent reads every rule of every fragment exactly as the molecule author wrote it, not a condensed version.

**Why this priority**: This is the defect. Today the model writing the constitution condenses large fragments and silently drops rules, and nothing detects it, because the completeness check accepts a fragment that is cited once. A constitution that loses rules gives false assurance.

**Independent Test**: Install a fragment set that contains one fragment of at least 30 rules. Compare each fragment body with the matching part of the composed constitution: all bodies are present byte for byte.

**Acceptance Scenarios**:

1. **Given** a project with several molecules and a fragment of 32 rules, **When** the operator runs `spaex install`, **Then** the composed constitution contains that fragment's body unchanged, all 32 rules.
2. **Given** any fragment set, **When** install finishes, **Then** every fragment appears exactly once in the composed constitution, introduced by a boundary naming its scoped id.
3. **Given** a fragment whose body contains headings, lists and code blocks, **When** install runs, **Then** all of that structure is preserved unchanged.

---

### User Story 2 - Installing again changes nothing (Priority: P1)

An operator runs `spaex install` again, on the same day or after a version bump of an unrelated molecule, and the composed constitution does not change unless a fragment changed.

**Why this priority**: Today every composition differs in wording, so every install produces a noisy diff and operators learn to ignore diffs of the constitution, or to revert them by hand. A reviewable constitution diff must mean that rules changed.

**Independent Test**: Run `spaex install` three times against the same fragments, including once after deleting the composed file. All outputs are byte-identical, and the second and later runs do not call any language model.

**Acceptance Scenarios**:

1. **Given** an unchanged fragment set and clarifications, **When** the operator runs install again, **Then** the composed constitution is byte-identical and no language model is invoked.
2. **Given** one fragment changed in one molecule, **When** install runs, **Then** the only differences in the composed constitution are inside or around that fragment.
3. **Given** the composed file was deleted, **When** install runs, **Then** it is recreated byte-identical to before, without a language model call if the fragments were already checked for contradictions.
4. **Given** a fragment set where the contradiction check reports nothing, **When** install runs on two different days or machines, **Then** the composed constitution is identical.

---

### User Story 3 - Contradictions are still found and resolved by the operator (Priority: P2)

Two molecules give contradictory instructions. The operator is told, decides once, and the decision becomes part of the constitution the agent reads.

**Why this priority**: The model was useful for exactly this judgement. It must keep doing it, but it must no longer be able to alter rule text while doing so.

**Independent Test**: Adopt two molecules with a contradictory MUST. Run install: a question naming both fragments appears. Answer it: the answer appears verbatim in a resolutions section, and both fragment bodies are still present unchanged.

**Acceptance Scenarios**:

1. **Given** two contradictory fragments and no resolution, **When** install runs, **Then** install stops with the question naming both fragments (as today: interactive prompt, or a documented non-zero exit when not interactive).
2. **Given** the operator answers, **When** install runs again, **Then** the composed constitution contains the answer verbatim in a resolutions section that names the fragments it concerns, and no fragment body is altered.
3. **Given** a persisted resolution and unchanged fragments, **When** install runs again, **Then** the model is not asked the same question again and the output is byte-identical.
4. **Given** a fragment concerned by a resolution changes, **When** install runs, **Then** the resolution is treated as outdated and the question is asked again (as today).

---

### User Story 4 - Existing repos move over once (Priority: P2)

An operator with a repo composed under the old format runs `spaex install` with the new version and ends up with a valid new-format constitution in one reviewable change.

**Why this priority**: Every repo that uses spaex (haex-vault, atoms consumers, spaex itself) is affected; the move has to be a plain install, not manual surgery.

**Independent Test**: Take a repo with a version 1 composed constitution and run `spaex install`. The file is rewritten as version 2 and a second run changes nothing.

**Acceptance Scenarios**:

1. **Given** a repo whose composed constitution carries format version 1, **When** the operator runs `spaex install`, **Then** it is replaced by a version 2 document containing every fragment verbatim.
2. **Given** a version 1 file and `spaex constitution build --check`, **When** the check runs, **Then** it reports the file as out of date.
3. **Given** persisted clarifications from version 1 (overlap and contradiction answers), **When** install runs, **Then** contradiction answers still apply, and overlap answers are ignored without error.

---

### User Story 5 - The tools that read the constitution keep working (Priority: P3)

`spaex constitution trace`, `spaex status` and the instruction block that tells agents where the constitution is keep working with the new format.

**Why this priority**: They read the old one-line clause format; without a change they would report nothing or fail.

**Independent Test**: On a version 2 constitution, run `spaex constitution trace <fragment id>` and `spaex status`: trace names the molecule and fragment of the match, and status reports the number of fragments and resolutions.

**Acceptance Scenarios**:

1. **Given** a version 2 constitution, **When** the operator runs `trace` with a fragment id or a phrase from a fragment, **Then** the output names the fragment's scoped id, molecule and the lines in the composed file.
2. **Given** a version 2 constitution, **When** the operator runs `spaex status`, **Then** the constitution summary reports fragments per molecule and the number of resolutions, without modality counts.
3. **Given** the local document of spec 029, **When** install runs, **Then** it is composed the same way and the project document stays byte-identical.

---

### Edge Cases

- A fragment body contains text that looks like a boundary marker. Boundary markers use the reserved `spaex-` comment form that spec 023 already rejects inside fragment bodies, so a fragment can never contain one.
- A fragment declares a `modality` in its header. The header is kept visible next to the fragment, not used to move the fragment to another place; the body decides, as before.
- Fragments do not end with a newline, or use different line endings. Rendering canonicalizes CRLF and CR to LF, preserving all other body characters, including trailing whitespace and the number of trailing newlines. It adds separators outside the body. Hash normalization from spec 023 MUST NOT be reused for rendering because it also trims whitespace and trailing blank lines.
- The contradiction check is unavailable (no runtime, timeout, bad output). The composed constitution does not depend on it, so it is still written in full and marked as not checked, and the operator is told (see FR-009).
- The fragment set is empty. Behaviour as today (the composed file is absent, spec 023 FR-017d).
- Two fragments say the same thing in different words. That is no longer a question: nothing is merged, both appear verbatim.
- Large fragment sets (haex-vault: about 930 lines of fragments). The file gets longer than today (about 185 lines); the operator accepted this.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The composed constitution MUST contain the complete body of every fragment, preserving all body characters except that CRLF and CR line endings are canonicalized to LF. It MUST NOT summarize, reword, trim whitespace, merge or omit body content.
- **FR-002**: Each fragment MUST appear exactly once, introduced by a machine-readable boundary that names its scoped id, in an order determined only by the scoped ids.
- **FR-003**: The text of the composed constitution, including any header metadata, MUST be produced by spaex itself, never by a language model, and MUST depend only on the fragments, the persisted resolutions and the format version. Contradiction-check prompt versions, results and check state MUST NOT affect the composed text.
- **FR-004**: For the same fragments and resolutions, the composed constitution MUST be byte-identical across runs, machines and days.
- **FR-005**: `spaex install` MUST NOT invoke a language model when the fragments, the resolutions and the contradiction-check prompt version are unchanged since the last completed check.
- **FR-006**: The contradiction check MUST be the only use of a language model in composition. Its result MUST be either contradiction questions naming the fragments involved, or no findings; it MUST NOT be able to change, add or remove constitution text.
- **FR-007**: A contradiction question MUST be handled as today: interactive prompt, persisted answer, documented non-zero exit when no operator can answer, and the answer invalidated when a fragment it concerns changes.
- **FR-008**: Persisted resolutions MUST be rendered verbatim in a resolutions section of the composed constitution, each naming the scoped ids it concerns, after the fragments, in a deterministic order.
- **FR-009**: When the contradiction check cannot run, `spaex install` MUST still write the full composed constitution, MUST say plainly that the contradiction check did not run, and MUST record that state outside the composed constitution so the next install retries; `spaex constitution build --check` MUST report the unchecked state. Check state MUST NOT affect the composed constitution's text.
- **FR-010**: Overlapping fragments MUST NOT cause questions or merging; only contradictions are questions.
- **FR-011**: The composed constitution MUST carry format version 2 in its header; a file with another version MUST be treated as out of date and rewritten by `spaex install`.
- **FR-012**: A mechanical completeness check MUST confirm after composing that every fragment body is present verbatim, and `spaex install` MUST fail without writing any tracked file if it is not (replaces the citation-based check).
- **FR-013**: `spaex constitution trace` MUST resolve a fragment id, a molecule id or a phrase from a fragment to the scoped ids and the line range in the composed file.
- **FR-014**: `spaex status` MUST report the constitution summary per fragment and per molecule, with the number of resolutions, and MUST NOT report modality counts derived from clauses.
- **FR-015**: The local constitution document of spec 029 MUST be composed by the same rules and MUST NOT change the project document.
- **FR-016**: The documented format contract, the CLI surface, the bootstrap block text and the user documentation MUST describe the version 2 format; the one-line clause grammar MUST be removed from them, or marked as version 1 only.
- **FR-017**: Persisted clarifications from earlier versions MUST keep working: contradiction answers apply, overlap answers are ignored without error.
- **FR-018**: Install failures MUST leave tracked files byte-unchanged, as in spec 023 FR-006.

### Key Entities

- **Fragment**: a molecule's rule document; its scoped id, optional declared modality and body are inputs.
- **Composed constitution**: header with format version and fingerprints, then the fragments in scoped-id order, then the resolutions section.
- **Fragment boundary**: the marker that begins a fragment block and names its scoped id; also what `trace` and the completeness check read.
- **Resolution**: an operator's answer to a contradiction question, with the scoped ids it concerns and a fingerprint of their bodies.
- **Check state**: whether the fragments were checked for contradictions at the current fragment fingerprint, was unchecked, or has open questions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the haex-vault fragment set (13 fragments from the coding, devshell and spaex molecules, about 930 lines), 100% of fragment lines appear in the composed constitution unchanged; today's compositions keep 10 to 12 of the 32 rules of the largest fragment.
- **SC-002**: Three consecutive installs on an unchanged fragment set produce byte-identical composed files, and runs after the first make 0 language-model calls.
- **SC-003**: After changing one fragment, the diff of the composed constitution is limited to that fragment's block, derived fingerprint metadata in the header, and any affected resolutions.
- **SC-004**: A deliberately contradictory pair of fragments is reported as a question in 100% of 5 independent, uncached contradiction checks, and the answer given appears verbatim in the composed constitution.
- **SC-005**: With the contradiction check made unavailable, install still finishes and writes a complete composed constitution in under 10 seconds for the haex-vault set, and reports the unchecked state.
- **SC-006**: A repo with a version 1 file reaches version 2 with one `spaex install` and a second install changes nothing.
- **SC-007**: `trace` and `status` produce correct output on a version 2 file for every fragment of the haex-vault set.

## Assumptions

- The fragment format of spec 023 does not change; only how fragments are put into the composed constitution changes.
- Fragment bodies are not rewritten, not even to demote their headings; boundaries are comment lines that cannot occur inside bodies, so the structure of a body stays untouched.
- Because fragments are no longer sorted by modality, the composed file has no modality sections. Agents read the modal words (MUST, SHOULD, MAY) inside each fragment, which is where the molecule author put them.
- A longer constitution is acceptable: about five times longer for haex-vault (operator decision, 2026-11-22).
- The contradiction check may use the same runtime selection as today; a failing check is a warning, not an abort, because the text no longer depends on it. A project that wants the stricter behavior can use `--check`, which fails on an unchecked state.
- The `.spaex/constitution.d/` copies of the fragments stay as they are.
- Releasing this as a new major version of spaex (format change for every consumer) is handled by the existing release process, with a breaking-change commit.
