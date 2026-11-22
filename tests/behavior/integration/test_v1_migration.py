"""A repo composed under format version 1 moves to version 2 in one install (Spec 030 T019).

Version 1 left a clause-style `constitution.md`, `clarifications.json` and perhaps a
`.stale` marker. One `spaex install` must replace the file, remove both legacy files,
ask the findings anew (old answers refer to rewritten clauses, not passages) and then
be stable: a second install changes nothing.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior.decisions import Choice
from spaex.cli import install as install_cli
from spaex.cli.main import main
from spaex.util.errors import HaexError

from ..conftest import Operator, StubCheck, make_finding

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")

_TABS = "com.example.publisher.tabs"
_SPACES = "com.example.publisher.spaces"

_V1_CONSTITUTION = (
    '<!-- spaex-composed:source_hash="'
    + "a" * 64
    + '" build_input_hash="'
    + "b" * 64
    + '" version="1" -->\n'
    "# spaex Behavior Harness\n\n## MUST\n\n"
    f"- Always use tabs. _[from `{_TABS}/tabs`]_\n"
    f"- Never use tabs. _[from `{_SPACES}/spaces`]_\n"
)
_V1_CLARIFICATIONS = json.dumps(
    {
        "schema_version": 1,
        "clarifications": {
            "k" * 64: {
                "question": "tabs or spaces?",
                "cited_fragments": [
                    {"molecule_id": _TABS, "fragment_id": "tabs", "body_sha256": "c" * 64}
                ],
                "answer": "tabs",
                "asked_at": "2026-01-01T00:00:00Z",
                "answered_at": "2026-01-01T00:00:01Z",
            }
        },
    }
)


def _molecule(path: str, fragment_id: str, rule: str) -> dict:
    return {
        "path": path,
        "version": "1.0.0",
        "atoms": {"behavior": ["rule.md"]},
        "files": {
            "rule.md": (
                f"---\nid: {fragment_id}\nkind: constitution_fragment\n"
                f"atom_source: pkg.{fragment_id}\n---\nintro\n{rule}\noutro\n"
            )
        },
    }


@pytest.fixture
def v1_repo(
    tmp_path: Path, haex_add_helpers, monkeypatch, git_binary: str, stub_check: StubCheck
) -> SimpleNamespace:
    helpers = haex_add_helpers
    canonical, head, state_root = helpers["make_publisher"](
        tmp_path,
        {
            _TABS: _molecule("tabs", "tabs", "**MUST** always use tabs."),
            _SPACES: _molecule("spaces", "spaces", "**MUST** never use tabs."),
        },
    )
    consumer = helpers["make_consumer"](tmp_path)
    assert (
        helpers["run_add"](
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            revision=head,
            molecule_ids=f"{_TABS},{_SPACES}",
        )
        == 0
    )
    # Turn the result into what a version 1 install left behind.
    spaex_dir = consumer / ".spaex"
    (spaex_dir / "constitution.md").write_text(_V1_CONSTITUTION, encoding="utf-8")
    (spaex_dir / "decisions.json").unlink()
    (spaex_dir / "clarifications.json").write_text(_V1_CLARIFICATIONS, encoding="utf-8")
    (spaex_dir / ".stale").write_text("stale marker of version 1\n", encoding="utf-8")
    stub_check.calls = 0
    monkeypatch.setenv("SPAEX_STATE", str(state_root))

    def install() -> int:
        return install_cli.run(SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0))

    def snapshot() -> dict[str, bytes]:
        return {
            str(p.relative_to(consumer)): p.read_bytes()
            for p in sorted(consumer.rglob("*"))
            if p.is_file()
            and p.name != "composer.log"
            # scratch of an aborted behavior pass; it is not a tracked file
            and ".constitution.d.staging" not in p.parts
        }

    return SimpleNamespace(consumer=consumer, install=install, snapshot=snapshot)


def _contradiction(stub: StubCheck) -> None:
    stub.factory = lambda fragments: [
        make_finding(
            fragments,
            "contradiction",
            (f"{_TABS}/tabs", 2, 2),
            (f"{_SPACES}/spaces", 2, 2),
        )
    ]


def test_check_reports_the_old_format_before_the_install(
    v1_repo: SimpleNamespace, stub_check: StubCheck, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    rc = main(["--repo-root", str(v1_repo.consumer), "constitution", "build", "--check"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "format version 1" in out
    assert stub_check.calls == 0


def test_one_install_replaces_the_file_removes_legacy_files_and_asks_again(
    v1_repo: SimpleNamespace, stub_check: StubCheck, operator: Operator
) -> None:
    _contradiction(stub_check)
    operator.default = Choice(kind="keep", kept=0)
    spaex_dir = v1_repo.consumer / ".spaex"

    assert v1_repo.install() == 0

    assert stub_check.calls == 1
    assert len(operator.asked) == 1, "old answers are not reused as decisions"
    text = (spaex_dir / "constitution.md").read_text(encoding="utf-8")
    assert text.split("\n", 1)[0].endswith('version="2" -->')
    assert f'<!-- spaex-fragment id="{_TABS}/tabs" -->' in text
    assert "intro\n**MUST** always use tabs.\noutro\n" in text
    assert f'<!-- spaex-excluded kept="{_TABS}/tabs:2-2"' in text
    assert "_[from `" not in text, "no clause-style provenance is left"
    assert not (spaex_dir / "clarifications.json").exists()
    assert not (spaex_dir / ".stale").exists()
    assert (spaex_dir / "decisions.json").exists()


def test_a_second_install_changes_nothing(
    v1_repo: SimpleNamespace, stub_check: StubCheck, operator: Operator
) -> None:
    _contradiction(stub_check)
    operator.default = Choice(kind="keep", kept=0)
    assert v1_repo.install() == 0
    after_first = v1_repo.snapshot()
    calls = stub_check.calls

    assert v1_repo.install() == 0

    assert v1_repo.snapshot() == after_first
    assert stub_check.calls == calls
    assert len(operator.asked) == 1


def test_check_is_green_after_the_move(
    v1_repo: SimpleNamespace,
    stub_check: StubCheck,
    operator: Operator,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub_check.factory = lambda fragments: []
    assert v1_repo.install() == 0
    capsys.readouterr()

    rc = main(["--repo-root", str(v1_repo.consumer), "constitution", "build", "--check"])
    assert rc == 0
    assert "is current" in capsys.readouterr().out


def test_without_an_operator_the_move_stops_and_changes_nothing(
    v1_repo: SimpleNamespace, stub_check: StubCheck
) -> None:
    """The findings must be asked; with no way to ask, the v1 files stay exactly as they were."""
    import io

    _contradiction(stub_check)
    before = v1_repo.snapshot()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("sys.stdin", io.StringIO(""))
        with pytest.raises(HaexError) as caught:
            v1_repo.install()
    assert caught.value.exit_code == 21
    assert v1_repo.snapshot() == before
