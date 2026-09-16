"""Deterministic fragment→batch partitioning (Spec 026 T004, T005).

Covers: determinism, boundary sizes (exactly at the ceiling, one byte over),
a molecule whose fragments would otherwise straddle a boundary, an oversized
molecule that fails before any LLM call, and the single-batch degenerate
case.
"""

from __future__ import annotations

import pytest

from spaex.behavior.composer.batching import (
    BatchingLimits,
    partition,
)
from spaex.behavior.composer.clarifications import CitedFragment, Clarification
from spaex.behavior.composer.failure import ComposerInvalidOutputError
from spaex.behavior.composer.invoke import ComposerInput
from spaex.behavior.fragment import BehaviorFragment


def _fragment(molecule: str, fid: str, body: str = "**MUST** run tests.\n") -> BehaviorFragment:
    """Build a behavior fragment for batching scenarios."""
    raw = (
        f"---\nid: {fid}\nkind: constitution_fragment\n"
        f"atom_source: pkg.a\nmodality: MUST\n---\n{body}"
    ).encode()
    return BehaviorFragment.from_bytes(raw, molecule_id=molecule, path=f"{molecule}/{fid}.md")


def _clarification(*cited: CitedFragment, key: str = "k") -> Clarification:
    """Build a resolved clarification citing the supplied fragments."""
    return Clarification(
        key=key,
        question="q?",
        cited_fragments=tuple(cited),
        answer="a",
        asked_at="2026-01-01T00:00:00Z",
        answered_at="2026-01-01T00:00:00Z",
    )


def test_single_batch_degenerate_case() -> None:
    """Keep a fragment set within the limits in one batch."""
    fragments = [_fragment("alpha", "a"), _fragment("beta", "b")]

    result = partition(fragments)

    assert len(result.batches) == 1
    assert result.batches[0].batch_id == "batch-1"
    assert set(result.batches[0].fragments) == set(fragments)
    assert result.cross_batch_clarifications == ()


def test_partitioning_is_deterministic_across_repeated_calls() -> None:
    """Produce identical ordered batches across repeated calls."""
    fragments = [_fragment(f"mol-{i}", "rule") for i in reversed(range(6))]
    limits = BatchingLimits(max_fragments=2, max_bytes=100_000)

    first = partition(fragments, limits=limits)
    second = partition(fragments, limits=limits)

    assert [b.batch_id for b in first.batches] == [b.batch_id for b in second.batches]
    assert [tuple(f.scoped_id for f in b.fragments) for b in first.batches] == [
        tuple(f.scoped_id for f in b.fragments) for b in second.batches
    ]


def test_fragment_count_ceiling_splits_into_multiple_batches() -> None:
    """Split fragments when the configured count ceiling is reached."""
    fragments = [_fragment(f"mol-{i}", "rule") for i in range(6)]
    limits = BatchingLimits(max_fragments=2, max_bytes=100_000)

    result = partition(fragments, limits=limits)

    assert len(result.batches) == 3
    for batch in result.batches:
        assert len(batch.fragments) <= 2


def test_molecule_fragments_never_split_across_a_batch_boundary() -> None:
    """mol-b has 2 fragments; with a fragment ceiling of 2, adding it whole to
    a batch that already holds mol-a's 1 fragment would exceed the ceiling —
    the whole group must move to the next batch instead of splitting."""
    fragments = [
        _fragment("mol-a", "only"),
        _fragment("mol-b", "one"),
        _fragment("mol-b", "two"),
    ]
    limits = BatchingLimits(max_fragments=2, max_bytes=100_000)

    result = partition(fragments, limits=limits)

    assert len(result.batches) == 2
    assert {f.scoped_id for f in result.batches[0].fragments} == {"mol-a/only"}
    assert {f.scoped_id for f in result.batches[1].fragments} == {
        "mol-b/one",
        "mol-b/two",
    }


def test_byte_ceiling_exactly_at_boundary_fits_in_one_batch() -> None:
    """Allow a serialized batch exactly at the byte ceiling."""
    fragments = [_fragment("mol-a", "one"), _fragment("mol-b", "two")]
    exact = len(ComposerInput(fragments=tuple(fragments)).to_json().encode("utf-8"))
    limits = BatchingLimits(max_fragments=100, max_bytes=exact)

    result = partition(fragments, limits=limits)

    assert len(result.batches) == 1


