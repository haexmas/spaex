"""Rollback coverage for the behavior artifact publication boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.behavior import orchestrate
from spaex.behavior.composer.clarifications import ClarificationsStore
from spaex.behavior.composer.invoke import ComposedShape


def _composed_body() -> str:
    return (
        '<!-- spaex-composed:source_hash="' + "a" * 64 + '" '
        'build_input_hash="' + "b" * 64 + '" version="1" -->\n'
        "# spaex Behavior Harness\n"
    )


def _prepare_publication(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    spaex_dir = repo / ".spaex"
    target = spaex_dir / "constitution.d"
    target.mkdir(parents=True)
    (target / "old.md").write_text("old fragment", encoding="utf-8")
    (repo / ".spaex/constitution.md").write_text("old composed", encoding="utf-8")
    clarifications = spaex_dir / "clarifications.json"
    clarifications.write_text("old clarifications", encoding="utf-8")
    staging = spaex_dir / orchestrate.STAGING_DIRNAME
    staging.mkdir()
    (staging / "new.md").write_text("new fragment", encoding="utf-8")
    return repo, target, staging, clarifications


def test_composed_publication_restores_all_artifacts_on_save_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, target, staging, clarifications = _prepare_publication(tmp_path)

    def fail_save(*_args, **_kwargs):
        raise OSError("simulated clarification write failure")

    monkeypatch.setattr(orchestrate, "save", fail_save)
    with pytest.raises(OSError, match="simulated clarification write failure"):
        orchestrate._commit_behavior_artifacts(
            repo_root=repo,
            staging=staging,
            target=target,
            prev=repo / ".spaex" / orchestrate.PREV_DIRNAME,
            composed=ComposedShape(body=_composed_body()),
            expected_source_hash="a" * 64,
            expected_build_input_hash="b" * 64,
            clarifications_path=clarifications,
            clarifications=ClarificationsStore(),
            save_clarifications=True,
        )

    assert (target / "old.md").read_text(encoding="utf-8") == "old fragment"
    assert (repo / ".spaex/constitution.md").read_text(encoding="utf-8") == "old composed"
    assert clarifications.read_text(encoding="utf-8") == "old clarifications"


def test_empty_publication_restores_files_when_target_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, target, staging, _clarifications = _prepare_publication(tmp_path)

    def fail_clear(_target: Path):
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(orchestrate, "_clear_target", fail_clear)
    with pytest.raises(OSError, match="simulated cleanup failure"):
        orchestrate._commit_behavior_artifacts(
            repo_root=repo,
            staging=staging,
            target=target,
            prev=repo / ".spaex" / orchestrate.PREV_DIRNAME,
            remove_spaex_md=True,
        )

    assert (target / "old.md").read_text(encoding="utf-8") == "old fragment"
    assert (repo / ".spaex/constitution.md").read_text(encoding="utf-8") == "old composed"
