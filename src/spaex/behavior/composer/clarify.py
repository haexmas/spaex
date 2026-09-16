"""Shared clarification round-trip primitive (Spec 026 T003).

Generalizes the whole-build-only Shape-B round trip (`orchestrate.py`'s
`_resolve_clarifications`, historically the only caller) into a form any
composition step can invoke for its own scope: a batch call or a merge node
(`reduce.py`), not only the legacy single-call build.

Lives in its own module rather than directly in `orchestrate.py` (as
tasks.md's T003 names it) because `reduce.py` needs it too, and
`orchestrate.py` already imports `reduce.py` for the multi-batch entry point
(T013) — putting the shared helper in `orchestrate.py` would make the
reverse import a cycle. `orchestrate.py`'s own `_resolve_clarifications`
now delegates here for the legacy path, unchanged in behavior.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from spaex.behavior.composer.clarifications import (
    CitedFragment,
    Clarification,
    ClarificationsStore,
    derive_key,
    utc_timestamp,
)
from spaex.behavior.composer.failure import ComposerFailureCategory, raise_for
from spaex.behavior.composer.invoke import (
    ClarificationQuestion,
    InvokeOutcome,
    QuestionsShape,
)
from spaex.behavior.composer.prompt import COMPOSER_PROMPT_VERSION
from spaex.behavior.emit import compute_build_input_hash
from spaex.behavior.fragment import BehaviorFragment
from spaex.util import exit_codes
from spaex.util.errors import HaexError


def cited_fragments_for_question(
    question: ClarificationQuestion,
    fragment_by_scoped_id: Mapping[str, BehaviorFragment],
) -> tuple[CitedFragment, ...]:
    """Resolve a Shape-B question's cited fragments to current body hashes."""
    cited: list[CitedFragment] = []
    for entry in question.cited_fragments:
        molecule_id = entry.get("molecule_id", "")
        fragment_id = entry.get("fragment_id", "")
        fragment = fragment_by_scoped_id.get(f"{molecule_id}/{fragment_id}")
        if fragment is None:
            raise_for(
                ComposerFailureCategory.INVALID_OUTPUT,
                "Shape B question cites unknown fragment "
                f"{molecule_id}/{fragment_id}",
            )
            raise AssertionError("unreachable")
        cited.append(
            CitedFragment(
                molecule_id=molecule_id,
                fragment_id=fragment_id,
                body_sha256=fragment.body_hash,
            )
        )
    return tuple(cited)


def resolve_step_clarifications(
    *,
    questions: Sequence[ClarificationQuestion],
    fragments_in_scope: Sequence[BehaviorFragment],
    store: ClarificationsStore,
    prompt_hash: str,
    operator_answer: Callable[[ClarificationQuestion], str],
    retry: Callable[[ClarificationsStore, str], InvokeOutcome],
) -> tuple[ClarificationsStore, str, InvokeOutcome]:
    """Answer each Shape-B question once, persist it, and re-invoke this step
    exactly once with the staged clarifications.

    A blank answer means the operator declined to reconcile and aborts with
    `behavior-clarification-required` (FR-005a), exactly as the legacy
    whole-build round trip does. `retry` performs this step's own
    re-invocation given the updated store and recomputed `build_input_hash`
    — a batch call re-invokes with a batch-scoped `ComposerInput` via the
    canonical prompt, a merge node re-invokes with a `MergeNodeInput` via
    the merge prompt; this function is agnostic to which. Bounded to one
    retry: a second Shape B from `retry` is `invalid-output`.
    """
    fragment_by_scoped_id = {f.scoped_id: f for f in fragments_in_scope}
    for question in questions:
        cited = cited_fragments_for_question(question, fragment_by_scoped_id)
        answer = operator_answer(question).strip()
        if not answer:
            raise HaexError(
                message=(
                    "operator declined to reconcile clarification question: "
                    f"{question.question}"
                ),
                diagnostic_key="behavior-clarification-required",
                exit_code=exit_codes.BEHAVIOR_SEMANTIC_REFUSE,
                hint=(
                    "Provide a reconciling answer (choose one modality, merge, "
                    "or reject both), or drop the molecule whose fragments "
                    "trigger the overlap/contradiction."
                ),
            )
        timestamp = utc_timestamp()
        store = store.with_entry(
            Clarification(
                key=derive_key(cited),
                question=question.question,
                cited_fragments=cited,
                answer=answer,
                asked_at=timestamp,
                answered_at=timestamp,
            )
        )

    build_input_hash = compute_build_input_hash(
        effective_prompt_sha256=prompt_hash,
        composer_prompt_version=COMPOSER_PROMPT_VERSION,
        valid_clarifications=store.entries.values(),
    )
    invoke_result = retry(store, build_input_hash)
    if isinstance(invoke_result.result, QuestionsShape):
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            "Composer returned a second Shape B response for the same step; "
            "the clarification round is bounded to one re-invocation "
            "(contracts/composer-interface.md §Shape B)",
        )
        raise AssertionError("unreachable")

    return store, build_input_hash, invoke_result


__all__ = ["cited_fragments_for_question", "resolve_step_clarifications"]
