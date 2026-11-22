# Feature Specification: Verbatim Constitution Composition

**Feature Branch**: `030-verbatim-composition`

**Created**: 2026-11-22

**Status**: Draft

**Input**: User description: "Verbatim constitution composition. `spaex install` currently has an LLM rewrite fragment bodies into one-line clauses (Composer, spec 023/026). Measured on the haex-vault repo (same fragments, two compositions): the Composer condenses large fragments (graphify-first-authoring: 32 rules in the fragment, 12 and 10 clauses in two compositions; ponytail 15 rules, 11 and 13 clauses), so rules are silently dropped, because the completeness check only requires each fragment to be cited once, and output differs on every install, so every install produces noise diffs. Change: the constitution text is no longer rewritten by an LLM. spaex itself renders every fragment body unchanged, ordered deterministically by scoped id, into `.spaex/constitution.md` (new format version 2). The LLM only finds contradictions and duplicates between passages of different fragments; spaex always asks the operator what to do with each finding, and the decision is applied by commenting out the passage that is not kept, never by rewording. The sources come from different authors and cannot be changed for every consumer, so the merged constitution itself must be coherent: free of contradictions and duplicates. Same fragments and decisions give byte-identical output without any LLM call. Consumers of the clause grammar (`spaex constitution trace`, `spaex status` summary, completeness check, global bootstrap block, docs and format contract) move to the fragment-level format. The operator accepted that the constitution gets longer and that the format changes for every repo using spaex."

## Clarifications

### Session 2026-11-22

- Q: How are contradictions and duplicates handled when the text may not be rewritten and the sources cannot be changed for each consumer? → A: Both are reported to the operator, who always decides. The passage that is not kept is commented out in the composed constitution; its text stays unchanged except that a `-->` line is escaped as `--&gt;` so it cannot terminate the comment. Nothing is resolved automatically and nothing is only warned about; a constitution with open findings is not written.
- Q: Are duplicates only a warning? → A: No. Duplicates are findings like contradictions, with the same question and the same way to apply the decision, because the composed constitution must be free of both.
- Q: Must the operator's decision be reproducible? → A: Yes. Decisions are persisted, are tied to the exact text of the passages, and make the composed constitution a pure function of fragments and decisions.

## Terminology

- **Fragment**: one constitution fragment file contributed by a molecule (spec 023), identified by its scoped id `<molecule-id>/<fragment-id>`.
- **Composed constitution**: the single document an agent reads at the start of a session (`.spaex/constitution.md`, and the local document of spec 029).
- **Verbatim**: a fragment body is emitted without summarizing, rewording, reordering, trimming whitespace or dropping content. Line endings are canonicalized to LF for stable output across checkouts.
- **Passage**: a contiguous run of lines of one fragment body, named by the fragment's scoped id and its line range. Passages are what findings and decisions refer to; spaex checks that a named passage exists.
- **Finding**: a contradiction (two or more passages that cannot both be followed) or a duplicate (two or more passages that give the same instruction) between passages of different fragments, reported by the check.
- **Check**: the one step that still uses a language model. It reads the fragments and reports findings or nothing. It never produces constitution text.
- **Decision**: the operator's persisted answer to one finding: keep one passage (the others are excluded) or keep all (not a real finding).
- **Excluded passage**: a passage the operator did not keep. It stays in the composed constitution as a comment that carries its original text and says it is excluded, so it is not an instruction but is still visible and traceable.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The agent reads the authors' rules, not a rewrite (Priority: P1)

An operator adopts molecules whose fragments carry long rule sets. After `spaex install`, the agent reads every rule exactly as its author wrote it, except the passages the operator decided to exclude; nothing is condensed, reworded or lost on the way.

**Why this priority**: This is the defect. Today the model writing the constitution condenses large fragments and silently drops rules, and nothing detects it, because the completeness check accepts a fragment that is cited once.

**Independent Test**: Install a fragment set that contains one fragment of at least 30 rules and no findings. Normalize CRLF and CR to LF in each expected fragment body, then compare it byte for byte with the matching part of the composed constitution, preserving all other whitespace: all bodies are present.

**Acceptance Scenarios**:

