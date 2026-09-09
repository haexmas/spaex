"""Spec 017 T014-T015 - concurrency and interrupted-materialization tests."""

from __future__ import annotations

import multiprocessing
import shutil
import subprocess
from pathlib import Path

import pytest

from spaex.git.molecule_store import get_or_extract
from spaex.migrate.transform import clone_dir
from spaex.util.errors import MoleculeTreeExtractionError

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_CANONICAL = "https://example.invalid/example/publisher"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _git_bytes(cwd: Path, *args: str) -> bytes:
    """Run Git and return raw stdout without working-tree newline conversion."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, check=True
    )
    return proc.stdout


def _publish(publisher: Path) -> str:
    publisher.mkdir(parents=True, exist_ok=True)
    _git(publisher, "init", "-q")
    _git(publisher, "config", "user.email", "author@example.com")
    _git(publisher, "config", "user.name", "author")
    _git(publisher, "config", "commit.gpgsign", "false")
    (publisher / "mol").mkdir()
    (publisher / "mol" / "install.py").write_text("#!/usr/bin/env python3\nprint('ok')\n")
    (publisher / "mol" / "manifest.json").write_text('{"spaex_version":"4"}\n')
    (publisher / "mol" / "constitution.md").write_text(
        "# Principle: mol\n\nBody content used for byte-identity check.\n"
    )
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "publish mol")
    return _git(publisher, "rev-parse", "HEAD")


def _clone(state_root: Path, canonical: str, publisher: Path) -> Path:
    target = clone_dir(state_root, canonical)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, target)
    return target


def _worker(args: tuple[Path, str, str, str, Path]) -> str:
    """Subprocess worker that calls get_or_extract and returns the dir string."""
    repo_dir, source_url, revision, molecule_path, state_root = args
    result = get_or_extract(repo_dir, source_url, revision, molecule_path, state_root)
    return str(result)


# --- T014 [US2] ------------------------------------------------------------


def test_concurrent_requests_for_same_key_both_succeed(tmp_path: Path) -> None:
    """AS1 (FR-008, SC-005): two concurrent get_or_extract calls both succeed.

    Uses multiprocessing so the ManifestLockContext file-lock path is
    exercised at the OS level (flock on Linux serialises separate processes
    reliably where same-process threads may not).
    """
    publisher = tmp_path / "publisher"
    sha = _publish(publisher)
    state_root = tmp_path / "state"
    repo_dir = _clone(state_root, _CANONICAL, publisher)

    args = (repo_dir, _CANONICAL, sha, "mol", state_root)
    # Use the platform default: Windows does not provide the POSIX-only
    # ``fork`` context, while the default still gives us separate processes
    # everywhere and therefore exercises the file-lock path.
    ctx = multiprocessing.get_context()
    with ctx.Pool(processes=2) as pool:
        results = pool.map(_worker, [args, args])

    assert len(results) == 2
    assert results[0] == results[1]

    final = Path(results[0])
    assert final.is_dir()
    manifest_contents = (final / "manifest.json").read_bytes()
    assert manifest_contents == _git_bytes(publisher, "show", f"{sha}:mol/manifest.json")
    constitution_contents = (final / "constitution.md").read_bytes()
    assert constitution_contents == _git_bytes(
        publisher, "show", f"{sha}:mol/constitution.md"
    )


# --- T015 [US2] ------------------------------------------------------------


def test_interrupted_materialization_does_not_corrupt_final_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS2 (FR-009): an interrupted extraction leaves final_dir absent.

    Monkeypatches os.replace within the molecule_store module to raise
    partway through the first call, then verifies:
    - the first call raises,
    - no directory exists at the final path,
    - a second, uninterrupted call materializes cleanly.
    """
    publisher = tmp_path / "publisher"
    sha = _publish(publisher)
    state_root = tmp_path / "state"
    repo_dir = _clone(state_root, _CANONICAL, publisher)

    from spaex.git import molecule_store

    calls = {"n": 0}
    real_replace = molecule_store.os.replace

    def _flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated crash mid-materialization")
        return real_replace(src, dst)

    monkeypatch.setattr(molecule_store.os, "replace", _flaky_replace)

    with pytest.raises(MoleculeTreeExtractionError, match="simulated crash") as error:
        get_or_extract(repo_dir, _CANONICAL, sha, "mol", state_root)
    assert isinstance(error.value.__cause__, OSError)

    source_digest = clone_dir(state_root, _CANONICAL).name
    final_dir = state_root / "molecule-store" / source_digest / sha / "mol"
    assert not final_dir.exists(), (
        "interrupted materialization must not leave a partial final_dir; "
        f"found: {final_dir}"
    )

    # A subsequent call, no longer flaky, must succeed and materialize.
    monkeypatch.setattr(molecule_store.os, "replace", real_replace)
    result = get_or_extract(repo_dir, _CANONICAL, sha, "mol", state_root)
    assert result == final_dir
    assert result.is_dir()
    assert (result / "manifest.json").exists()
