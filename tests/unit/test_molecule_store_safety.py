"""Spec 017 T005/T012/T013 — path-containment validation tests for
`git.molecule_store`.

Crafted `tarfile.TarInfo` fixtures, not real git repos, per research.md's
"crafted fixtures over real git repos" decision for exercising specific
member types (`..`-escapes, symlink/hardlink escapes) that git itself
cannot always be made to track directly. T012/T013 (User Story 3's
end-to-end and aggregate-outcome tests) additionally exercise the full
`get_or_extract` path against a real git repository.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
from pathlib import Path
from unittest import mock

import pytest

from spaex.git import revparse
from spaex.git.cache import clone_dir
from spaex.git.molecule_store import _validate_and_extract, get_or_extract
from spaex.util.errors import MoleculeTreeExtractionError

# T012/T013 need a real git repo; T001-T011's crafted-tar tests above do not,
# so the skip is applied per-test rather than module-wide.
_requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")

_SOURCE_URL = "https://example.invalid/example/publisher"


def _git(repo: Path, *args: str) -> str:
    """Run a Git command in ``repo`` and return its stripped standard output."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _build_and_validate(add_members, destination: Path) -> None:
    """Build a tar with ``add_members`` and validate its extraction."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        add_members(tar)
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r") as tar:
        _validate_and_extract(tar, destination)


def test_dotdot_escaping_path_is_rejected(tmp_path: Path) -> None:
    """Worked example (a): a member whose own path escapes via `..`."""

    def add(tar: tarfile.TarFile) -> None:
        """Add a regular-file member whose path escapes the destination."""
        info = tarfile.TarInfo(name="../../etc/passwd")
        info.size = 0
        tar.addfile(info, io.BytesIO(b""))

    with pytest.raises(MoleculeTreeExtractionError):
        _build_and_validate(add, tmp_path)


def test_absolute_symlink_target_is_rejected_unconditionally(tmp_path: Path) -> None:
    """Worked example (b): absolute link target refused even if it would
    resolve inside destination — the 2026-09-08 clarification. Uses a target
    that does NOT exist under tmp_path, proving the refusal is unconditional
    (no resolution is even attempted)."""

    def add(tar: tarfile.TarFile) -> None:
        """Add a symlink member with an absolute target."""
        info = tarfile.TarInfo(name="innocuous.txt")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)

    with pytest.raises(MoleculeTreeExtractionError):
        _build_and_validate(add, tmp_path)


def test_relative_escaping_symlink_target_is_rejected(tmp_path: Path) -> None:
    """Worked example (c): relative link target that resolves outside destination."""

    def add(tar: tarfile.TarFile) -> None:
        """Add a directory containing a symlink that targets outside it."""
        subdir = tarfile.TarInfo(name="subdir")
        subdir.type = tarfile.DIRTYPE
        tar.addfile(subdir)
        info = tarfile.TarInfo(name="subdir/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        tar.addfile(info)

    with pytest.raises(MoleculeTreeExtractionError):
        _build_and_validate(add, tmp_path)


def test_nesting_under_a_rejected_symlink_is_also_rejected(tmp_path: Path) -> None:
    """Worked example (d), literal form: member 1 (a symlink) is itself
    rejected because it escapes destination; member 2 nests under that
    never-created path. The archive-order ancestor check must reject member
    2 too, since 'escape' was never established as a safe directory."""

    def add(tar: tarfile.TarFile) -> None:
        """Add an escaping symlink followed by a member nested beneath it."""
        link = tarfile.TarInfo(name="escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../outside"
        tar.addfile(link)
        nested = tarfile.TarInfo(name="escape/payload.txt")
        nested.size = 3
        tar.addfile(nested, io.BytesIO(b"bad"))

    with pytest.raises(MoleculeTreeExtractionError):
        _build_and_validate(add, tmp_path)


def test_escape_through_an_accepted_symlink_via_own_dotdot_is_rejected(
    tmp_path: Path,
) -> None:
    """Worked example (d), compounding form (FR-012): member 1 is an
    ACCEPTED symlink (`alias -> real`, resolves inside destination on its
    own). A later member's OWN path then traverses `..` through the
    symlink's resolved location to escape further than a naive per-member
    check would catch. `Path.resolve()` following the real, already-created
    symlink must still land outside destination and be refused."""

    def add(tar: tarfile.TarFile) -> None:
        """Add a safe symlink followed by a member that escapes through it."""
        real = tarfile.TarInfo(name="real")
        real.type = tarfile.DIRTYPE
        tar.addfile(real)
        link = tarfile.TarInfo(name="alias")
        link.type = tarfile.SYMTYPE
        link.linkname = "real"
        tar.addfile(link)
        escaping = tarfile.TarInfo(name="alias/../../outside")
        escaping.size = 3
        tar.addfile(escaping, io.BytesIO(b"bad"))

    with pytest.raises(MoleculeTreeExtractionError):
        _build_and_validate(add, tmp_path)


def test_legitimate_internal_symlink_is_accepted(tmp_path: Path) -> None:
    """Worked example (e): a relative, non-escaping symlink is accepted and
    extracted normally."""

    def add(tar: tarfile.TarFile) -> None:
        """Add a regular file and a relative symlink to that file."""
        target = tarfile.TarInfo(name="real-file.txt")
        content = b"hello\n"
        target.size = len(content)
        tar.addfile(target, io.BytesIO(content))
        link = tarfile.TarInfo(name="alias.txt")
        link.type = tarfile.SYMTYPE
        link.linkname = "real-file.txt"
        tar.addfile(link)

    _build_and_validate(add, tmp_path)

    assert (tmp_path / "real-file.txt").read_bytes() == b"hello\n"
    assert (tmp_path / "alias.txt").is_symlink()


def test_benign_nesting_under_an_accepted_non_escaping_symlink_is_accepted(
    tmp_path: Path,
) -> None:
    """A file nested under an ACCEPTED symlink whose target is itself an
    established-safe directory must be extracted, not refused — the
    compounding check exists to catch escapes, not to ban all use of
    legitimate internal symlinks as path components."""

    def add(tar: tarfile.TarFile) -> None:
        """Add a safe directory symlink followed by a nested regular file."""
        real = tarfile.TarInfo(name="real")
        real.type = tarfile.DIRTYPE
        tar.addfile(real)
        target = tarfile.TarInfo(name="real/target.txt")
        content = b"hello"
        target.size = len(content)
        tar.addfile(target, io.BytesIO(content))
        link = tarfile.TarInfo(name="alias")
        link.type = tarfile.SYMTYPE
        link.linkname = "real"
        tar.addfile(link)
        nested = tarfile.TarInfo(name="alias/sneaky.txt")
        content2 = b"ok!"
        nested.size = len(content2)
        tar.addfile(nested, io.BytesIO(content2))

    _build_and_validate(add, tmp_path)

    assert (tmp_path / "real" / "sneaky.txt").read_bytes() == b"ok!"


def test_ordinary_nested_files_and_directories_extract_successfully(tmp_path: Path) -> None:
    """Worked example (f): the common case — no links anywhere, everything
    extracts successfully without false refusals."""

    def add(tar: tarfile.TarFile) -> None:
        """Add ordinary nested directories and a regular file."""
        a = tarfile.TarInfo(name="a")
        a.type = tarfile.DIRTYPE
        tar.addfile(a)
        b = tarfile.TarInfo(name="a/b")
        b.type = tarfile.DIRTYPE
        tar.addfile(b)
        c = tarfile.TarInfo(name="a/b/c.txt")
        content = b"ok!"
        c.size = len(content)
        tar.addfile(c, io.BytesIO(content))

    _build_and_validate(add, tmp_path)

    assert (tmp_path / "a" / "b" / "c.txt").read_bytes() == b"ok!"


def test_hardlink_with_absolute_target_is_rejected(tmp_path: Path) -> None:
    """FR-011's absolute-target refusal also applies to hardlink members,
    not just symlinks."""

    def add(tar: tarfile.TarFile) -> None:
        """Add a hardlink member with an absolute target."""
        info = tarfile.TarInfo(name="innocuous.txt")
        info.type = tarfile.LNKTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)

    with pytest.raises(MoleculeTreeExtractionError):
        _build_and_validate(add, tmp_path)


def test_member_resolving_to_destination_itself_is_rejected(tmp_path: Path) -> None:
    """A member whose normalized path equals the destination directory
    itself (e.g. name '.') must be rejected, not silently treated as a
    no-op."""

    def add(tar: tarfile.TarFile) -> None:
        """Add a directory member whose path resolves to the destination."""
        info = tarfile.TarInfo(name=".")
        info.type = tarfile.DIRTYPE
        tar.addfile(info)

    with pytest.raises(MoleculeTreeExtractionError):
        _build_and_validate(add, tmp_path)


def _init_repo(root: Path) -> None:
    """Initialize a repository with the test author's deterministic identity."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "haex-test@example.com")
    _git(root, "config", "user.name", "haex-test")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "core.eol", "lf")
    (root / ".gitattributes").write_bytes(b"* -text\n")


