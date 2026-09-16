"""Map-reduce composition: batch dispatch + bounded merge orchestration (Spec 026).

The only new caller of `invoke.py`'s single-call machinery. For each `Batch`
(`batching.py`) this dispatches one Composer call reusing the existing
sentinel/Shape A/Shape B contract unchanged - every batch concurrently, on
its own thread (ADR 0023) - then combines the batches' composed output with
one bounded merge step (a flat N-ary merge when the merge input fits the
batching byte-size ceiling, otherwise a deterministic pairwise tree
reduction) that re-checks for cross-batch contradictions before the final,
header-bearing document is returned.

`compose()` is only entered for a fragment set spanning more than one batch;
a single-batch build stays on `orchestrate.py`'s direct `invoke_composer`
call, unchanged (contracts/batch-merge-composer-interface.md: "the
existing, unmodified path").
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from spaex.behavior.composer.batching import Batch, BatchingLimits, PartitionResult
from spaex.behavior.composer.clarifications import Clarification, ClarificationsStore
from spaex.behavior.composer.clarify import resolve_step_clarifications
from spaex.behavior.composer.completeness import verify_completeness
from spaex.behavior.composer.failure import ComposerFailureCategory, raise_for
from spaex.behavior.composer.invoke import (
    ClarificationQuestion,
    ComposedShape,
    ComposerInput,
    InvokeOptions,
    InvokeOutcome,
    QuestionsShape,
    RuntimeDescriptor,
    invoke_composer,
    invoke_step,
    resolve_runtime_name,
)
from spaex.behavior.composer.prompt import MERGE_PROMPT, strip_header
from spaex.behavior.fragment import BehaviorFragment


@dataclass(frozen=True)
class BatchComposition:
    """The result of composing one `Batch` (data-model.md `BatchComposition`)."""

    batch_id: str
    body: str
    runtime: RuntimeDescriptor


@dataclass(frozen=True)
class MergeNodeInput:
    """Input to one merge call: two or more already-composed documents
    (data-model.md `MergeInput`, generalized to one tree node)."""

    batch_compositions: tuple[BatchComposition, ...]
    clarifications: tuple[Clarification, ...] = ()
    expected_source_hash: str = ""
    expected_build_input_hash: str = ""

    def to_json(self) -> str:
        """Serialize a merge node input using deterministic JSON ordering."""
        payload = {
            "expected_source_hash": self.expected_source_hash,
            "expected_build_input_hash": self.expected_build_input_hash,
            "batch_compositions": [
                {"batch_id": bc.batch_id, "body": bc.body}
                for bc in self.batch_compositions
            ],
            "clarifications": [_clarification_to_json(c) for c in self.clarifications],
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)


def _clarification_to_json(c: Clarification) -> dict[str, object]:
    """Convert a stored clarification to its merge-payload representation."""
    return {
        "key": c.key,
        "question": c.question,
        "cited_fragments": [entry.as_json() for entry in c.cited_fragments],
        "answer": c.answer,
    }


@dataclass(frozen=True)
class _Node:
    """One tree node flowing through the reduce phase: a composition plus
    which original batches and fragments it represents (so a merge-level
    Shape B can resolve cited fragments, and so clarifications can be
    scoped to exactly the nodes being merged)."""

    composition: BatchComposition
    batch_ids: frozenset[str]
    fragments: tuple[BehaviorFragment, ...]


def compose(
    *,
    partition_result: PartitionResult,
    source_hash: str,
    build_input_hash: str,
    repo_root: Path,
    invoke_options: InvokeOptions | None,
    store: ClarificationsStore,
    prompt_hash: str,
    operator_answer: Callable[[ClarificationQuestion], str],
    abort_on_contradiction: bool,
    limits: BatchingLimits | None = None,
) -> tuple[ClarificationsStore, str, InvokeOutcome]:
    """Multi-batch composition entry point (Spec 026 T011-T013).

    Dispatches one Composer call per `Batch` concurrently (reusing the
    canonical/project compose prompt via `invoke_composer`, exactly as a
    single-call build would): the CLI runtime is resolved once upfront,
    before any batch is dispatched, and forced on every batch (FR-011) so
    "same runtime throughout" holds regardless of dispatch order. Batches
    are independent until this point — none needs another's output — so
    running them on a thread pool turns their wall-clock cost from a sum
    into a max. Each batch's own Shape-B resolution and completeness check
    still run sequentially afterward, in batch order, since those touch the
    shared `store`. Then reduces the batches' composed output with
    `_reduce` into one final document.

    Returns `(store, build_input_hash, invoke_result)` mirroring
    `orchestrate._resolve_clarifications`'s shape so `orchestrate.run()`
    can slot this in exactly where its single-call `invoke_composer` used
    to sit. When `abort_on_contradiction` is `False` (the `spaex add`
    plausibility pre-check) and any node hits Shape B, that Shape B is
    returned immediately as the top-level result without being resolved —
    `orchestrate.run()`'s existing warn/stale handling takes it from there,
    exactly as it does for a single-call Shape B today.
    """
    batches = partition_result.batches
    if len(batches) <= 1:
        raise AssertionError("composer_reduce.compose is only for multi-batch builds")
    limits = limits or BatchingLimits()

    runtime_name = resolve_runtime_name(invoke_options)
    options = _with_forced_runtime(invoke_options, runtime_name)

    def _dispatch(batch: Batch) -> InvokeOutcome:
        """Fire one batch's initial Composer call (no shared-state access)."""
        composer_input = ComposerInput(
            fragments=batch.fragments,
            clarifications=batch.clarifications,
            expected_source_hash=source_hash,
            expected_build_input_hash=build_input_hash,
        )
        return invoke_composer(
            composer_input,
            repo_root=repo_root,
            options=options,
            step=batch.batch_id,
            invocation=1,
            phase="initial",
        )

    with ThreadPoolExecutor(max_workers=len(batches)) as executor:
        # `.map` returns results in argument order regardless of completion
        # order, so `zip(batches, outcomes)` below stays deterministic
        # (SC-003 byte-reproducibility) no matter which batch answers first.
        outcomes = list(executor.map(_dispatch, batches))

    nodes: list[_Node] = []

    for batch, outcome in zip(batches, outcomes, strict=True):
        invocation = 1
        phase = "initial"

        if isinstance(outcome.result, QuestionsShape):
            if not abort_on_contradiction:
                return store, build_input_hash, outcome
            store, build_input_hash, outcome = _resolve_batch_clarifications(
                batch=batch,
                questions=outcome.result.questions,
                store=store,
                source_hash=source_hash,
                prompt_hash=prompt_hash,
                repo_root=repo_root,
                invoke_options=invoke_options,
                operator_answer=operator_answer,
                runtime_name=runtime_name,
            )
            invocation = 2
            phase = "clarification-resolved"

        assert isinstance(outcome.result, ComposedShape)
        body = strip_header(outcome.result.body)
        batch_scoped_ids = {fragment.scoped_id for fragment in batch.fragments}
        batch_clarifications = {
            clarification.key: clarification
            for clarification in batch.clarifications
        }
        batch_clarifications.update(
            {
                clarification.key: clarification
                for clarification in store.entries.values()
                if {
                    cited.scoped_id for cited in clarification.cited_fragments
                }
                <= batch_scoped_ids
            }
        )
        verify_completeness(
            canonical_fragments=batch.fragments,
            composed_body=body,
            clarifications=ClarificationsStore(entries=batch_clarifications),
            repo_root=repo_root,
            invoke_options=options,
            step=batch.batch_id,
            invocation=invocation,
            phase=phase,
        )
        molecule_count = len({fragment.molecule_id for fragment in batch.fragments})
        sys.stdout.write(
            f"composer: {batch.batch_id} composed "
            f"({molecule_count} molecules, {len(batch.fragments)} fragments cited)\n"
        )
        nodes.append(
            _Node(
                composition=BatchComposition(
                    batch_id=batch.batch_id, body=body, runtime=outcome.runtime
                ),
                batch_ids=frozenset({batch.batch_id}),
                fragments=batch.fragments,
            )
        )

    return _reduce(
        nodes,
        cross_batch_clarifications=partition_result.cross_batch_clarifications,
        source_hash=source_hash,
        build_input_hash=build_input_hash,
        repo_root=repo_root,
        invoke_options=invoke_options,
        store=store,
        prompt_hash=prompt_hash,
        operator_answer=operator_answer,
        abort_on_contradiction=abort_on_contradiction,
        runtime_name=runtime_name,
        limits=limits,
    )


