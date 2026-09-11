"""Rollback coverage for the outer install generation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import install


def test_behavior_failure_restores_previous_generation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    live = repo / ".spaex"
    live.mkdir(parents=True)
    (live / "install.lock").write_text("old generation", encoding="utf-8")
    resolved = [
        SimpleNamespace(
            molecule_manifest=SimpleNamespace(
                atoms={"behavior": ["fragment.md"]},
                constitution_fragments={},
            )
        )
    ]

    behavior_transaction = install._preserve_generation_for_behavior(repo, resolved)
    with pytest.raises(RuntimeError, match="composer failed"), behavior_transaction:
        (live / "install.lock").write_text("new generation", encoding="utf-8")
        raise RuntimeError("composer failed")

    assert (live / "install.lock").read_text(encoding="utf-8") == "old generation"
