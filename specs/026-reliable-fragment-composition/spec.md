# Feature Specification: Reliable Fragment Composition

**Feature Branch**: `026-reliable-fragment-composition`
**Created**: 2026-09-16
**Status**: Draft
**Input**: User description: "spaex needs a reliable way to compose multiple behavior fragments from many molecules into one consistent, complete constitution. The current Composer design (Spec 023) sends the entire fragment set as a single non-interactive LLM call (claude --print) that must reason about overlaps/contradictions across every fragment and produce one long, strictly-formatted, fully-cited document in one shot. Against this project's own real fragment set (9 adopted molecules, ~60KB composer input), 4 of 5 real spaex install attempts timed out even at a 600s budget, and the one attempt that did return a response silently dropped 9 of the fragments (caught by the existing FR-012b completeness check, which correctly aborted rather than publishing incomplete output). Host load was moderate (load avg ~2-3) during the failing attempts, ruling out simple host contention as the primary cause. This points at the single-shot, whole-fragment-set composition approach itself no longer scaling once the number of adopted molecules/fragments grows past what fits reliably in one LLM turn. We need a composition strategy that stays reliable as the fragment set grows, while preserving the existing guarantees this project already relies on: byte-reproducible output, the sentinel/Shape A/Shape B response contract, the no-silent-degradation and completeness guarantees, and the non-destructive/rollback behavior on any failure."

## Clarifications

### Session 2026-09-16

- Q: Must the entire composition (across however many internal steps) consistently use one single CLI runtime, or may individual steps independently pick whichever runtime is available? → A: One runtime, selected once per composition run, used for every step.
- Q: When a multi-step composition fails partway through, should the raw output of every already-completed step be preserved (not just the step that ultimately failed), so the whole run is inspectable? → A: Yes, log every completed step, extending the existing composer-log principle.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Install succeeds reliably at real-world molecule counts (Priority: P1)

As an operator who has adopted a realistic number of molecules into a project (today: 9, growing over time as more atoms are adopted), running `spaex install` composes a complete, correct constitution without silently dropping content and without routinely hanging or timing out.

**Why this priority**: This is the core reliability guarantee spaex's own behavior harness depends on. Without it, the tool becomes unusable exactly as adoption grows — which is already happening on this project's own repo (4 of 5 real attempts failed at 9 molecules).

**Independent Test**: Adopt a fragment set at least as large as the project's current real one (9 molecules, ~60KB composer input, the confirmed failure case). Run `spaex install` repeatedly. Every run either completes with every fragment accounted for, or fails with a diagnostic that does not require the operator to guess whether the run is still working — never a silent drop and never a bare unexplained timeout.

**Acceptance Scenarios**:

