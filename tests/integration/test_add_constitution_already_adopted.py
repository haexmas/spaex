"""T065 — the single-constitution rule at the `haex add` boundary (FR-020)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spaex.util.errors import ConstitutionAlreadyAdoptedError

_FIRST_ID = "com.example.publisher.first-constitution"
_SECOND_ID = "com.example.publisher.second-constitution"


def test_add_refuses_second_constitution_pre_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, haex_add_helpers
) -> None:
    canonical_a, head_a, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _FIRST_ID: {
                "path": "first",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
        },
        name="first",
    )
    canonical_b, head_b, _state_b = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _SECOND_ID: {
                "path": "second",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
        },
        name="second",
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical_a,
        molecule_ids=_FIRST_ID,
        revision=head_a,
    )
    baseline = (consumer / ".spaex.json").read_bytes()

    with pytest.raises(ConstitutionAlreadyAdoptedError) as exc_info:
        haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical_b,
            molecule_ids=_SECOND_ID,
            revision=head_b,
        )
    assert _FIRST_ID in exc_info.value.context["adopted_by"]
    assert (consumer / ".spaex.json").read_bytes() == baseline
    assert not (consumer / ".spaex" / "pending").exists()

    # Recovery: simulate `haex remove` (US4) by dropping the compound then retrying.
    manifest_data = json.loads(baseline)
    manifest_data["compounds"] = []
    (consumer / ".spaex.json").write_bytes(
        json.dumps(manifest_data).encode("utf-8")
    )
    rc = haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical_b,
        molecule_ids=_SECOND_ID,
        revision=head_b,
    )
    assert rc == 0