def _resolve_batch_clarifications(
    *,
    batch: Batch,
    questions: Sequence[ClarificationQuestion],
    store: ClarificationsStore,
    source_hash: str,
    prompt_hash: str,
    repo_root: Path,
    invoke_options: InvokeOptions | None,
    operator_answer: Callable[[ClarificationQuestion], str],
    runtime_name: str | None,
) -> tuple[ClarificationsStore, str, InvokeOutcome]:
    """Resolve one batch call's questions and perform its bounded retry."""
    batch_scoped_ids = {fragment.scoped_id for fragment in batch.fragments}

    def retry(new_store: ClarificationsStore, new_build_input_hash: str) -> InvokeOutcome:
        """Reinvoke the batch with clarifications relevant to its fragments."""
        retry_input = ComposerInput(
            fragments=batch.fragments,
            clarifications=_relevant_clarifications(new_store.entries.values(), batch_scoped_ids),
            expected_source_hash=source_hash,
            expected_build_input_hash=new_build_input_hash,
        )
        return invoke_composer(
            retry_input,
            repo_root=repo_root,
            options=_with_forced_runtime(invoke_options, runtime_name),
            step=batch.batch_id,
            invocation=2,
            phase="clarification-resolved",
        )

    return resolve_step_clarifications(
        questions=questions,
        fragments_in_scope=batch.fragments,
        store=store,
        prompt_hash=prompt_hash,
        operator_answer=operator_answer,
        retry=retry,
    )


