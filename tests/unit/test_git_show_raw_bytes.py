"""`git show` MUST return unfiltered blob bytes even with `.gitattributes` filters (R3)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from spaex.git.show import show_bytes
from spaex.util.errors import ContributionFileNotFoundError

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "haex-test@example.com")
    _git(root, "config", "user.name", "haex-test")
    _git(root, "config", "commit.gpgsign", "false")


def test_show_bytes_returns_blob_content(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "constitution.md").write_bytes(b"# Body\nline\n")
    _git(tmp_path, "add", "constitution.md")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    sha = _git(tmp_path, "rev-parse", "HEAD")
    body = show_bytes(
        tmp_path, sha, "constitution.md", not_found_error=ContributionFileNotFoundError
    )
    assert body == b"# Body\nline\n"


def test_show_bytes_bypasses_gitattributes_filter(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".gitattributes").write_text("*.md text=auto\n")
    _git(tmp_path, "add", ".gitattributes")
    (tmp_path / "constitution.md").write_bytes(b"crlf\r\nnormal\n")
    _git(tmp_path, "add", "constitution.md")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    sha = _git(tmp_path, "rev-parse", "HEAD")
    body = show_bytes(
        tmp_path, sha, "constitution.md", not_found_error=ContributionFileNotFoundError
    )
    assert body in (b"crlf\r\nnormal\n", b"crlf\nnormal\n")


def test_show_bytes_raises_on_missing_path(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "constitution.md").write_bytes(b"x")
    _git(tmp_path, "add", "constitution.md")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    sha = _git(tmp_path, "rev-parse", "HEAD")
    with pytest.raises(ContributionFileNotFoundError):
        show_bytes(
            tmp_path, sha, "does-not-exist.md", not_found_error=ContributionFileNotFoundError
        )
