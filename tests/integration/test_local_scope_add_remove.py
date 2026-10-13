"""Spec 029: `spaex add --local` / `spaex remove --local` end to end (US1, US3, US5)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import install as install_cli
from spaex.cli import status as status_cli
from spaex.install import git_exclude
from spaex.util.errors import UnknownMoleculeIdError

_PROJECT_ID = "com.example.publisher.proj"
_MINE_ID = "com.example.publisher.mine"
_PROJECT_FILES = (".spaex/manifest.json", ".spaex/install.lock", "project.txt")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _snapshot(consumer: Path) -> dict[str, bytes]:
    return {path: (consumer / path).read_bytes() for path in _PROJECT_FILES}


@pytest.fixture
def scene(tmp_path: Path, haex_add_helpers, monkeypatch, git_binary: str) -> SimpleNamespace:
    """A committed consumer repo with one project molecule installed."""
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _PROJECT_ID: {"path": "proj", "version": "1.0.0", "atoms": {"tools": ["project.txt"]}},
            _MINE_ID: {"path": "mine", "version": "1.0.0", "atoms": {"tools": ["mine.txt"]}},
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    _git(consumer, "init", "-q")
    helpers = haex_add_helpers

    def add(ids: str, *, local: bool = False) -> int:
        return helpers["run_add"](
            consumer, state_root, monkeypatch,
            source_url=canonical, revision=head, molecule_ids=ids, local=local,
        )

    def remove(ids: str, *, local: bool = False) -> int:
        return helpers["run_remove"](consumer, state_root, monkeypatch, ids, local=local)

    assert add(_PROJECT_ID) == 0
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-q", "-m", "project scope")
    return SimpleNamespace(consumer=consumer, add=add, remove=remove)


def test_add_local_leaves_git_clean_and_project_identical(scene: SimpleNamespace) -> None:
    consumer = scene.consumer
    before = _snapshot(consumer)

    assert scene.add(_MINE_ID, local=True) == 0

    assert (consumer / "mine.txt").read_text().startswith(f"# {_MINE_ID}")
    assert _snapshot(consumer) == before
    assert _git(consumer, "status", "--porcelain", "--untracked-files=all") == ""
    assert git_exclude.block_paths(consumer) == ("/mine.txt",)
    assert (consumer / ".spaex/local/install.lock").is_file()


def test_reinstall_with_local_scope_is_byte_identical(scene: SimpleNamespace) -> None:
    consumer = scene.consumer
    assert scene.add(_MINE_ID, local=True) == 0
    local_lock = (consumer / ".spaex/local/install.lock").read_bytes()
    project = _snapshot(consumer)

    assert install_cli.run(SimpleNamespace(repo_root=str(consumer))) == 0

    assert (consumer / ".spaex/local/install.lock").read_bytes() == local_lock
    assert _snapshot(consumer) == project


def test_remove_last_local_leaves_no_trace(scene: SimpleNamespace) -> None:
    consumer = scene.consumer
    before = _snapshot(consumer)
    assert scene.add(_MINE_ID, local=True) == 0

    assert scene.remove(_MINE_ID, local=True) == 0

    assert not (consumer / "mine.txt").exists()
    assert not (consumer / ".spaex/local").exists()
    assert git_exclude.block_paths(consumer) == ()
    assert _snapshot(consumer) == before
    assert _git(consumer, "status", "--porcelain", "--untracked-files=all") == ""


def test_fresh_clone_ignores_local_scope(scene: SimpleNamespace, tmp_path: Path) -> None:
    assert scene.add(_MINE_ID, local=True) == 0
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(scene.consumer), str(clone))
    # spaex derives a git checkout's identity from `origin`; a bare path has no scheme.
    _git(clone, "remote", "set-url", "origin", "https://example.com/consumer")

    assert install_cli.run(SimpleNamespace(repo_root=str(clone))) == 0

    assert not (clone / "mine.txt").exists()
    assert not (clone / ".spaex/local").exists()
    assert _snapshot(clone) == _snapshot(scene.consumer)
    assert _git(clone, "status", "--porcelain", "--untracked-files=all") == ""


def test_later_project_adoption_shadows_but_keeps_local_entry(
    scene: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = scene.consumer
    assert scene.add(_MINE_ID, local=True) == 0
    overlay = (consumer / ".spaex/local/manifest.json").read_bytes()

    assert scene.add(_MINE_ID) == 0

    assert f"shadowed: {_MINE_ID}" in capsys.readouterr().out
    assert (consumer / ".spaex/local/manifest.json").read_bytes() == overlay
    assert (consumer / "mine.txt").is_file()
    assert git_exclude.block_paths(consumer) == ()


def test_remove_without_local_hints_for_local_only_id(scene: SimpleNamespace) -> None:
    assert scene.add(_MINE_ID, local=True) == 0

    with pytest.raises(UnknownMoleculeIdError) as caught:
        scene.remove(_MINE_ID)

    assert "--local" in caught.value.hint


def test_status_and_trace_label_scope(
    scene: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = scene.consumer
    assert scene.add(_MINE_ID, local=True) == 0
    capsys.readouterr()

    assert status_cli.run_status(SimpleNamespace(repo_root=str(consumer), format="json")) == 0
    status = json.loads(capsys.readouterr().out)
    scopes = {m["molecule_id"]: m["scope"] for m in status["molecules"]}
    assert status["format_version"] == 2
    assert scopes == {_PROJECT_ID: "project", _MINE_ID: "local"}
    assert status["drift"] == []

    assert status_cli.run_status(SimpleNamespace(repo_root=str(consumer), format="text")) == 0
    assert f"{_MINE_ID}@" in (text := capsys.readouterr().out) and "[local]" in text

    for path, scope in (("mine.txt", "local"), ("project.txt", "project")):
        assert status_cli.run_trace(
            SimpleNamespace(repo_root=str(consumer), path=path, format="json")
        ) == 0
        owners = json.loads(capsys.readouterr().out)["matches"][0]["owners"]
        assert [owner["scope"] for owner in owners] == [scope]