1. **Given** a project with several molecules and a fragment of 32 rules, **When** the operator runs `spaex install`, **Then** the composed constitution contains that fragment's body unchanged (apart from LF line endings), all 32 rules.
2. **Given** any fragment set, **When** install finishes, **Then** every fragment appears exactly once, introduced by a boundary naming its scoped id.
3. **Given** a fragment whose body contains headings, lists and code blocks, **When** install runs, **Then** all of that structure is preserved unchanged.

---

### User Story 2 - Installing again changes nothing (Priority: P1)

An operator runs `spaex install` again, on another day or machine, and the composed constitution does not change unless a fragment or a decision changed.

**Why this priority**: Today every composition differs in wording, so every install produces a noisy diff. A reviewable constitution diff must mean that rules changed.

**Independent Test**: Run `spaex install` three times against the same fragments and decisions, once after deleting the composed file. All outputs are byte-identical, and the second and later runs do not call any language model.

**Acceptance Scenarios**:

1. **Given** unchanged fragments and decisions, **When** the operator runs install again, **Then** the composed constitution is byte-identical and no language model is invoked.
2. **Given** one fragment changed, **When** install runs, **Then** the only differences are inside or around that fragment's block.
3. **Given** the composed file was deleted, **When** install runs, **Then** it is recreated byte-identical, without a language model call, because the decisions are persisted.
4. **Given** the same fragments and decisions on two machines, **When** install runs on each, **Then** the composed constitutions are identical.

---

### User Story 3 - Contradictions and duplicates are resolved by the operator, never silently (Priority: P1)

Sources come from different authors. Two fragments contradict each other, or say the same thing. The operator is shown both passages, decides which to keep, and the composed constitution ends up with one coherent instruction, without anyone rewriting a source.

**Why this priority**: The merged constitution has to be coherent, and the sources cannot be changed for each consumer. This is the one judgement that still needs the model and the operator.

**Independent Test**: Adopt two molecules with a contradictory MUST and a third pair with the same instruction twice. Run install: two questions appear, each showing both passages. Choose which to keep. The composed constitution contains the kept passages unchanged and the others commented out, and a second install asks nothing.

**Acceptance Scenarios**:

1. **Given** two contradictory passages and no decision, **When** install runs interactively, **Then** the operator is shown both passages with their fragment and lines and chooses: keep the first, keep the second, or keep both.
2. **Given** two duplicate passages, **When** install runs, **Then** the same question is asked and answered in the same way.
3. **Given** the operator keeps one passage, **When** the constitution is written, **Then** the other passage is commented out, its text unchanged inside the comment except that any `-->` line is escaped as `--&gt;`, marked as excluded and naming the passage that was kept; all other text is unchanged.
4. **Given** the operator keeps both, **When** the constitution is written, **Then** nothing is commented out and the decision is recorded so the finding is not asked again.
5. **Given** a finding and no operator available (not interactive), **When** install runs, **Then** it stops with the documented non-zero exit, names the finding, and changes no tracked file.
6. **Given** a persisted decision and unchanged passages, **When** install runs, **Then** the finding is not asked again and the output is byte-identical.
7. **Given** a passage a decision concerns changes, **When** install runs, **Then** the decision is outdated and the finding is asked again if it still exists.

---

### User Story 4 - Existing repos move over once (Priority: P2)

An operator with a repo composed under the old format runs `spaex install` with the new version and ends up with a valid new-format constitution in one reviewable change.

**Why this priority**: Every repo that uses spaex (haex-vault, atoms consumers, spaex itself) is affected; the move has to be a plain install, not manual surgery.

**Independent Test**: Take a repo with a version 1 composed constitution and run `spaex install`. The file is rewritten as version 2, and a second run changes nothing.

**Acceptance Scenarios**:

1. **Given** a repo whose composed constitution carries format version 1, **When** the operator runs `spaex install`, **Then** it is replaced by a version 2 document containing every fragment verbatim, after the operator answered the findings.
2. **Given** a version 1 file and `spaex constitution build --check`, **When** the check runs, **Then** it reports the file as out of date.
3. **Given** persisted answers from version 1, **When** install runs, **Then** they are not reused as decisions (they refer to rewritten clauses, not passages) and the findings are asked again.

---

### User Story 5 - The tools that read the constitution keep working (Priority: P3)

`spaex constitution trace`, `spaex status` and the instruction block that tells agents where the constitution is keep working with the new format.

**Why this priority**: They read the old one-line clause format; without a change they would report nothing or fail.

