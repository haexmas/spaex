from __future__ import annotations

from spaex.io import json_deterministic


def test_byte_identity_across_calls() -> None:
    obj = {"b": {"nested": ["y", "x"]}, "a": 1, "emoji": "☃"}
    first = json_deterministic.dumps(obj)
    second = json_deterministic.dumps(obj)
    assert first == second


def test_sort_keys_and_trailing_newline() -> None:
    data = json_deterministic.dumps({"z": 1, "a": 2})
    assert data.endswith(b"\n")
    assert data.index(b'"a"') < data.index(b'"z"')


def test_unicode_not_escaped() -> None:
    data = json_deterministic.dumps({"snowman": "☃"})
    assert "☃".encode() in data
