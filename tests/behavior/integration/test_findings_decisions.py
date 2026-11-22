"""Findings of the check are asked, decided and applied by commenting out (Spec 030 T015).

Two molecules contradict each other (`tabs` / `spaces`), a third repeats the
first (`tabs-copy`). The check is stubbed to report them; the operator is
stubbed too, except where the real prompt must refuse on a non-interactive
terminal. The composed file must keep every line, with the passage that was
not kept commented out, and the decision must make the output reproducible.
"""

from __future__ import annotations

import io
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior.composer.failure import ComposerFailureCategory, raise_for
from spaex.behavior.decisions import Choice
from spaex.cli import install as install_cli
from spaex.util.errors import HaexError

from ..conftest import Operator, StubCheck, make_finding

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")

_TABS = "com.example.publisher.tabs"
_SPACES = "com.example.publisher.spaces"
_COPY = "com.example.publisher.tabs-copy"
_TABS_RULE = "**MUST** always use tabs for indentation."
_SPACES_RULE = "**MUST** never use tabs for indentation."


def _fragment(fragment_id: str, lines: list[str]) -> str:
    return (
        f"---\nid: {fragment_id}\nkind: constitution_fragment\n"
        f"atom_source: pkg.{fragment_id}\n---\n" + "\n".join(lines) + "\n"
    )


def _molecule(path: str, fragment_id: str, lines: list[str]) -> dict:
    return {
        "path": path,
        "version": "1.0.0",
        "atoms": {"behavior": ["rule.md"]},
        "files": {"rule.md": _fragment(fragment_id, lines)},
    }


def _tabs_lines(intro: str = "intro of tabs", rule: str = _TABS_RULE) -> list[str]:
    return [intro, rule, "outro of tabs"]


@pytest.fixture
def scene(tmp_path: Path, haex_add_helpers, monkeypatch, git_binary: str) -> SimpleNamespace:
    helpers = haex_add_helpers
    canonical, head, state_root = helpers["make_publisher"](
        tmp_path,
        {
            _TABS: _molecule("tabs", "tabs", _tabs_lines()),
            _SPACES: _molecule("spaces", "spaces", ["alpha", _SPACES_RULE, "omega"]),
            _COPY: _molecule("copy", "tabs-copy", ["copy intro", _TABS_RULE, "copy outro"]),
        },
    )
    consumer = helpers["make_consumer"](tmp_path)
    working = tmp_path / "publisher-working"

    def add(ids: str) -> int:
        return helpers["run_add"](
            consumer, state_root, monkeypatch, source_url=canonical, revision=head, molecule_ids=ids
        )

    def remove(ids: str) -> int:
        return helpers["run_remove"](consumer, state_root, monkeypatch, ids)

    def publish(path: str, fragment_id: str, lines: list[str]) -> None:
        """Commit a new version of one fragment and re-pin the consumer to it."""
        (working / path / "rule.md").write_text(_fragment(fragment_id, lines))
        helpers["git"](working, "add", ".")
        helpers["git"](working, "commit", "-q", "-m", f"edit {fragment_id}")
        new_head = helpers["git"](working, "rev-parse", "HEAD")
        clone = helpers["clone_dir"](state_root, canonical)
        helpers["git"](clone, "fetch", "-q", str(working), "+main:main")
        manifest = consumer / ".spaex/manifest.json"
        data = json.loads(manifest.read_text())
        for compound in data["compounds"]:
            compound["revision"] = new_head
        manifest.write_text(json.dumps(data, indent=2))

    def install() -> int:
        monkeypatch.setenv("SPAEX_STATE", str(state_root))
        return install_cli.run(SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0))

    def snapshot() -> dict[str, bytes]:
        return {
            str(p.relative_to(consumer)): p.read_bytes()
            for p in sorted(consumer.rglob("*"))
            if p.is_file() and p.name != "composer.log"
        }

    return SimpleNamespace(
        consumer=consumer,
        add=add,
        remove=remove,
        publish=publish,
        install=install,
        snapshot=snapshot,
        composed=lambda: (consumer / ".spaex/constitution.md").read_text(encoding="utf-8"),
        decisions=lambda: json.loads((consumer / ".spaex/decisions.json").read_text("utf-8")),
    )


