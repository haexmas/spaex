from __future__ import annotations

import pytest

from spaex.model.repo_relative_path import RepoRelativePath


@pytest.mark.parametrize(
    "value",
    ["constitution.md", "constitution/constitution.md", "a/b/c.txt"],
)
def test_accepts_valid(value: str) -> None:
    assert RepoRelativePath.validate(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/absolute",
        "a\\b",
        "C:/drive",
        "./relative",
        "../outside",
        "a//b",
        "a/./b",
        "a/../b",
        "a/\x00/b",
    ],
)
def test_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        RepoRelativePath.validate(value)
