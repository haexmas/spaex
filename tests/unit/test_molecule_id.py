from __future__ import annotations

import pytest

from spaex.model.molecule_id import MoleculeId


@pytest.mark.parametrize(
    "value",
    [
        "com.example.project",
        "com.example.project.constitution",
        "a.b",
        "com.github.example.publisher-name.atom",
    ],
)
def test_accepts_valid(value: str) -> None:
    assert MoleculeId.parse(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "com",
        "com.example-",
        "com.example--",
        "COM.example.project",
        "com..example",
        "com.example.",
        ".com.example",
        "_com.example",
        "com.example_underscore",
    ],
)
def test_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        MoleculeId.parse(value)


def test_rejects_over_length() -> None:
    long = "a" * 254
    with pytest.raises(ValueError):
        MoleculeId.parse(long)