def _report(first: str, second: str, kind: str) -> Callable:
    """A stub check that reports `first` against `second` when both fragments exist.

    Both passages are line 2 of their fragment (the rule sits between an intro and an outro).
    """

    def factory(fragments):
        ids = {f.scoped_id for f in fragments}
        if (
            f"{first}/{first.rsplit('.', 1)[1]}" in ids
            and f"{second}/{second.rsplit('.', 1)[1]}" in ids
        ):
            return [
                make_finding(
                    fragments,
                    kind,
                    (f"{first}/{first.rsplit('.', 1)[1]}", 2, 2),
                    (f"{second}/{second.rsplit('.', 1)[1]}", 2, 2),
                    summary=f"{kind} between {first} and {second}",
                )
            ]
        return []

    return factory


def _failure(call: Callable[[], int]) -> HaexError:
    """The error a failing `add`/`install` raises (`add` wraps the install's own error)."""
    with pytest.raises(HaexError) as caught:
        call()
    return caught.value


def _install_exit_code(error: HaexError) -> int:
    """Exit code of the install behind an `add` failure (or the error's own code)."""
    return int(error.context.get("install_exit_code", error.exit_code))


def test_a_contradiction_is_asked_with_both_passages_and_the_other_one_is_commented_out(
    scene: SimpleNamespace, stub_check: StubCheck, operator: Operator
) -> None:
    stub_check.factory = _report(_TABS, _SPACES, "contradiction")
    operator.default = Choice(kind="keep", kept=0)

    assert scene.add(_TABS) == 0
    assert operator.asked == []
    assert scene.add(_SPACES) == 0

    (finding,) = operator.asked
    assert finding.kind == "contradiction"
    assert [(p.scoped_id, p.text) for p in finding.passages] == [
        (f"{_TABS}/tabs", _TABS_RULE),
        (f"{_SPACES}/spaces", _SPACES_RULE),
    ]
    text = scene.composed()
    decision_key = next(iter(scene.decisions()["decisions"]))[:12]
    assert (
        f'<!-- spaex-excluded kept="{_TABS}/tabs:2-2" decision="{decision_key}"\n'
        f"{_SPACES_RULE}\n-->"
    ) in text
    # the kept passage and everything around the excluded one is untouched
    assert f"intro of tabs\n{_TABS_RULE}\noutro of tabs\n" in text
    assert "alpha\n<!-- spaex-excluded" in text
    assert "-->\nomega\n" in text


def test_keeping_the_second_passage_comments_out_the_first(
    scene: SimpleNamespace, stub_check: StubCheck, operator: Operator
) -> None:
    stub_check.factory = _report(_TABS, _SPACES, "contradiction")
    operator.default = Choice(kind="keep", kept=1)

    assert scene.add(f"{_TABS},{_SPACES}") == 0

    text = scene.composed()
    assert f'kept="{_SPACES}/spaces:2-2"' in text
    assert f'<!-- spaex-excluded kept="{_SPACES}/spaces:2-2"' in text
    assert f"{_TABS_RULE}\n-->" in text
    assert f"alpha\n{_SPACES_RULE}\nomega\n" in text


def test_a_duplicate_is_asked_like_a_contradiction(
    scene: SimpleNamespace, stub_check: StubCheck, operator: Operator
) -> None:
    stub_check.factory = _report(_TABS, _COPY, "duplicate")
    operator.default = Choice(kind="keep", kept=0)

    assert scene.add(f"{_TABS},{_COPY}") == 0

    (finding,) = operator.asked
    assert finding.kind == "duplicate"
    text = scene.composed()
    assert f'<!-- spaex-excluded kept="{_TABS}/tabs:2-2"' in text
    assert "copy intro\n<!-- spaex-excluded" in text


def test_keeping_all_comments_out_nothing_and_is_not_asked_again(
    scene: SimpleNamespace, stub_check: StubCheck, operator: Operator
) -> None:
    stub_check.factory = _report(_TABS, _SPACES, "contradiction")
    operator.default = Choice(kind="keep_all")
    assert scene.add(f"{_TABS},{_SPACES}") == 0

    text = scene.composed()
    assert "<!-- spaex-excluded" not in text
    assert scene.decisions()["decisions"]
    before = scene.snapshot()
    calls = stub_check.calls

    assert scene.install() == 0
    assert len(operator.asked) == 1, "the finding is not asked again"
    assert stub_check.calls == calls, "nothing changed, so no new check"
    assert scene.snapshot() == before