1. **Given** a project with 9 adopted molecules and no persisted clarifications, **When** the operator runs `spaex install`, **Then** the install completes and the composed constitution cites every one of the 9 molecules' fragments (or accounts for their absence via a clarification the operator already answered).
2. **Given** the same 9-molecule project, **When** the operator runs `spaex install` five times in a row under normal host load, **Then** all five runs succeed (compare against today's ~20% observed success rate at this scale).

---

### User Story 2 - Composed output stays byte-reproducible (Priority: P2)

As someone relying on spaex's existing reproducibility guarantee (an unchanged fragment set always re-composes to byte-identical output, and unchanged input skips composition entirely), I need that guarantee to keep holding even though composition may now internally involve more than one step.

**Why this priority**: Determinism is load-bearing for existing tests, the reproducibility skip that avoids re-invoking the Composer on unchanged input, and operator trust that re-running install is always safe.

**Independent Test**: Run `spaex install` twice against the same unchanged fragment set (no new clarifications in between). Diff `.spaex/constitution.md` byte-for-byte between the two runs and confirm they are identical, and confirm the second run does not re-invoke composition at all when nothing changed.

**Acceptance Scenarios**:

1. **Given** a fragment set that already composed successfully, **When** the operator re-runs `spaex install` with nothing changed, **Then** the composed constitution is byte-identical to the previous run and no new composition work runs at all.
2. **Given** the same fragment set, **When** composition *is* re-invoked (for example after a clarification is added), **Then** the newly composed output is byte-identical to any other successful composition run against that exact same fragment set and clarification state.

---

### User Story 3 - Genuine cross-fragment contradictions are still caught (Priority: P3)

As an operator, if two fragments from different molecules genuinely conflict (for example, one states a MUST and another states a contradicting MUST_NOT on the same topic), I still get asked to resolve it before anything publishes — regardless of how the composition work is internally organized.

**Why this priority**: Cross-fragment contradiction detection is an existing safety guarantee. A composition strategy that processes fragments in smaller groups must not lose the ability to reason across group boundaries, or it would silently regress this guarantee while fixing reliability.

**Independent Test**: Adopt two molecules whose fragments contradict each other, positioned so that a smaller-batch or incremental strategy would naturally place them in different groups. Run `spaex install` and confirm the operator is still asked to resolve the contradiction rather than the system silently picking one side or publishing both.

**Acceptance Scenarios**:

1. **Given** two molecules whose fragments contradict on the same topic, **When** the operator runs `spaex install`, **Then** the system surfaces the contradiction as a clarification question naming both fragments, exactly as it does today for a single-call composition.
2. **Given** the operator has already answered that clarification, **When** they re-run `spaex install` with the same fragment set, **Then** the answer is honored and no repeat question is asked.

### Edge Cases

- A fragment set small enough to compose in one call today (the common case for most consumers) MUST keep working exactly as it does now, with no added latency, added steps, or behavior change.
- If part of a multi-step composition succeeds and a later part fails (times out, returns invalid output, hits a quota/runtime error), the project's existing constitution MUST remain byte-unchanged — the existing non-destructive/rollback guarantee extends to a composition process with more than one internal step.
- A single fragment (or a no-split molecule group that cannot reasonably be subdivided further) that is itself too large to compose reliably MUST fail before an LLM call with the bounded, typed `behavior-composer-invalid-output` diagnostic described in FR-012 rather than being silently truncated or dropped.
- The failure diagnostic for a multi-step composition MUST indicate which part of the process failed, not just that composition as a whole failed — building on the existing progress/timeout/log visibility already in place.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST successfully compose a complete, correct constitution for a fragment set of any size a project adopts when every individual fragment and every no-split molecule group fits within the supported input limits — there is no fixed ceiling on molecule or fragment count at which the system is allowed to stop scaling. The project's current real-world scale (9 molecules, ~60KB combined fragment content) is the confirmed minimum bar, not the target ceiling.
- **FR-002**: The system MUST NOT silently omit any input fragment from the composed output at any scale; every fragment MUST be cited in the final document or covered by a persisted operator clarification, exactly as today's completeness check already requires.
- **FR-003**: The system MUST continue to produce byte-reproducible composed output for an unchanged fragment set and clarification state, and MUST continue to skip re-invoking composition entirely when nothing has changed.
- **FR-004**: The system MUST NOT publish a partial or internally-inconsistent constitution if any part of the composition process fails partway through; on any failure, the previously published constitution MUST remain byte-unchanged.
- **FR-005**: The system MUST still detect a genuine cross-fragment contradiction or overlap between any two fragments in the adopted set and surface it to the operator as a clarification question, regardless of how composition work is internally organized.
- **FR-006**: The system MUST continue to expose accurate per-clause provenance (which molecule and fragment produced each clause) in the composed output.
- **FR-007**: The system's success rate at composing a given fragment set MUST NOT degrade as the number of adopted molecules grows, provided every individual fragment and no-split molecule group fits within the supported input limits — reliability at 9 molecules must not be worse than reliability at 3, and the same must hold as further molecules are adopted beyond today's scale, with no fragment-count ceiling at which the system is allowed to give up.
- **FR-008**: When composition fails despite the new approach, the system MUST provide a diagnostic that identifies which specific part of the process failed, building on the existing invocation-progress, elapsed-time, and failure-log visibility. This MUST include the raw output of every internal invocation that completed before the failure, not only the invocation that failed, extending the existing composer-log principle to a multi-step run so the operator can inspect the whole attempt, not just its final error.
- **FR-009**: The system MUST NOT silently fall back to including raw, unreviewed fragment content in place of composed output — every path that does not go through a successful composition and completeness check remains a typed failure, never a degraded success.
- **FR-010**: The system MAY take longer to compose a larger fragment set, and an occasional manual re-run after a genuine failure remains an acceptable fallback — this feature is not required to add automatic retry or self-healing on top of the reliability improvement itself.
- **FR-011**: The system MUST select one CLI runtime for a given composition run and use it consistently across every internal step of that run — never mixing runtimes within one run — so that the byte-reproducibility guarantee (FR-003) is not put at risk by different steps potentially answering through different models.
- **FR-012**: If an individual fragment or no-split molecule group exceeds the supported serialized-size limit, the system MUST fail before invoking the LLM with the existing typed `behavior-composer-invalid-output` diagnostic, including a bounded reason (`input-too-large`), the offending molecule or fragment identifier, the measured size, and the configured ceiling. It MUST produce no batch and MUST leave the previously published constitution unchanged.

### Key Entities

- **Fragment**: A single behavior directive contributed by one molecule; already exists today, unchanged by this feature.
- **Composed Constitution**: The single output document (`.spaex/constitution.md`) produced from every adopted fragment; must remain one coherent document with stable, provenance-annotated formatting regardless of how many internal steps produced it.
- **Clarification**: An operator-answered question resolving an overlap or contradiction between fragments; already exists today, must keep working across whatever internal grouping composition now uses.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `spaex install` against the project's current real fragment set (9 molecules) succeeds on at least 95% of attempts under normal host conditions, compared to the ~20% success rate observed before this feature (1 of 5 real attempts).
- **SC-002**: A successful composition completes within a generous but bounded time budget (target: well under 20 minutes) even at the project's current scale and beyond; reliability is prioritized over raw speed, but a run is never left to hang with no diagnostic until an unbounded wait finally elapses.
- **SC-003**: Re-running `spaex install` against an unchanged fragment set produces byte-identical composed output 100% of the time, with no observable behavior change from today's reproducibility guarantee.
- **SC-004**: A fragment set small enough to have composed successfully in one call before this feature continues to compose in comparable or better time after this feature, with no regression for the common case.
- **SC-005**: On the rare remaining failure, a manual re-run of `spaex install` is a sufficient and acceptable recovery path; the feature is not required to retry or self-heal automatically.

## Assumptions

- The specific composition strategy (for example: grouping fragments into smaller batches with a merge step, composing incrementally per molecule, or another approach) is a design decision for the implementation plan, not fixed by this specification.
- Target scale is unbounded by design: this feature must not introduce a fixed molecule/fragment-count ceiling. The project's current real-world scale (9 molecules, ~60KB combined fragment content) is the confirmed minimum bar it must clear today, not the ceiling it is designed toward. *(Resolved during `/speckit.specify`.)*
- A generous but bounded latency (target: well under 20 minutes) is acceptable for a successful composition; reliability is explicitly prioritized over raw speed. *(Resolved during `/speckit.specify`.)*
- An occasional manual re-run of `spaex install` remains an acceptable recovery path on genuine failure; this feature is not required to add automatic retry or self-healing on top of the reliability improvement itself. *(Resolved during `/speckit.specify`.)*
- Existing response-contract guarantees from Spec 023 (the sentinel-wrapped Shape A/Shape B envelope, the five typed failure categories, the non-destructive rollback on any failure, and per-clause provenance annotations) remain in force and are not renegotiated by this feature; this feature is about how reliably the system reaches a valid Shape A/Shape B response as the fragment set grows, not about changing what a valid response looks like.
- This feature is scoped to the Composer's reliability at scale. It does not prescribe which CLI runtime is selected or how the effective prompt is authored; it does require the selected runtime to remain consistent for the whole composition attempt under FR-011.
