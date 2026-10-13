"""Spec 029 refusals: nothing local may change team-owned state (FR-006, FR-010, FR-017)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import install as install_cli
from spaex.util.errors import (
    InstallTransactionFailedError,
    LocalAdoptionShadowedError,
    LocalManifestInvalidError,
)

_PROJECT_ID = "com.example.publisher.proj"
_CLASH_ID = "com.example.publisher.clash"
_TRACKED_ID = "com.example.publisher.tracked"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def scene(tmp_path: Path, haex_add_helpers, monkeypatch, git_binary: str) -> SimpleNamespace:
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _PROJECT_ID: {"path": "proj", "version": "1.0.0", "atoms": {"tools": ["project.txt"]}},
            _CLASH_ID: {"path": "clash", "version": "1.0.0", "atoms": {"tools": ["project.txt"]}},
            _TRACKED_ID: {"path": "tracked", "version": "1.0.0", "atoms": {"tools": ["README.md"]}},
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    _git(consumer, "init", "-q")
    (consumer / "README.md").write_text("team readme\n")

    def add(ids: str, *, local: bool = False) -> int:
        return haex_add_helpers["run_add"](
            consumer, state_root, monkeypatch,
            source_url=canonical, revision=head, molecule_ids=ids, local=local,
        )

    assert add(_PROJECT_ID) == 0
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-q", "-m", "project scope")
    return SimpleNamespace(consumer=consumer, add=add)


def _assert_untouched(consumer: Path) -> None:
    assert not (consumer / ".spaex/local").exists()
    assert _git(consumer, "status", "--porcelain", "--untracked-files=all") == ""


def test_project_molecule_cannot_be_adopted_locally(scene: SimpleNamespace) -> None:
    with pytest.raises(LocalAdoptionShadowedError):
        scene.add(_PROJECT_ID, local=True)
    _assert_untouched(scene.consumer)


@pytest.mark.parametrize(
    "molecule_id, path, reason",
    [(_CLASH_ID, "project.txt", "project-owned"), (_TRACKED_ID, "README.md", "tracked by git")],
)
def test_local_write_to_team_owned_path_is_refused(
    scene: SimpleNamespace, molecule_id: str, path: str, reason: str
) -> None:
    before = (scene.consumer / path).read_bytes()

    with pytest.raises(InstallTransactionFailedError) as caught:
        scene.add(molecule_id, local=True)

    assert caught.value.context["install_key"] == "local-path-conflict"
    assert reason in caught.value.message
    assert (scene.consumer / path).read_bytes() == before
    _assert_untouched(scene.consumer)


def test_invalid_overlay_stops_install(scene: SimpleNamespace) -> None:
    overlay = scene.consumer / ".spaex/local/manifest.json"
    overlay.parent.mkdir(parents=True)
    overlay.write_text('{"spaex_version": "4", "compounds": [], "identity": "x"}')

    with pytest.raises(LocalManifestInvalidError):
        install_cli.run(SimpleNamespace(repo_root=str(scene.consumer)))
