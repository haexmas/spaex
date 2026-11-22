"""Spec 029 US2: local behavior rules compose separately from the team constitution."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior.decisions import Choice
from spaex.cli import install as install_cli
from spaex.constitution.show import show
from spaex.install.local_scope import LOCAL_PREAMBLE

from ..conftest import Operator, StubCheck, make_finding

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
def scene(
    tmp_path: Path, haex_add_helpers, monkeypatch, git_binary: str, stub_check: StubCheck
) -> SimpleNamespace:
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _TEAM_ID: _behavior_molecule("team", "team-rule", "**MUST** write tests."),
            _MINE_ID: _behavior_molecule("mine", "mine-rule", "**SHOULD** prefer short names."),
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    _git(consumer, "init", "-q")
    (consumer / ".gitignore").write_text(
        ".spaex/manifest.json.lock\n.spaex/composer.log\n", encoding="utf-8"
    )

    def add(ids: str, *, local: bool = False) -> int:
        return haex_add_helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            revision=head,
            molecule_ids=ids,
            local=local,
        )

    def remove(ids: str) -> int:
        return haex_add_helpers["run_remove"](consumer, state_root, monkeypatch, ids, local=True)

    assert add(_TEAM_ID) == 0
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-q", "-m", "team rules")
    return SimpleNamespace(consumer=consumer, add=add, remove=remove, check=stub_check)


def test_local_rules_get_their_own_document(
    scene: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = scene.consumer
    team = (consumer / ".spaex/constitution.md").read_bytes()

    assert scene.add(_MINE_ID, local=True) == 0

    assert (consumer / ".spaex/constitution.md").read_bytes() == team
    local = (consumer / ".spaex/local/constitution.md").read_text(encoding="utf-8")
    lines = local.split("\n")
    assert lines[0].startswith("<!-- spaex-composed:")
    assert lines[1] == "# spaex Behavior Harness"
    preamble = LOCAL_PREAMBLE.rstrip("\n")
    first_block = next(i for i, line in enumerate(lines) if line.startswith("<!-- spaex-fragment"))
    assert preamble in lines[2:first_block], "the preamble sits between the notices and the rules"
    assert f'<!-- spaex-fragment id="{_MINE_ID}/mine-rule"' in local
    assert "**SHOULD** prefer short names." in local
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


def test_constitution_show_prints_local_section_last(scene: SimpleNamespace) -> None:
    consumer = scene.consumer
    assert scene.add(_MINE_ID, local=True) == 0
    out = io.BytesIO()

    show(consumer, no_preface=True, out=out)

    text = out.getvalue().decode()
    team_at = text.index(f"{_TEAM_ID}/team-rule")
    local_at = text.index("## Local (this checkout only)")
    assert team_at < local_at < text.index(f"{_MINE_ID}/mine-rule")


def test_local_check_covers_only_local_fragments_and_keeps_its_own_decisions(
    scene: SimpleNamespace, operator: Operator
) -> None:
    """Findings among local fragments are asked and stored under `.spaex/local/`; the
    project constitution and its decisions are never touched by the local pass."""
    consumer = scene.consumer
    team = (consumer / ".spaex/constitution.md").read_bytes()
    team_decisions = (consumer / ".spaex/decisions.json").read_bytes()
    checks_before = scene.check.calls

    scene.check.factory = lambda fragments: (
        [
            make_finding(
                fragments,
                "duplicate",
                (f"{_MINE_ID}/mine-rule", 1, 1),
                (f"{_MINE_ID}/other-rule", 1, 1),
            )
        ]
        if any(f.id == "other-rule" for f in fragments)
        else []
    )
    operator.default = Choice(kind="keep", kept=0)

    assert scene.add(_MINE_ID, local=True) == 0
    assert scene.check.calls == checks_before + 1
    assert scene.check.seen[-1] == (f"{_MINE_ID}/mine-rule",)
    assert operator.asked == []

    assert (consumer / ".spaex/constitution.md").read_bytes() == team
    assert (consumer / ".spaex/decisions.json").read_bytes() == team_decisions
    local_decisions = consumer / ".spaex/local/decisions.json"
    assert local_decisions.exists()
    assert '"checked"' in local_decisions.read_text(encoding="utf-8")