**Independent Test**: On a version 2 constitution with one decision, run `spaex constitution trace <fragment id>` and `spaex status`: trace names the molecule, fragment and lines, and says if a passage is excluded; status reports fragments, decisions and excluded passages.

**Acceptance Scenarios**:

1. **Given** a version 2 constitution, **When** the operator runs `trace` with a fragment id or a phrase, **Then** the output names the fragment's scoped id, molecule and the line range in the composed file, and marks excluded passages.
2. **Given** a version 2 constitution, **When** the operator runs `spaex status`, **Then** the summary reports fragments per molecule, the decisions and the number of excluded passages, without modality counts.
3. **Given** the local document of spec 029, **When** install runs, **Then** it is composed the same way and the project document stays byte-identical.

---

### Edge Cases

- A fragment body contains text that looks like a boundary or exclusion marker. Markers use the reserved `spaex-` comment form that spec 023 already rejects inside fragment bodies, so a fragment can never contain one.
- A passage to exclude contains the comment terminator. Inside an excluded passage only, the terminator is neutralized so the comment stays closed; this is the one change made to text, and only to text that is no longer an instruction.
- The check names a passage that does not exist (line range outside the body, or another fragment). spaex rejects the finding; the check is retried as for any unusable check output (spec 026), and install fails without writing if it stays unusable.
- The check names the same fragment twice, or passages of the same fragment. Findings are between passages of different fragments; others are rejected.
- Excluded passages of two decisions overlap. The union is commented out once.
- Fragments do not end with a newline, or use different line endings. Rendering canonicalizes CRLF and CR to LF, preserving all other body characters, including trailing whitespace and the number of trailing newlines. It adds separators outside the body. The whitespace normalization of spec 023 hashing MUST NOT be reused for rendering, because it also trims whitespace and trailing blank lines.
- A fragment declares a `modality` in its header. The header is kept visible next to the fragment, not used to move it; the body decides, as before.
- The check is unavailable (no runtime, timeout, unusable output). A coherent constitution cannot be guaranteed, so install fails without changing any tracked file, as it does for any composition failure today.
- The fragment set is empty. Behaviour as today (the composed file is absent, spec 023 FR-017d).
- Large fragment sets (haex-vault: about 930 lines of fragments). The file gets longer than today (about 185 lines); the operator accepted this.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The composed constitution MUST contain the complete body of every fragment, preserving all body characters except that CRLF and CR line endings are canonicalized to LF, and with nothing summarized, reworded, trimmed, merged or omitted, except passages the operator excluded (FR-009).
- **FR-002**: Each fragment MUST appear exactly once, introduced by a machine-readable boundary that names its scoped id, in an order determined only by the scoped ids.
- **FR-003**: The text of the composed constitution, including any header metadata, MUST be produced by spaex itself, never by a language model, and MUST depend only on the fragments, the persisted decisions and the format version. The check's prompt version, results and state MUST NOT affect the composed text.
- **FR-004**: For the same fragments and decisions, the composed constitution MUST be byte-identical across runs, machines and days.
- **FR-005**: `spaex install` MUST NOT invoke a language model when the fragments, the decisions and the check's prompt version are unchanged since the last completed check.
- **FR-006**: The check MUST be the only use of a language model in composition. Its result MUST be a list of findings, each naming at least two passages of different fragments, or nothing; it MUST NOT be able to change, add or remove constitution text.
- **FR-007**: spaex MUST verify every passage a finding names (fragment exists, line range lies inside the body) and MUST reject a finding that names an unverifiable passage.
- **FR-008**: Every finding, contradiction or duplicate, MUST be put to the operator; spaex MUST NOT resolve a finding on its own, and MUST NOT write a composed constitution while a finding has no decision. When no operator can answer, install MUST stop with a documented non-zero exit naming the finding.
- **FR-009**: For each finding the operator MUST be able to choose which passage to keep (the others are excluded) or to keep all. An excluded passage MUST stay in the composed constitution as a comment that contains its text unchanged, states that it is excluded and names the kept passage. To keep the comment well-formed, a line exactly equal to `-->` MUST be represented as `--&gt;`; this is the only permitted text change inside an exclusion.
- **FR-010**: Decisions MUST be persisted, MUST be tied to the exact text of the passages they concern, and MUST be asked again only when a concerned passage changed or no longer exists.
- **FR-011**: A decision to keep all MUST be recorded and respected like any other, so the same finding is not asked again.
- **FR-012**: When the check cannot run or its output stays unusable, `spaex install` MUST fail without changing any tracked file (spec 023 FR-006); it MUST NOT write a constitution that was not checked.
- **FR-013**: The composed constitution MUST carry format version 2 in its header; a file with another version MUST be treated as out of date and rewritten by `spaex install`. Answers persisted by version 1 MUST NOT be reused as decisions.
- **FR-014**: A mechanical completeness check MUST confirm after composing that every passage that is not excluded is present verbatim, and every excluded passage is present inside its exclusion comment with only the `-->` to `--&gt;` escaping permitted by FR-009; `spaex install` MUST fail without writing any tracked file if not (replaces the citation-based check).
- **FR-015**: `spaex constitution trace` MUST resolve a fragment id, a molecule id or a phrase from a fragment to the scoped ids and the line range in the composed file, and MUST mark excluded passages.
- **FR-016**: `spaex status` MUST report the constitution summary per fragment and molecule, with the number of decisions and excluded passages, and MUST NOT report modality counts derived from clauses.
- **FR-017**: The local constitution document of spec 029 MUST be composed by the same rules and MUST NOT change the project document.
- **FR-018**: The documented format contract, the CLI surface, the bootstrap block text and the user documentation MUST describe the version 2 format; the one-line clause grammar MUST be removed from them or marked as version 1 only.
- **FR-019**: Install failures MUST leave tracked files byte-unchanged (spec 023 FR-006).

