from __future__ import annotations

import pytest

from spaex.model.version_constraint import VersionConstraint


def test_exact_form() -> None:
    v = VersionConstraint.parse("2.0.0")
    assert v.operator == "=="
    assert v.version == (2, 0, 0)
    assert v.satisfied_by((2, 0, 0))
    assert not v.satisfied_by((2, 0, 1))


def test_lower_bound() -> None:
    v = VersionConstraint.parse(">=1.2.3")
    assert v.operator == ">="
    assert v.version == (1, 2, 3)
    assert v.satisfied_by((1, 2, 3))
    assert v.satisfied_by((1, 2, 4))
    assert v.satisfied_by((2, 0, 0))
    assert not v.satisfied_by((1, 2, 2))


@pytest.mark.parametrize(
    "value",
    ["", "1", "1.0", "1.0.0.0", "01.0.0", ">= 1.0.0", ">=1.0.0-alpha", "v1.0.0"],
)
def test_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        VersionConstraint.parse(value)