def test_byte_ceiling_one_byte_over_splits_into_two_batches() -> None:
    """Split a serialized batch that exceeds the byte ceiling by one."""
    fragments = [_fragment("mol-a", "one"), _fragment("mol-b", "two")]
    exact = len(ComposerInput(fragments=tuple(fragments)).to_json().encode("utf-8"))
    limits = BatchingLimits(max_fragments=100, max_bytes=exact - 1)

    result = partition(fragments, limits=limits)

    assert len(result.batches) == 2


def test_oversized_molecule_raises_input_too_large_without_a_batch() -> None:
    """Reject an indivisible molecule that exceeds the byte ceiling."""
    huge_body = "**MUST** " + ("x" * 5_000) + ".\n"
    fragments = [_fragment("mol-huge", "rule", body=huge_body)]
    limits = BatchingLimits(max_fragments=100, max_bytes=1_000)

    with pytest.raises(ComposerInvalidOutputError) as excinfo:
        partition(fragments, limits=limits)

    assert excinfo.value.context.get("reason") == "input-too-large"
    assert excinfo.value.context.get("molecule_id") == "mol-huge"
    assert "ceiling" in excinfo.value.context


def test_molecule_exceeding_fragment_ceiling_but_not_byte_ceiling_gets_its_own_batch() -> None:
    """Fragment count alone never fails a molecule (regression: a real
    18-fragment molecule with a small total byte size was wrongly rejected
    by an earlier version of this check). `max_fragments` only bounds
    whether several molecules get COMBINED into one batch below; a single
    molecule with many small fragments still gets one batch of its own,
    larger than max_fragments, as long as it fits the byte ceiling."""
    fragments = [_fragment("mol-many", f"rule-{i}") for i in range(3)]
    limits = BatchingLimits(max_fragments=2, max_bytes=100_000)

    result = partition(fragments, limits=limits)

    assert len(result.batches) == 1
    assert len(result.batches[0].fragments) == 3


def test_clarification_scoped_to_one_batch_is_assigned_to_it() -> None:
    """Attach a clarification whose citations lie within one batch."""
    fragments = [_fragment(f"mol-{i}", "rule") for i in range(4)]
    limits = BatchingLimits(max_fragments=2, max_bytes=100_000)
    same_batch_clarification = _clarification(
        CitedFragment("mol-0", "rule", "h0"), CitedFragment("mol-1", "rule", "h1")
    )

    result = partition(fragments, [same_batch_clarification], limits=limits)

    scoped = {f.scoped_id for f in result.batches[0].fragments}
    assert scoped == {"mol-0/rule", "mol-1/rule"}
    assert result.batches[0].clarifications == (same_batch_clarification,)
    assert result.cross_batch_clarifications == ()


def test_clarification_spanning_batches_is_cross_batch() -> None:
    """Classify a clarification citing multiple batches as cross-batch."""
    fragments = [_fragment(f"mol-{i}", "rule") for i in range(4)]
    limits = BatchingLimits(max_fragments=2, max_bytes=100_000)
    spanning_clarification = _clarification(
        CitedFragment("mol-0", "rule", "h0"), CitedFragment("mol-2", "rule", "h2")
    )

    result = partition(fragments, [spanning_clarification], limits=limits)

    assert result.cross_batch_clarifications == (spanning_clarification,)
    for batch in result.batches:
        assert batch.clarifications == ()


def test_batch_byte_ceiling_includes_batch_local_clarifications() -> None:
    fragments = [_fragment("mol-a", "rule"), _fragment("mol-b", "rule")]
    clarification = _clarification(CitedFragment("mol-a", "rule", "hash"))
    with_clarification = len(
        ComposerInput(
            fragments=tuple(fragments), clarifications=(clarification,)
        )
        .to_json()
        .encode("utf-8")
    )
    limits = BatchingLimits(max_fragments=100, max_bytes=with_clarification - 1)

    result = partition(fragments, [clarification], limits=limits)

    assert len(result.batches) == 2
    assert result.batches[0].fragments == (fragments[0],)
    assert result.batches[0].clarifications == (clarification,)
    assert result.batches[1].fragments == (fragments[1],)