@_requires_git
def test_real_git_archive_with_tracked_symlink_is_validated(tmp_path: Path) -> None:
    """T012 (US3): a real git repo with one legitimate, non-escaping tracked
    symlink, materialized through the FULL get_or_extract path (real `git
    archive`, not a crafted tarfile fixture) — proves T004's validation and
    T006's git-archive integration connect correctly end-to-end, not just in
    isolation against synthetic fixtures."""
    publisher = tmp_path / "publisher"
    publisher.mkdir()
    _init_repo(publisher)
    mol = publisher / "mol"
    mol.mkdir()
    (mol / "real.txt").write_text("real content\n")
    (mol / "alias.txt").symlink_to("real.txt")
    _git(publisher, "add", "-A")
    _git(publisher, "commit", "-q", "-m", "publish")
    sha = _git(publisher, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    repo_dir = clone_dir(state_root, _SOURCE_URL)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, repo_dir)
    canonical_sha = revparse.full_sha(repo_dir, sha)

    materialized = get_or_extract(repo_dir, _SOURCE_URL, canonical_sha, "mol", state_root)

    assert (materialized / "real.txt").read_text() == "real content\n"
    assert (materialized / "alias.txt").is_symlink()
    assert (materialized / "alias.txt").read_text() == "real content\n"


