"""Deterministic fragment→batch partitioning (Spec 026 T004).

Pure functions, no I/O: partitions the canonically-sorted fragment set into
fixed-size batches so no single Composer call's input grows unbounded with
the number of adopted molecules/fragments (research.md §2). A molecule's
fragments are never split across two batches. A fragment set that fits in
one batch degenerates to today's single-call path (see
`spaex.behavior.composer.reduce`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from spaex.behavior.composer.clarifications import Clarification
from spaex.behavior.composer.failure import ComposerFailureCategory, raise_for
from spaex.behavior.composer.invoke import ComposerInput
from spaex.behavior.fragment import BehaviorFragment

#: Fragment-count guard, checked alongside the byte-size ceiling — whichever
#: is reached first closes a batch (research.md §2). Chosen so today's real
#: fragment set (9 molecules, ~60KB) yields a handful of batches, matching
#: quickstart.md's illustrated 3-batch walkthrough.
DEFAULT_MAX_BATCH_FRAGMENTS = 12

#: Serialized-size ceiling in bytes, measured as the same
#: `ComposerInput.to_json()` payload actually sent to a Composer call.
DEFAULT_MAX_BATCH_BYTES = 20_000


@dataclass(frozen=True)
class BatchingLimits:
    """Batch-sizing ceilings (research.md §2). Overridable for tests."""

    max_fragments: int = DEFAULT_MAX_BATCH_FRAGMENTS
    max_bytes: int = DEFAULT_MAX_BATCH_BYTES


@dataclass(frozen=True)
class Batch:
    """An ordered, deterministic grouping of fragments assigned to one
    Composer call (data-model.md `Batch`)."""

    batch_id: str
    fragments: tuple[BehaviorFragment, ...]
    clarifications: tuple[Clarification, ...] = ()


@dataclass(frozen=True)
class PartitionResult:
    """Output of `partition()`: every batch, plus whichever currently-valid
    clarifications cite fragments spanning more than one batch (data-model.md
    `MergeInput.cross_batch_clarifications`)."""

    batches: tuple[Batch, ...]
    cross_batch_clarifications: tuple[Clarification, ...] = ()


def partition(
    fragments: Sequence[BehaviorFragment],
    clarifications: Sequence[Clarification] = (),
    *,
    limits: BatchingLimits | None = None,
) -> PartitionResult:
    """Partition `fragments` into deterministic batches.

    Fragments are sorted by `scoped_id` (same canonical order the Composer
    input already uses), grouped by molecule (contiguous after that sort,
    since no molecule id is a prefix-ambiguous substring of another once the
    `/` separator is included), then greedily packed into batches bounded by
    `limits.max_fragments` and `limits.max_bytes`, never splitting one
    molecule's fragment group across two batches.

    Raises the existing typed `behavior-composer-invalid-output` diagnostic
    (`reason=input-too-large`) before any batch is produced if a single
    molecule's fragment group alone exceeds `limits.max_bytes` — the
    no-splitting rule makes a valid batch impossible for that molecule
    (FR-012).
    """
    limits = limits or BatchingLimits()
    sorted_fragments = tuple(sorted(fragments, key=lambda f: f.scoped_id))
    groups = _group_by_molecule(sorted_fragments)

    batches: list[Batch] = []
    current: list[BehaviorFragment] = []

    def flush() -> None:
        if current:
            batches.append(
                Batch(batch_id=f"batch-{len(batches) + 1}", fragments=tuple(current))
            )

    for molecule_id, group in groups:
        group_size = _serialized_size(group)
        if group_size > limits.max_bytes:
            raise_for(
                ComposerFailureCategory.INVALID_OUTPUT,
                (
                    f"molecule {molecule_id!r} fragment group serialized size "
                    f"{group_size} bytes exceeds the {limits.max_bytes}-byte "
                    "batch ceiling and cannot be split across batches"
                ),
                context={
                    "reason": "input-too-large",
                    "molecule_id": molecule_id,
                    "size": str(group_size),
                    "ceiling": str(limits.max_bytes),
                },
            )
            raise AssertionError("unreachable")

        prospective_count = len(current) + len(group)
        prospective_size = _serialized_size(tuple(current) + group)
        if current and (
            prospective_count > limits.max_fragments
            or prospective_size > limits.max_bytes
        ):
            flush()
            current = []
        current.extend(group)
    flush()

    assigned_batches, cross_batch = _assign_clarifications(
        tuple(batches), clarifications
    )
    return PartitionResult(batches=assigned_batches, cross_batch_clarifications=cross_batch)


def _group_by_molecule(
    fragments: Sequence[BehaviorFragment],
) -> list[tuple[str, tuple[BehaviorFragment, ...]]]:
    groups: list[tuple[str, tuple[BehaviorFragment, ...]]] = []
    current_id: str | None = None
    current: list[BehaviorFragment] = []
    for fragment in fragments:
        if fragment.molecule_id != current_id:
            if current:
                assert current_id is not None
                groups.append((current_id, tuple(current)))
            current_id = fragment.molecule_id
            current = []
        current.append(fragment)
    if current:
        assert current_id is not None
        groups.append((current_id, tuple(current)))
    return groups


def _serialized_size(fragments: Sequence[BehaviorFragment]) -> int:
    """Real payload byte-size a batch of `fragments` would occupy in a
    Composer call, reusing the exact serialization the call itself sends."""
    return len(ComposerInput(fragments=tuple(fragments)).to_json().encode("utf-8"))


def _assign_clarifications(
    batches: tuple[Batch, ...], clarifications: Sequence[Clarification]
) -> tuple[tuple[Batch, ...], tuple[Clarification, ...]]:
    batch_of: dict[str, str] = {
        fragment.scoped_id: batch.batch_id
        for batch in batches
        for fragment in batch.fragments
    }
    per_batch: dict[str, list[Clarification]] = {batch.batch_id: [] for batch in batches}
    cross_batch: list[Clarification] = []
    for clarification in clarifications:
        scoped_ids = {cited.scoped_id for cited in clarification.cited_fragments}
        batch_ids = {batch_of.get(scoped_id) for scoped_id in scoped_ids}
        only_batch_id = next(iter(batch_ids)) if len(batch_ids) == 1 else None
        if only_batch_id is not None:
            per_batch[only_batch_id].append(clarification)
        else:
            cross_batch.append(clarification)

    new_batches = tuple(
        replace(batch, clarifications=tuple(per_batch[batch.batch_id]))
        for batch in batches
    )
    return new_batches, tuple(cross_batch)


__all__ = [
    "DEFAULT_MAX_BATCH_BYTES",
    "DEFAULT_MAX_BATCH_FRAGMENTS",
    "Batch",
    "BatchingLimits",
    "PartitionResult",
    "partition",
]