def _reduce(
    nodes: list[_Node],
    *,
    cross_batch_clarifications: tuple[Clarification, ...],
    source_hash: str,
    build_input_hash: str,
    repo_root: Path,
    invoke_options: InvokeOptions | None,
    store: ClarificationsStore,
    prompt_hash: str,
    operator_answer: Callable[[ClarificationQuestion], str],
    abort_on_contradiction: bool,
    runtime_name: str | None,
    limits: BatchingLimits,
) -> tuple[ClarificationsStore, str, InvokeOutcome]:
    """Bounded merge reduction (research.md §3): one flat N-ary merge when
    the current node set fits the batching byte ceiling,
    otherwise a deterministic pairwise tree level (adjacent nodes merged,
    an odd node carried forward unchanged), repeated until one node
    remains."""
    merge_ceiling = limits.max_bytes
    level = 0
    while len(nodes) > 1:
        relevant = _relevant_clarifications(cross_batch_clarifications, _scoped_ids(nodes))
        if _fits(nodes, relevant, source_hash, build_input_hash, merge_ceiling):
            merged, store, build_input_hash, shape_b = _merge_call(
                nodes,
                relevant,
                step="merge",
                is_root=True,
                source_hash=source_hash,
                build_input_hash=build_input_hash,
                repo_root=repo_root,
                invoke_options=invoke_options,
                store=store,
                prompt_hash=prompt_hash,
                operator_answer=operator_answer,
                abort_on_contradiction=abort_on_contradiction,
                runtime_name=runtime_name,
            )
            if shape_b is not None:
                return store, build_input_hash, shape_b
            assert merged is not None
            nodes = [merged]
            break

        # A level with exactly 2 nodes produces exactly 1 output (no carry,
        # since 2 is even) — that single pairwise merge is the root.
        is_root_level = len(nodes) == 2
        new_nodes: list[_Node] = []
        pair_index = 0
        i = 0
        while i < len(nodes):
            if i + 1 < len(nodes):
                pair = [nodes[i], nodes[i + 1]]
                pair_clarifications = _relevant_clarifications(
                    cross_batch_clarifications, _scoped_ids(pair)
                )
                pair_fits = _fits(
                    pair, pair_clarifications, source_hash, build_input_hash, merge_ceiling
                )
                if not pair_fits:
                    raise_for(
                        ComposerFailureCategory.INVALID_OUTPUT,
                        (
                            f"merge pair at tree level {level} (batches "
                            f"{sorted(pair[0].batch_ids | pair[1].batch_ids)}) "
                            f"exceeds the {merge_ceiling}-byte merge ceiling "
                            "and cannot be merged"
                        ),
                        context={
                            "reason": "input-too-large",
                            "step": f"merge-l{level}-{pair_index}",
                            "ceiling": str(merge_ceiling),
                        },
                    )
                    raise AssertionError("unreachable")
                merged, store, build_input_hash, shape_b = _merge_call(
                    pair,
                    pair_clarifications,
                    step=f"merge-l{level}-{pair_index}",
                    is_root=is_root_level,
                    source_hash=source_hash,
                    build_input_hash=build_input_hash,
                    repo_root=repo_root,
                    invoke_options=invoke_options,
                    store=store,
                    prompt_hash=prompt_hash,
                    operator_answer=operator_answer,
                    abort_on_contradiction=abort_on_contradiction,
                    runtime_name=runtime_name,
                )
                if shape_b is not None:
                    return store, build_input_hash, shape_b
                assert merged is not None
                new_nodes.append(merged)
                i += 2
            else:
                new_nodes.append(nodes[i])
                i += 1
            pair_index += 1
        nodes = new_nodes
        level += 1

    root = nodes[0]
    sys.stdout.write(
        f"composer: merge composed ({len(root.batch_ids)} batches -> "
        f"1 constitution, {len(root.fragments)} fragments cited)\n"
    )
    final_outcome = InvokeOutcome(
        result=ComposedShape(body=root.composition.body),
        runtime=root.composition.runtime,
        raw_output=root.composition.body,
    )
    return store, build_input_hash, final_outcome


