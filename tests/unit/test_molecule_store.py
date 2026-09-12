"""Spec 017 T007-T011 — unit tests for `git.molecule_store.get_or_extract`."""

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
from spaex.git.molecule_store import get_or_extract
from spaex.util.errors import MoleculeTreeExtractionError, MoleculeTreePathNotFoundError

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")

_SOURCE_URL = "https://example.invalid/example/publisher"


def _git(repo: Path, *args: str) -> str:
    """Run a Git command in ``repo`` and return its stripped standard output."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _init_repo(root: Path) -> None:
    """Initialize a repository with the test author's deterministic identity."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "haex-test@example.com")
    _git(root, "config", "user.name", "haex-test")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "core.eol", "lf")
    (root / ".gitattributes").write_bytes(b"* -text\n")


def _publish_molecule(publisher: Path, files: dict[str, bytes]) -> str:
    """Write `files` (relative-path -> content) into a fresh repo and commit."""
    publisher.mkdir(parents=True, exist_ok=True)
    _init_repo(publisher)
    for rel_path, content in files.items():
        target = publisher / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "publish")
    return _git(publisher, "rev-parse", "HEAD")


def _clone(state_root: Path, canonical: str, publisher: Path) -> Path:
    """Copy ``publisher`` to its canonical clone-cache path and return that path."""
    target = clone_dir(state_root, canonical)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, target)
    return target


def test_molecule_path_shape_violation_raises_before_any_git_call(tmp_path: Path) -> None:
    """FR-014: an unsafe molecule_path is refused before touching git/filesystem."""
    with mock.patch("subprocess.run") as spy:
        with pytest.raises(ValueError):
            get_or_extract(
                tmp_path / "repo", _SOURCE_URL, "0" * 40, "../escape", tmp_path / "state"
            )
        with pytest.raises(ValueError):
            get_or_extract(
                tmp_path / "repo", _SOURCE_URL, "0" * 40, "/absolute", tmp_path / "state"
            )
        spy.assert_not_called()


def test_non_canonical_revision_raises_value_error(tmp_path: Path) -> None:
    """Contract: get_or_extract treats a non-canonical revision as a caller-
    contract violation, never attempting to resolve it itself."""
    with pytest.raises(ValueError):
        get_or_extract(tmp_path / "repo", _SOURCE_URL, "short-sha", "widgets", tmp_path / "state")
    with pytest.raises(ValueError):
        get_or_extract(tmp_path / "repo", _SOURCE_URL, "HEAD", "widgets", tmp_path / "state")


def test_cache_key_uses_source_url_digest_not_repo_dir(tmp_path: Path) -> None:
    """The molecule-store digest MUST come from clone_dir(state_root, source_url),
    never from repo_dir's local path — device-independence (Constitution
    Principle III). Uses a repo_dir path deliberately unrelated to the
    source-digest naming scheme, so a bug that derived the digest from
    repo_dir's own name (rather than source_url) would be caught."""
    publisher = tmp_path / "publisher"
    sha = _publish_molecule(publisher, {"widgets/hello/manifest.json": b'{"id":"x"}'})
    state_root = tmp_path / "state"
    canonical_target = clone_dir(state_root, _SOURCE_URL)
    canonical_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, canonical_target)

    custom_repo_dir = tmp_path / "some-arbitrary-local-clone-name"
    shutil.copytree(publisher, custom_repo_dir)
    canonical_sha = revparse.full_sha(custom_repo_dir, sha)

    materialized = get_or_extract(
        custom_repo_dir, _SOURCE_URL, canonical_sha, "widgets/hello", state_root
    )

    expected_digest = clone_dir(state_root, _SOURCE_URL).name
    relative = materialized.relative_to(state_root / "molecule-store")
    assert relative.parts[0] == expected_digest
    assert "some-arbitrary-local-clone-name" not in str(materialized)


def test_materialize_returns_correct_directly_nested_content(tmp_path: Path) -> None:
    """AS1: the returned directory directly contains the molecule's files,
    not nested under an extra molecule_path-named level (FR-002), with
    byte-identical content (FR-003)."""
    publisher = tmp_path / "publisher"
    sha = _publish_molecule(
        publisher,
        {
            "widgets/hello/manifest.json": b'{"id": "com.example.hello"}',
            "widgets/hello/helper.txt": b"hello from the molecule\n",
        },
    )
    repo_dir = _clone(tmp_path / "state", _SOURCE_URL, publisher)
    canonical_sha = revparse.full_sha(repo_dir, sha)

    materialized = get_or_extract(
        repo_dir, _SOURCE_URL, canonical_sha, "widgets/hello", tmp_path / "state"
    )

    assert sorted(p.name for p in materialized.iterdir()) == ["helper.txt", "manifest.json"]
    assert (materialized / "manifest.json").read_bytes() == b'{"id": "com.example.hello"}'
    assert (materialized / "helper.txt").read_bytes() == b"hello from the molecule\n"


