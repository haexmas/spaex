"""Spec 029 US2: local behavior rules compose separately from the team constitution."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.cli import install as install_cli
from spaex.install.local_scope import LOCAL_PREAMBLE

from .test_project_local_fragments import _stub_invoke_composer

_TEAM_ID = "com.example.publisher.team"
_MINE_ID = "com.example.publisher.mine"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _behavior_molecule(path: str, fragment_id: str, rule: str) -> dict:
    return {
        "path": path,
        "version": "1.0.0",
        "atoms": {"behavior": ["rule.md"]},
        "files": {
            "rule.md": (
                f"---\nid: {fragment_id}\nkind: constitution_fragment\n"
                f"atom_source: {path}\n---\n{rule}\n"
            )
        },
    }


@pytest.fixture
def scene(tmp_path: Path, haex_add_helpers, monkeypatch, git_binary: str) -> SimpleNamespace:
    monkeypatch.setattr(behavior_orchestrate, "invoke_composer", _stub_invoke_composer)
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _TEAM_ID: _behavior_molecule("team", "team-rule", "**MUST** write tests."),
            _MINE_ID: _behavior_molecule("mine", "mine-rule", "**SHOULD** prefer short names."),
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    _git(consumer, "init", "-q")
    (consumer / ".gitignore").write_text(".spaex/manifest.json.lock\n.spaex/composer.log\n")

    def add(ids: str, *, local: bool = False) -> int:
        return haex_add_helpers["run_add"](
            consumer, state_root, monkeypatch,
            source_url=canonical, revision=head, molecule_ids=ids, local=local,
        )

    def remove(ids: str) -> int:
        return haex_add_helpers["run_remove"](consumer, state_root, monkeypatch, ids, local=True)

    assert add(_TEAM_ID) == 0
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-q", "-m", "team rules")
    return SimpleNamespace(consumer=consumer, add=add, remove=remove)


def test_local_rules_get_their_own_document(
    scene: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = scene.consumer
    team = (consumer / ".spaex/constitution.md").read_bytes()

    assert scene.add(_MINE_ID, local=True) == 0

    assert (consumer / ".spaex/constitution.md").read_bytes() == team
    local = (consumer / ".spaex/local/constitution.md").read_text()
    header, preamble = local.split("\n")[:2]
    assert header.startswith("<!-- spaex-composed:")
    assert preamble == LOCAL_PREAMBLE.rstrip("\n")
    assert f"{_MINE_ID}/mine-rule" in local
    assert _TEAM_ID not in local
    assert _git(consumer, "status", "--porcelain", "--untracked-files=all") == ""

    capsys.readouterr()
    assert install_cli.run(SimpleNamespace(repo_root=str(consumer))) == 0
    assert "reused .spaex/local/constitution.md" in capsys.readouterr().out


def test_removing_local_rules_drops_the_document(scene: SimpleNamespace) -> None:
    consumer = scene.consumer
    team = (consumer / ".spaex/constitution.md").read_bytes()
    assert scene.add(_MINE_ID, local=True) == 0

    assert scene.remove(_MINE_ID) == 0

    assert not (consumer / ".spaex/local").exists()
    assert (consumer / ".spaex/constitution.md").read_bytes() == team
