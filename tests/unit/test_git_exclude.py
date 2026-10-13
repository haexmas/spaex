"""Per-worktree spaex block in git's info/exclude (Spec 029 research R7)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from spaex.install import git_exclude
from spaex.util.errors import LocalExcludeMalformedError


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, git_binary: str) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    return root


def _exclude(repo: Path) -> Path:
    path = git_exclude.exclude_file(repo)
    assert path is not None
    return path


def test_reconcile_creates_block_and_git_honors_it(repo: Path) -> None:
    _exclude(repo).unlink(missing_ok=True)
    (repo / "flake.local.nix").write_text("x")

    git_exclude.reconcile(repo, ["flake.local.nix", "flake.local.nix"])

    assert _exclude(repo).read_text().splitlines() == [
        '# spaex-local:start worktree=".git"',
        "/flake.local.nix",
        '# spaex-local:end worktree=".git"',
    ]
    assert _git(repo, "status", "--porcelain") == ""


def test_reconcile_keeps_foreign_lines_and_removes_empty_block(repo: Path) -> None:
    _exclude(repo).write_text("# mine\n*.swp\n")

    git_exclude.reconcile(repo, ["a.txt"])
    git_exclude.reconcile(repo, ["b.txt"])
    assert git_exclude.block_paths(repo) == ("/b.txt",)

    git_exclude.reconcile(repo, [])
    assert _exclude(repo).read_text() == "# mine\n*.swp\n"


def test_blocks_of_other_worktrees_are_untouched(repo: Path) -> None:
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    other = repo.parent / "other"
    _git(repo, "worktree", "add", "-q", str(other))

    git_exclude.reconcile(repo, ["main-only"])
    git_exclude.reconcile(other, ["other-only"])
    git_exclude.reconcile(repo, [])

    assert git_exclude.block_paths(repo) == ()
    assert git_exclude.block_paths(other) == ("/other-only",)


def test_special_characters_are_escaped(repo: Path) -> None:
    (repo / "a*b").write_text("x")
    (repo / "axb").write_text("x")

    git_exclude.reconcile(repo, ["a*b"])

    assert git_exclude.block_paths(repo) == ("/a\\*b",)
    assert _git(repo, "status", "--porcelain") == "?? axb"


def test_unbalanced_block_is_refused_and_file_left_alone(repo: Path) -> None:
    content = '# spaex-local:start worktree=".git"\n/x\n'
    _exclude(repo).write_text(content)

    with pytest.raises(LocalExcludeMalformedError):
        git_exclude.reconcile(repo, ["y"])
    assert _exclude(repo).read_text() == content


def test_outside_git_is_a_no_op(tmp_path: Path, git_binary: str) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    assert git_exclude.exclude_file(plain) is None
    git_exclude.reconcile(plain, ["x"])
    assert git_exclude.block_paths(plain) == ()
