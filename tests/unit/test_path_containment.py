"""T012 - canonicalise_within containment tests (Spec 016 FR-014/FR-015)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from spaex.util.path_containment import PathEscapeError, canonicalise_within


def test_direct_descendant_returns_canonical_target(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "install.py"
    inside.write_text("# ok\n")
    result = canonicalise_within(root, inside)
    assert result == inside.resolve(strict=True)


def test_dotdot_that_stays_inside_root_is_allowed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    target = root / "install.py"
    target.write_text("ok")
    candidate = root / "sub" / ".." / "install.py"
    result = canonicalise_within(root, candidate)
    assert result == target.resolve(strict=True)


def test_dotdot_that_escapes_root_raises(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("bad")
    candidate = root / ".." / "outside.py"
    with pytest.raises(PathEscapeError):
        canonicalise_within(root, candidate)


@pytest.mark.skipif(
    sys.platform.startswith("win"), reason="symlink test skipped on Windows"
)
def test_symlink_pointing_outside_root_raises(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "real_outside.py"
    outside.write_text("bad")
    link = root / "install.py"
    os.symlink(outside, link)
    with pytest.raises(PathEscapeError):
        canonicalise_within(root, link)


@pytest.mark.skipif(
    sys.platform.startswith("win"), reason="symlink test skipped on Windows"
)
def test_internal_symlink_chain_that_stays_inside_root_is_allowed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    (root / "real").mkdir(parents=True)
    real_target = root / "real" / "install.py"
    real_target.write_text("ok")
    hop1 = root / "hop1.py"
    hop2 = root / "hop2.py"
    os.symlink(real_target, hop1)
    os.symlink(hop1, hop2)
    result = canonicalise_within(root, hop2)
    assert result == real_target.resolve(strict=True)


@pytest.mark.skipif(
    sys.platform.startswith("win"), reason="symlink test skipped on Windows"
)
def test_broken_symlink_raises(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    link = root / "install.py"
    os.symlink(root / "does-not-exist", link)
    with pytest.raises(PathEscapeError):
        canonicalise_within(root, link)


def test_missing_root_raises(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    candidate = root / "install.py"
    with pytest.raises(PathEscapeError):
        canonicalise_within(root, candidate)


def test_candidate_equals_root_raises(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PathEscapeError):
        canonicalise_within(root, root)