@_requires_git
def test_materialization_failure_leaves_no_final_directory(tmp_path: Path) -> None:
    """T013 (US3): a hostile archive fed through the FULL get_or_extract flow
    (not just _validate_and_extract in isolation) must raise, and the final
    cache path must never be populated — the aggregate-outcome guarantee
    from contracts/tar-member-validation.md, verified end-to-end."""
    publisher = tmp_path / "publisher"
    sha = _publish_dummy_repo(publisher)

    state_root = tmp_path / "state"
    repo_dir = clone_dir(state_root, _SOURCE_URL)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, repo_dir)
    canonical_sha = revparse.full_sha(repo_dir, sha)

    hostile_tar = io.BytesIO()
    with tarfile.open(fileobj=hostile_tar, mode="w") as tar:
        info = tarfile.TarInfo(name="../../etc/passwd")
        info.size = 0
        tar.addfile(info, io.BytesIO(b""))

    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        """Return the hostile archive for archive calls and delegate all others."""
        if "archive" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=hostile_tar.getvalue(), stderr=b"")
        return real_run(cmd, *args, **kwargs)

    with (
        mock.patch("subprocess.run", side_effect=fake_run),
        pytest.raises(MoleculeTreeExtractionError),
    ):
        get_or_extract(repo_dir, _SOURCE_URL, canonical_sha, "mol", state_root)

    digest = clone_dir(state_root, _SOURCE_URL).name
    would_be_final_dir = state_root / "molecule-store" / digest / canonical_sha / "mol"
    assert not would_be_final_dir.exists()


@_requires_git
def test_archive_without_requested_prefix_is_rejected(tmp_path: Path) -> None:
    """An archive that omits the requested molecule prefix raises a typed error."""
    publisher = tmp_path / "publisher"
    sha = _publish_dummy_repo(publisher)

    state_root = tmp_path / "state"
    repo_dir = clone_dir(state_root, _SOURCE_URL)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, repo_dir)
    canonical_sha = revparse.full_sha(repo_dir, sha)

    wrong_prefix = io.BytesIO()
    with tarfile.open(fileobj=wrong_prefix, mode="w") as tar:
        directory = tarfile.TarInfo(name="other")
        directory.type = tarfile.DIRTYPE
        tar.addfile(directory)
        member = tarfile.TarInfo(name="other/file.txt")
        member.size = 2
        tar.addfile(member, io.BytesIO(b"no"))

    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        """Return an archive with a prefix different from the requested path."""
        if "archive" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=wrong_prefix.getvalue(), stderr=b""
            )
        return real_run(cmd, *args, **kwargs)

    with (
        mock.patch("subprocess.run", side_effect=fake_run),
        pytest.raises(MoleculeTreeExtractionError),
    ):
        get_or_extract(repo_dir, _SOURCE_URL, canonical_sha, "mol", state_root)


def _publish_dummy_repo(publisher: Path) -> str:
    """Create a minimal publisher repository and return its commit SHA."""
    publisher.mkdir()
    _init_repo(publisher)
    mol = publisher / "mol"
    mol.mkdir()
    (mol / "manifest.json").write_text('{"id": "x"}')
    _git(publisher, "add", "-A")
    _git(publisher, "commit", "-q", "-m", "publish")
    return _git(publisher, "rev-parse", "HEAD")
