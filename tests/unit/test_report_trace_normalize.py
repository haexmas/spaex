"""Unit tests for `normalize_query` (Spec 028 T024, FR-011)."""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.report.trace import normalize_query
from spaex.util.errors import UsageError


def test_repo_relative_path(tmp_path: Path) -> None:
    assert normalize_query(tmp_path, "flake.nix") == "flake.nix"


def test_absolute_path_inside_repo(tmp_path: Path) -> None:
    absolute = str(tmp_path / "flake.nix")
    assert normalize_query(tmp_path, absolute) == "flake.nix"


def test_dot_slash_prefixed_path(tmp_path: Path) -> None:
    assert normalize_query(tmp_path, "./flake.nix") == "flake.nix"


def test_trailing_slash(tmp_path: Path) -> None:
    assert normalize_query(tmp_path, "some/dir/") == "some/dir"


def test_all_four_forms_agree(tmp_path: Path) -> None:
    forms = [
        "a/b.md",
        str(tmp_path / "a" / "b.md"),
        "./a/b.md",
        "a/b.md/",
    ]
    results = {normalize_query(tmp_path, form) for form in forms}
    assert results == {"a/b.md"}


def test_path_outside_repository_raises(tmp_path: Path) -> None:
    outside = tmp_path.parent / "elsewhere" / "file.txt"
    with pytest.raises(UsageError):
        normalize_query(tmp_path, str(outside))