### Key Entities

- **Fragment**: a molecule's rule document; its scoped id, optional declared modality and body are inputs.
- **Passage**: a line range of one fragment body, the unit findings and decisions refer to.
- **Finding**: contradiction or duplicate between passages of different fragments.
- **Decision**: the operator's answer to a finding, with the fingerprints of the passages' text; persisted.
- **Composed constitution**: header with format version and fingerprints, then the fragments in scoped-id order, with excluded passages as comments.
- **Fragment boundary** and **exclusion comment**: the markers `trace`, `status` and the completeness check read.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the haex-vault fragment set (13 fragments, about 930 lines), 100% of the lines of every fragment appear in the composed constitution, in the open or inside an exclusion comment; today's compositions keep 10 to 12 of the 32 rules of the largest fragment.
- **SC-002**: Three consecutive installs on unchanged fragments and decisions produce byte-identical composed files, and runs after the first make 0 language-model calls.
- **SC-003**: After changing one fragment, the diff of the composed constitution is limited to that fragment's block, derived fingerprint metadata in the header, and the exclusion comments of decisions that concern it.
- **SC-004**: A seeded contradictory pair and a seeded duplicate pair are reported as questions in 100% of 5 independent, uncached checks, each shows both passages, and in 100% of cases the passage not kept is commented out with its text unchanged except for the `-->` escaping required to keep the comment well-formed.
- **SC-005**: With the check made unavailable, install fails in under 60 seconds with a message naming the cause and changes 0 tracked files.
- **SC-006**: Deleting the composed constitution and running install reproduces it byte-identical without a language-model call.
- **SC-007**: A repo with a version 1 file reaches version 2 with one `spaex install` (plus the questions of its findings), and a second install changes nothing.
- **SC-008**: `trace` and `status` produce correct output on a version 2 file for every fragment of the haex-vault set, including excluded passages.

## Assumptions

- The fragment format of spec 023 does not change; only how fragments are put into the composed constitution changes.
- Fragment bodies are not rewritten, not even to demote their headings; boundaries and exclusion markers are comment lines that cannot occur inside bodies.
- Because fragments are no longer sorted by modality, the composed file has no modality sections. The agent reads the modal words (MUST, SHOULD, MAY) inside each fragment, as the molecule author wrote them.
- An excluded passage is kept as a comment, not deleted, so the operator can see what was excluded and why; the comment states that it is not an instruction.
- The check finds findings between passages of different fragments only; it is a language model and can miss a finding, so a new fragment set is checked again in full and previous decisions are kept.
- Findings are asked one at a time with both passages shown; how the questions are shown (prompt layout, batching) is a planning decision.
- A longer constitution is acceptable: about five times longer for haex-vault (operator decision, 2026-11-22).
- The `.spaex/constitution.d/` copies of the fragments stay as they are.
- Releasing this as a new major version of spaex (format change for every consumer) is handled by the existing release process, with a breaking-change commit.
