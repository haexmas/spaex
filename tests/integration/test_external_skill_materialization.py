"""External skill references never materialize or enter install.lock.

Spec 018 T008, FR-002/FR-010/FR-011.

`atoms.constitution` (the legacy plain-file category) is used here rather
than Spec 023 behavior fragments, so this needs no Composer stub: it is a
plain file-materialization path, exactly like any other atom category.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")

_MOLECULE_ID = "com.example.publisher.with-skill"
_CANONICAL = "https://example.invalid/example/publisher-with-skill"
_SKILL_REPO = "https://github.com/example/skills-repo"
_SKILL_REVISION = "a" * 40
_SKILL_PATH = "skills/example-skill"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_molecule_with_external_skill(tmp_path: Path) -> tuple[str, Path]:
    working = tmp_path / "publisher-working"
    working.mkdir()
    _git(working, "init", "-q", "-b", "main")
    _git(working, "config", "user.email", "author@example.com")
    _git(working, "config", "user.name", "author")
    _git(working, "config", "commit.gpgsign", "false")

    (working / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "publisher": "com.example.publisher",
                "molecules": {_MOLECULE_ID: {"path": "with-skill", "version": "1.0.0"}},
            },
            indent=2,
        )
    )
    mol_dir = working / "with-skill"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOLECULE_ID,
                "version": "1.0.0",
                "priority": 100,
                "atoms": {"constitution": ["constitution.md"]},
                "external_skills": [
                    {
                        "repository": _SKILL_REPO,
                        "revision": _SKILL_REVISION,
                        "path": _SKILL_PATH,
                    }
                ],
            },
            indent=2,
        )
    )
    (mol_dir / "constitution.md").write_text("# Example Constitution\n\nBe kind.\n")

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "publish")
    sha = _git(working, "rev-parse", "HEAD")
    return sha, working


def test_external_skill_reference_is_absent_from_install_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spaex.cli import add as add_cli
    from spaex.git.cache import clone_dir

    sha, working = _publish_molecule_with_external_skill(tmp_path)

    state_root = tmp_path / "state"
    clone_target = clone_dir(state_root, _CANONICAL)
    clone_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(working, clone_target)

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex").mkdir()
    (consumer / ".spaex/manifest.json").write_text(
        json.dumps({"spaex_version": "4", "identity": "com.example.consumer", "compounds": []})
    )

    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    rc = add_cli.run(
        SimpleNamespace(
            repo_root=str(consumer),
            source_url=_CANONICAL,
            molecule_ids=_MOLECULE_ID,
            revision=sha,
            all=False,
            lock_timeout=1.0,
        )
    )
    assert rc == 0

    lock_text = (consumer / ".spaex/install.lock").read_text(encoding="utf-8")
    assert _SKILL_REPO not in lock_text
    assert _SKILL_REVISION not in lock_text
    assert _SKILL_PATH not in lock_text

    lock_data = json.loads(lock_text)
    molecule_entry = next(m for m in lock_data["molecules"] if m["id"] == _MOLECULE_ID)
    assert molecule_entry["paths"] == [".spaex/constitution.md"]
    assert not (consumer / _SKILL_PATH).exists()
