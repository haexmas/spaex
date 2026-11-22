"""A check failure inside `orchestrate.run` leaves `.spaex` byte-unchanged (Spec 030 FR-019)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from spaex.behavior import orchestrate
from spaex.behavior.composer.failure import ComposerFailureCategory, raise_for
from spaex.behavior.fragment import PROJECT_SCOPE, BehaviorFragment
from spaex.util.errors import HaexError

_OLD = {
    "constitution.md": "old composed\n",
    "decisions.json": '{"schema_version": 1, "decisions": {}}\n',
    "clarifications.json": "old clarifications\n",
    ".stale": "old stale marker\n",
    "constitution.d/old.md": "old fragment\n",
}


def _fragment() -> BehaviorFragment:
    raw = (
        b"---\nid: rule\nkind: constitution_fragment\natom_source: pkg.rule\n---\n"
        b"Always run the tests.\n"
    )
    return BehaviorFragment.from_bytes(raw, molecule_id=PROJECT_SCOPE, path="_project/rule.md")


def _snapshot(spaex_dir: Path) -> dict[str, str]:
    """Hash every artifact; staging and the composer log are scratch, not artifacts."""
    return {
        str(path.relative_to(spaex_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(spaex_dir.rglob("*"))
        if path.is_file()
        and not path.relative_to(spaex_dir).parts[0].startswith(".constitution.d.")
        and path.name != "composer.log"
    }


@pytest.mark.parametrize(
    "category",
    [
        ComposerFailureCategory.TIMEOUT,
        ComposerFailureCategory.RUNTIME_ERROR,
        ComposerFailureCategory.INVALID_OUTPUT,
        ComposerFailureCategory.QUOTA,
        ComposerFailureCategory.NO_RUNTIME,
    ],
)
def test_check_failure_changes_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, category: ComposerFailureCategory
) -> None:
    repo = tmp_path / "repo"
    spaex_dir = repo / ".spaex"
    for name, text in _OLD.items():
        path = spaex_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    before = _snapshot(spaex_dir)

    def failing_check(*_args: object, **_kwargs: object) -> None:
        raise_for(category, f"simulated {category.value} failure")

    monkeypatch.setattr(orchestrate, "check_fragments", failing_check)
    with pytest.raises(HaexError, match="simulated"):
        orchestrate.run(
            repo_root=repo,
            state_root=tmp_path / "state",
            resolved=[],
            project_local=[_fragment()],
        )

    assert _snapshot(spaex_dir) == before