def test_a_decision_makes_the_output_reproducible_without_the_model(
    scene: SimpleNamespace, stub_check: StubCheck, operator: Operator
) -> None:
    stub_check.factory = _report(_TABS, _SPACES, "contradiction")
    operator.default = Choice(kind="keep", kept=0)
    assert scene.add(f"{_TABS},{_SPACES}") == 0
    first = scene.composed()
    calls = stub_check.calls

    (scene.consumer / ".spaex/constitution.md").unlink()
    assert scene.install() == 0

    assert scene.composed() == first
    assert stub_check.calls == calls
    assert len(operator.asked) == 1


def test_an_unrelated_edit_keeps_the_decision_but_an_edited_passage_asks_again(
    scene: SimpleNamespace, stub_check: StubCheck, operator: Operator
) -> None:
    stub_check.factory = _report(_TABS, _SPACES, "contradiction")
    operator.default = Choice(kind="keep", kept=0)
    assert scene.add(f"{_TABS},{_SPACES}") == 0
    calls = stub_check.calls
    assert len(operator.asked) == 1

    # another line of the same fragment changes: a new check runs, the finding is the same
    scene.publish("tabs", "tabs", _tabs_lines(intro="a different intro"))
    assert scene.install() == 0
    assert stub_check.calls == calls + 1
    assert len(operator.asked) == 1, "the passage text is unchanged, so its decision holds"
    assert "a different intro" in scene.composed()
    assert f'kept="{_TABS}/tabs:2-2"' in scene.composed()

    # the passage itself changes: the decision no longer applies and the finding is asked again
    scene.publish("tabs", "tabs", _tabs_lines(rule="**MUST** use tabs wherever possible."))
    assert scene.install() == 0
    assert len(operator.asked) == 2
    assert operator.asked[1].passages[0].text == "**MUST** use tabs wherever possible."
    assert len(scene.decisions()["decisions"]) == 1, "the outdated decision is dropped"


def test_removing_a_molecule_drops_its_decision_and_exclusion(
    scene: SimpleNamespace, stub_check: StubCheck, operator: Operator
) -> None:
    stub_check.factory = _report(_TABS, _SPACES, "contradiction")
    operator.default = Choice(kind="keep", kept=0)
    assert scene.add(f"{_TABS},{_SPACES}") == 0

    assert scene.remove(_SPACES) == 0

    text = scene.composed()
    assert "<!-- spaex-excluded" not in text
    assert _SPACES_RULE not in text
    assert scene.decisions()["decisions"] == {}


def test_without_an_operator_the_install_stops_and_changes_nothing(
    scene: SimpleNamespace, stub_check: StubCheck, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_check.factory = _report(_TABS, _SPACES, "contradiction")
    assert scene.add(_TABS) == 0
    before = scene.snapshot()

    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # not a TTY: the real prompt refuses
    assert _install_exit_code(_failure(lambda: scene.add(_SPACES))) == 21

    assert scene.snapshot() == before


def test_an_unusable_check_answer_stops_the_install_and_changes_nothing(
    scene: SimpleNamespace, stub_check: StubCheck
) -> None:
    assert scene.add(_TABS) == 0
    before = scene.snapshot()

    def unusable(_fragments):
        raise_for(ComposerFailureCategory.INVALID_OUTPUT, "the check answered nonsense")

    stub_check.factory = unusable
    assert _install_exit_code(_failure(lambda: scene.add(_SPACES))) == 32

    assert scene.snapshot() == before


def test_the_decision_file_records_what_was_asked_and_answered(
    scene: SimpleNamespace, stub_check: StubCheck, operator: Operator
) -> None:
    stub_check.factory = _report(_TABS, _SPACES, "contradiction")
    operator.default = Choice(kind="keep", kept=0)
    assert scene.add(f"{_TABS},{_SPACES}") == 0

    data = scene.decisions()
    assert data["schema_version"] == 1
    assert set(data["checked"]) == {"source_hash", "prompt_hash"}
    ((key, decision),) = data["decisions"].items()
    assert len(key) == 64
    assert decision["kind"] == "contradiction"
    assert decision["summary"] == f"contradiction between {_TABS} and {_SPACES}"
    assert [(p["scoped_id"], p["text"]) for p in decision["passages"]] == [
        (f"{_TABS}/tabs", _TABS_RULE),
        (f"{_SPACES}/spaces", _SPACES_RULE),
    ]
    assert all(len(p["text_hash"]) == 64 for p in decision["passages"])
    assert decision["choice"] == {"kind": "keep", "kept": 0}
    assert decision["asked_at"] and decision["answered_at"]
