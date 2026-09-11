"""Clarification key derivation tests (Spec 023 T017).

Covers:
- sort order invariance (order of `cited_fragments` in the input does not
  affect the derived key)
- LF+trim body normalization invariance (research.md §7)
- mismatch detection (invalidate() drops entries whose recomputed key
  differs, or whose fragments no longer exist)
- atomic tmp+rename round-trip through load/save
- schema_version rejection

Corresponds to SC-008 unit portion (persistence key round-trip); the
scripted end-to-end flow lives in T043.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spaex.behavior.composer.clarifications import (
    SCHEMA_VERSION,
    CitedFragment,
    Clarification,
    ClarificationsStore,
    ClarificationsStoreError,
    derive_key,
    invalidate,
    load,
    save,
    utc_timestamp,
)


def _cited(scoped: str, body_hash: str) -> CitedFragment:
    molecule_id, fragment_id = scoped.split("/", 1)
    return CitedFragment(
        molecule_id=molecule_id,
        fragment_id=fragment_id,
        body_sha256=body_hash,
    )


def test_derive_key_is_stable_regardless_of_input_order() -> None:
    a = _cited("com.example.mol-a/rule", "a" * 64)
    b = _cited("com.example.mol-b/rule", "b" * 64)
    assert derive_key([a, b]) == derive_key([b, a])


def test_derive_key_uses_sha256_of_sorted_pipe_delimited_lines() -> None:
    a = _cited("com.example.mol/one", "0" * 64)
    b = _cited("com.example.mol/two", "f" * 64)
    payload = (
        "com.example.mol/one|"
        + ("0" * 64)
        + "\n"
        + "com.example.mol/two|"
        + ("f" * 64)
    )
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert derive_key([a, b]) == expected


def test_key_changes_when_body_hash_changes() -> None:
    original = _cited("com.example.mol/rule", "a" * 64)
    edited = _cited("com.example.mol/rule", "b" * 64)
    assert derive_key([original]) != derive_key([edited])


def test_invalidate_drops_entries_with_stale_hash() -> None:
    key = derive_key([_cited("com.example.mol/rule", "a" * 64)])
    entry = Clarification(
        key=key,
        question="Which one wins?",
        cited_fragments=(_cited("com.example.mol/rule", "a" * 64),),
        answer="the first",
        asked_at=utc_timestamp(),
        answered_at=utc_timestamp(),
    )
    store = ClarificationsStore().with_entry(entry)

    pruned, removed = invalidate(store, {"com.example.mol/rule": "b" * 64})
    assert removed == (key,)
    assert pruned.entries == {}


def test_invalidate_keeps_entries_whose_recomputed_key_matches() -> None:
    hash_a = "a" * 64
    key = derive_key([_cited("com.example.mol/rule", hash_a)])
    entry = Clarification(
        key=key,
        question="Q?",
        cited_fragments=(_cited("com.example.mol/rule", hash_a),),
        answer="A",
        asked_at=utc_timestamp(),
        answered_at=utc_timestamp(),
    )
    store = ClarificationsStore().with_entry(entry)
    pruned, removed = invalidate(store, {"com.example.mol/rule": hash_a})
    assert removed == ()
    assert set(pruned.entries) == {key}


def test_invalidate_drops_entries_whose_cited_fragment_is_missing() -> None:
    key = derive_key([_cited("com.example.mol/gone", "a" * 64)])
    entry = Clarification(
        key=key,
        question="Q?",
        cited_fragments=(_cited("com.example.mol/gone", "a" * 64),),
        answer="A",
        asked_at=utc_timestamp(),
        answered_at=utc_timestamp(),
    )
    store = ClarificationsStore().with_entry(entry)
    pruned, removed = invalidate(store, {})
    assert removed == (key,)


def test_load_returns_empty_store_when_file_absent(tmp_path: Path) -> None:
    store = load(tmp_path / "clarifications.json")
    assert store.entries == {}


def test_save_and_reload_round_trips(tmp_path: Path) -> None:
    cited = (_cited("com.example.mol/rule", "a" * 64),)
    key = derive_key(cited)
    entry = Clarification(
        key=key,
        question="Q?",
        cited_fragments=cited,
        answer="A",
        asked_at="2026-09-11T10:00:00Z",
        answered_at="2026-09-11T10:00:05Z",
    )
    store = ClarificationsStore().with_entry(entry)
    target = tmp_path / "clarifications.json"
    save(target, store)

    reloaded = load(target)
    assert set(reloaded.entries) == {key}
    got = reloaded.entries[key]
    assert got.question == "Q?"
    assert got.answer == "A"
    assert got.cited_fragments == cited


def test_save_writes_via_temp_file_and_final_replace(tmp_path: Path) -> None:
    """The final path exists and no stray .tmp is left behind on success."""
    target = tmp_path / "clarifications.json"
    save(target, ClarificationsStore())
    assert target.exists()
    assert not target.with_suffix(target.suffix + ".tmp").exists()


def test_load_rejects_unknown_schema_version(tmp_path: Path) -> None:
    target = tmp_path / "clarifications.json"
    target.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION + 99, "clarifications": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ClarificationsStoreError):
        load(target)


def test_load_rejects_corrupt_json(tmp_path: Path) -> None:
    target = tmp_path / "clarifications.json"
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(ClarificationsStoreError):
        load(target)


def test_load_rejects_non_object_top_level(tmp_path: Path) -> None:
    target = tmp_path / "clarifications.json"
    target.write_text("[]", encoding="utf-8")
    with pytest.raises(ClarificationsStoreError):
        load(target)


def test_load_rejects_entry_missing_required_field(tmp_path: Path) -> None:
    target = tmp_path / "clarifications.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "clarifications": {
                    "some-key": {
                        # missing "question"
                        "cited_fragments": [],
                        "answer": "A",
                        "asked_at": "x",
                        "answered_at": "y",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ClarificationsStoreError):
        load(target)


def test_load_rejects_entry_with_empty_answer(tmp_path: Path) -> None:
    """Contract: `answer` MUST be non-empty (contract §Validation rules)."""
    target = tmp_path / "clarifications.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "clarifications": {
                    "some-key": {
                        "question": "Q",
                        "cited_fragments": [],
                        "answer": "",
                        "asked_at": "x",
                        "answered_at": "y",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ClarificationsStoreError):
        load(target)


def test_utc_timestamp_returns_z_suffixed_iso_8601() -> None:
    stamp = utc_timestamp()
    assert stamp.endswith("Z")
    assert "T" in stamp
    assert len(stamp) == len("2026-09-11T10:00:00Z")
