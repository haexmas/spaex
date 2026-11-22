"""Rollback coverage for the behavior artifact publication boundary (Spec 030)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from spaex.behavior import orchestrate
from spaex.behavior.composer.failure import ComposerFailureCategory, raise_for
from spaex.behavior.decisions import DecisionStore
from spaex.behavior.fragment import PROJECT_SCOPE, BehaviorFragment
from spaex.util.errors import HaexError

from ..conftest import Operator, StubCheck

OLD_FILES = {
    "constitution.md": "old composed",
    "decisions.json": "old decisions",
    "clarifications.json": "old clarifications",
    ".stale": "old stale marker",
}


def _prepare_publication(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    spaex_dir = repo / ".spaex"
    target = spaex_dir / "constitution.d"
    target.mkdir(parents=True)
    (target / "old.md").write_text("old fragment", encoding="utf-8")
    for name, text in OLD_FILES.items():
        (spaex_dir / name).write_text(text, encoding="utf-8")
    staging = spaex_dir / orchestrate.STAGING_DIRNAME
    staging.mkdir()
    (staging / "new.md").write_text("new fragment", encoding="utf-8")
    return repo, spaex_dir, target, staging


def _assert_untouched(spaex_dir: Path, target: Path) -> None:
    assert (target / "old.md").read_text(encoding="utf-8") == "old fragment"
    assert not (target / "new.md").exists()
    for name, text in OLD_FILES.items():
        assert (spaex_dir / name).read_text(encoding="utf-8") == text, name


def _commit(repo: Path, target: Path, staging: Path, **kwargs: object) -> None:
    orchestrate._commit_behavior_artifacts(
        repo_root=repo,
        staging=staging,
        target=target,
        prev=repo / ".spaex" / orchestrate.PREV_DIRNAME,
        **kwargs,  # type: ignore[arg-type]
    )


def test_successful_commit_publishes_everything_and_removes_the_legacy_files(
    tmp_path: Path,
) -> None:
    repo, spaex_dir, target, staging = _prepare_publication(tmp_path)

    _commit(repo, target, staging, rendered="new composed\n", decisions_store=DecisionStore())

    assert (spaex_dir / "constitution.md").read_text(encoding="utf-8") == "new composed\n"
    assert (spaex_dir / "decisions.json").exists()
    assert (spaex_dir / "decisions.json").read_text(encoding="utf-8") != "old decisions"
    assert (target / "new.md").read_text(encoding="utf-8") == "new fragment"
    for legacy in orchestrate.LEGACY_FILENAMES:
        assert not (spaex_dir / legacy).exists(), legacy
    assert not list(spaex_dir.glob(".behavior-backup-*"))
    assert not (spaex_dir / orchestrate.PREV_DIRNAME).exists()


def test_composed_publication_restores_all_artifacts_on_decisions_save_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, spaex_dir, target, staging = _prepare_publication(tmp_path)

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated decisions write failure")

    monkeypatch.setattr(orchestrate, "save", fail_save)
    with pytest.raises(OSError, match="simulated decisions write failure"):
        _commit(repo, target, staging, rendered="new composed\n", decisions_store=DecisionStore())

    _assert_untouched(spaex_dir, target)
    assert not list(spaex_dir.glob(".behavior-backup-*"))


def test_composed_publication_restores_the_legacy_files_when_their_removal_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, spaex_dir, target, staging = _prepare_publication(tmp_path)
    real_remove = orchestrate.remove_if_exists

    def remove_failing_on_stale(repo_root: Path, path: Path | None = None) -> bool:
        if path is not None and path.name == ".stale":
            raise OSError("simulated legacy removal failure")
        return real_remove(repo_root, path)

    monkeypatch.setattr(orchestrate, "remove_if_exists", remove_failing_on_stale)
    with pytest.raises(OSError, match="simulated legacy removal failure"):
        _commit(repo, target, staging, rendered="new composed\n", decisions_store=DecisionStore())

    _assert_untouched(spaex_dir, target)


def test_empty_publication_restores_files_when_target_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, spaex_dir, target, staging = _prepare_publication(tmp_path)

    def fail_clear(_target: Path) -> None:
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(orchestrate, "_clear_target", fail_clear)
    with pytest.raises(OSError, match="simulated cleanup failure"):
        _commit(repo, target, staging, remove_spaex_md=True)

    _assert_untouched(spaex_dir, target)


def test_empty_publication_removes_constitution_decisions_and_legacy_files(
    tmp_path: Path,
) -> None:
    repo, spaex_dir, target, staging = _prepare_publication(tmp_path)

    _commit(repo, target, staging, remove_spaex_md=True)

    for name in OLD_FILES:
        assert not (spaex_dir / name).exists(), name
    assert not target.exists()


def _fragment(fragment_id: str, body: str) -> BehaviorFragment:
    raw = (
        f"---\nid: {fragment_id}\nkind: constitution_fragment\n"
        f"atom_source: pkg.{fragment_id}\n---\n{body}"
    ).encode()
    return BehaviorFragment.from_bytes(
        raw, molecule_id=PROJECT_SCOPE, path=f"{PROJECT_SCOPE}/{fragment_id}.md"
    )


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_run_publishes_fragments_text_and_decisions_in_one_go(
    tmp_path: Path, stub_check: StubCheck, operator: Operator
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".spaex").mkdir()
    (repo / ".spaex" / "clarifications.json").write_text("{}", encoding="utf-8")

    outcome = orchestrate.run(
        repo_root=repo,
        state_root=tmp_path / "state",
        resolved=[],
        project_local=[_fragment("one", "first rule\n"), _fragment("two", "second rule\n")],
    )

    assert outcome.published and outcome.fragment_count == 2
    assert outcome.skipped_check is False
    assert stub_check.calls == 1
    text = (repo / ".spaex" / "constitution.md").read_text(encoding="utf-8")
    assert "first rule\n" in text and "second rule\n" in text
    assert (repo / ".spaex" / "decisions.json").exists()
    assert not (repo / ".spaex" / "clarifications.json").exists()
    assert (repo / ".spaex" / "constitution.d" / PROJECT_SCOPE / "one.md").exists()


def test_run_leaves_every_file_unchanged_when_the_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operator: Operator
) -> None:
    repo = tmp_path / "repo"
    spaex_dir = repo / ".spaex"
    (spaex_dir / "constitution.d").mkdir(parents=True)
    (spaex_dir / "constitution.d" / "old.md").write_text("old fragment", encoding="utf-8")
    for name, text in OLD_FILES.items():
        (spaex_dir / name).write_text(text, encoding="utf-8")
    (spaex_dir / "decisions.json").write_text(
        '{"schema_version": 1, "decisions": {}}\n', encoding="utf-8"
    )
    before = _snapshot(spaex_dir)

    def failing_check(*_args: object, **_kwargs: object) -> None:
        raise_for(ComposerFailureCategory.RUNTIME_ERROR, "simulated runtime failure")

    monkeypatch.setattr(orchestrate, "check_fragments", failing_check)
    with pytest.raises(HaexError, match="simulated runtime failure"):
        orchestrate.run(
            repo_root=repo,
            state_root=tmp_path / "state",
            resolved=[],
            project_local=[_fragment("one", "first rule\n")],
        )

    # The staging tree and composer.log are scratch/diagnostic files, not tracked artifacts.
    after = {
        name: digest
        for name, digest in _snapshot(spaex_dir).items()
        if not name.startswith(orchestrate.STAGING_DIRNAME) and name != "composer.log"
    }
    assert after == before