def test_materialization_preserves_blob_bytes_with_autocrlf_enabled(tmp_path: Path) -> None:
    """FR-003: archive extraction must not apply Windows worktree conversion."""
    publisher = tmp_path / "publisher"
    publisher.mkdir()
    _init_repo(publisher)
    (publisher / ".gitattributes").write_bytes(b"* text=auto\n")
    molecule_file = publisher / "widgets" / "hello" / "constitution.md"
    molecule_file.parent.mkdir(parents=True)
    molecule_file.write_bytes(b"one\ntwo\n")
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "publish")
    _git(publisher, "config", "core.autocrlf", "true")
    sha = _git(publisher, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    repo_dir = _clone(state_root, _SOURCE_URL, publisher)
    canonical_sha = revparse.full_sha(repo_dir, sha)

    materialized = get_or_extract(
        repo_dir, _SOURCE_URL, canonical_sha, "widgets/hello", state_root
    )

    assert (materialized / "constitution.md").read_bytes() == b"one\ntwo\n"


def test_repeated_request_is_a_cache_hit_no_reextraction(tmp_path: Path) -> None:
    """AS2/FR-005/SC-002: a second identical request returns the same
    directory without a second `git archive` subprocess call."""
    publisher = tmp_path / "publisher"
    sha = _publish_molecule(publisher, {"widgets/hello/manifest.json": b'{"id":"x"}'})
    repo_dir = _clone(tmp_path / "state", _SOURCE_URL, publisher)
    canonical_sha = revparse.full_sha(repo_dir, sha)

    first = get_or_extract(
        repo_dir, _SOURCE_URL, canonical_sha, "widgets/hello", tmp_path / "state"
    )

    with mock.patch("subprocess.run", wraps=subprocess.run) as spy:
        second = get_or_extract(
            repo_dir, _SOURCE_URL, canonical_sha, "widgets/hello", tmp_path / "state"
        )
        assert second == first
        archive_calls = [c for c in spy.call_args_list if "archive" in c.args[0]]
        assert archive_calls == []


def test_nonexistent_molecule_path_fails_distinctly(tmp_path: Path) -> None:
    """AS3/FR-004: a molecule path absent at the revision raises the
    dedicated not-found error, not MoleculeTreeExtractionError, and leaves
    no directory at the would-be cache location."""
    publisher = tmp_path / "publisher"
    sha = _publish_molecule(publisher, {"widgets/hello/manifest.json": b'{"id":"x"}'})
    repo_dir = _clone(tmp_path / "state", _SOURCE_URL, publisher)
    canonical_sha = revparse.full_sha(repo_dir, sha)
    state_root = tmp_path / "state"

    with pytest.raises(MoleculeTreePathNotFoundError):
        get_or_extract(repo_dir, _SOURCE_URL, canonical_sha, "widgets/nope", state_root)

    digest = clone_dir(state_root, _SOURCE_URL).name
    would_be_final_dir = state_root / "molecule-store" / digest / canonical_sha / "widgets" / "nope"
    assert not would_be_final_dir.exists()


def test_tracked_file_at_molecule_path_is_rejected(tmp_path: Path) -> None:
    """A tracked file cannot be published as the molecule directory."""
    publisher = tmp_path / "publisher"
    sha = _publish_molecule(publisher, {"mol": b"not a directory"})
    state_root = tmp_path / "state"
    repo_dir = _clone(state_root, _SOURCE_URL, publisher)
    canonical_sha = revparse.full_sha(repo_dir, sha)

    with pytest.raises(MoleculeTreeExtractionError):
        get_or_extract(repo_dir, _SOURCE_URL, canonical_sha, "mol", state_root)

    final_dir = state_root / "molecule-store" / clone_dir(state_root, _SOURCE_URL).name
    assert not (final_dir / canonical_sha / "mol").exists()


def test_empty_archive_succeeds_with_empty_directory(tmp_path: Path) -> None:
    """Edge case / FR-001 amendment: a successful archive with zero tar
    members must still create and publish an existing, empty directory
    (distinguishable from the not-found case above). Git cannot track a
    genuinely empty directory, so this is exercised by mocking subprocess.run
    to return a successful, member-less tar stream."""
    publisher = tmp_path / "publisher"
    sha = _publish_molecule(publisher, {"widgets/hello/manifest.json": b'{"id":"x"}'})
    repo_dir = _clone(tmp_path / "state", _SOURCE_URL, publisher)
    canonical_sha = revparse.full_sha(repo_dir, sha)

    empty_tar_buf = io.BytesIO()
    with tarfile.open(fileobj=empty_tar_buf, mode="w"):
        pass  # zero members

    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        """Return the empty archive for archive calls and delegate all other calls."""
        if "archive" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=empty_tar_buf.getvalue(), stderr=b"")
        return real_run(cmd, *args, **kwargs)

    with mock.patch("subprocess.run", side_effect=fake_run):
        materialized = get_or_extract(
            repo_dir, _SOURCE_URL, canonical_sha, "widgets/empty", tmp_path / "state"
        )

    assert materialized.is_dir()
    assert list(materialized.iterdir()) == []