def _merge_call(
    nodes: Sequence[_Node],
    clarifications: tuple[Clarification, ...],
    *,
    step: str,
    is_root: bool,
    source_hash: str,
    build_input_hash: str,
    repo_root: Path,
    invoke_options: InvokeOptions | None,
    store: ClarificationsStore,
    prompt_hash: str,
    operator_answer: Callable[[ClarificationQuestion], str],
    abort_on_contradiction: bool,
    runtime_name: str | None,
) -> tuple[_Node | None, ClarificationsStore, str, InvokeOutcome | None]:
    """Invoke one merge node. Returns `(merged_node, store, build_input_hash,
    shape_b_outcome)`; `shape_b_outcome` is non-`None` only when
    `abort_on_contradiction` is `False` and this node hit Shape B, in which
    case `merged_node` is `None` and the caller must bubble `shape_b_outcome`
    up as the whole build's result immediately."""
    options = _with_forced_runtime(invoke_options, runtime_name)
    merge_input = MergeNodeInput(
        batch_compositions=tuple(n.composition for n in nodes),
        clarifications=clarifications,
        expected_source_hash=source_hash,
        expected_build_input_hash=build_input_hash,
    )
    outcome = invoke_step(
        prompt_text=MERGE_PROMPT,
        payload_json=merge_input.to_json(),
        repo_root=repo_root,
        options=options,
        step=step,
        invocation=1,
        phase="initial",
    )

    if isinstance(outcome.result, QuestionsShape):
        if not abort_on_contradiction:
            return None, store, build_input_hash, outcome

        merged_scoped_ids = _scoped_ids(nodes)
        fragments_in_scope = tuple(fragment for node in nodes for fragment in node.fragments)

        def retry(new_store: ClarificationsStore, new_build_input_hash: str) -> InvokeOutcome:
            """Reinvoke the merge node with its newly stored clarifications."""
            retry_input = MergeNodeInput(
                batch_compositions=tuple(n.composition for n in nodes),
                clarifications=_relevant_clarifications(
                    new_store.entries.values(), merged_scoped_ids
                ),
                expected_source_hash=source_hash,
                expected_build_input_hash=new_build_input_hash,
            )
            return invoke_step(
                prompt_text=MERGE_PROMPT,
                payload_json=retry_input.to_json(),
                repo_root=repo_root,
                options=options,
                step=step,
                invocation=2,
                phase="clarification-resolved",
            )

        store, build_input_hash, outcome = resolve_step_clarifications(
            questions=outcome.result.questions,
            fragments_in_scope=fragments_in_scope,
            store=store,
            prompt_hash=prompt_hash,
            operator_answer=operator_answer,
            retry=retry,
        )

    assert isinstance(outcome.result, ComposedShape)
    body = outcome.result.body if is_root else strip_header(outcome.result.body)
    merged_batch_ids: frozenset[str] = frozenset()
    for node in nodes:
        merged_batch_ids |= node.batch_ids
    merged_fragments = tuple(fragment for node in nodes for fragment in node.fragments)
    sys.stdout.write(f"composer: {step} composed ({len(nodes)} inputs merged)\n")
    return (
        _Node(
            composition=BatchComposition(batch_id=step, body=body, runtime=outcome.runtime),
            batch_ids=merged_batch_ids,
            fragments=merged_fragments,
        ),
        store,
        build_input_hash,
        None,
    )


def _fits(
    nodes: Sequence[_Node],
    clarifications: tuple[Clarification, ...],
    source_hash: str,
    build_input_hash: str,
    ceiling: int,
) -> bool:
    """Return whether the nodes fit in one serialized merge request."""
    merge_input = MergeNodeInput(
        batch_compositions=tuple(n.composition for n in nodes),
        clarifications=clarifications,
        expected_source_hash=source_hash,
        expected_build_input_hash=build_input_hash,
    )
    size = len(merge_input.to_json().encode("utf-8"))
    return size <= ceiling


def _scoped_ids(nodes: Sequence[_Node]) -> set[str]:
    """Collect every fragment scoped ID represented by the supplied nodes."""
    return {fragment.scoped_id for node in nodes for fragment in node.fragments}


def _relevant_clarifications(
    candidates: Iterable[Clarification], scoped_ids: set[str]
) -> tuple[Clarification, ...]:
    """Every `candidate` whose cited fragments are entirely within `scoped_ids`."""
    return tuple(
        c
        for c in candidates
        if {cited.scoped_id for cited in c.cited_fragments} <= scoped_ids
    )


def _with_forced_runtime(
    options: InvokeOptions | None, runtime_name: str | None
) -> InvokeOptions:
    """Force a call to the given resolved runtime (FR-011), when known."""
    base = options or InvokeOptions()
    if runtime_name is None:
        return base
    return replace(base, forced_cli_runtimes=(runtime_name,))


__all__ = [
    "BatchComposition",
    "MergeNodeInput",
    "compose",
]
