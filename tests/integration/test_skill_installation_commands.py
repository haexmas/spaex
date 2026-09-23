"""Integration tests for Spec 018 US3 (T015).

Covers: normal `spaex install` reporting pending references without
installing, and `spaex skills install`/`spaex skills configure` covering
disabled mode, prompt cancellation/EOF, non-interactive refusal, managed
execution, persistence failure before adapter launch, configure without
removal, and adapter failure.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import add as add_cli
from spaex.cli import install as install_cli
from spaex.cli import skills as skills_cli
from spaex.git.cache import clone_dir
from spaex.util.errors import (
    InteractiveSelectionUnavailableError,
    SkillAdapterFailedError,
    SkillAdapterUnavailableError,
    SkillInstallationCancelledError,
    SkillInstallationPersistError,
)

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


@pytest.fixture
def consumer_with_pending_skill(tmp_path, monkeypatch):
    """Consumer repo with one adopted molecule declaring one external skill."""
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
    return consumer


class _TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _install_args(consumer: Path) -> SimpleNamespace:
    return SimpleNamespace(repo_root=str(consumer))


def _write_fake_adapter(bin_dir: Path, name: str, *, exit_code: int, output_path: Path) -> None:
    script = bin_dir / name
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"data = json.loads(Path(os.environ['SPAEX_MOLECULE_MANIFEST']).read_text())\n"
        f"Path({str(output_path)!r}).write_text(json.dumps(data.get('external_skills', [])))\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def test_normal_install_reports_pending_without_installing(
    consumer_with_pending_skill, capsys
) -> None:
    rc = install_cli.run(_install_args(consumer_with_pending_skill))
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 external skill reference(s) pending across 1 molecule(s)" in out
    assert "spaex skills install" in out
    manifest = json.loads((consumer_with_pending_skill / ".spaex/manifest.json").read_text())
    assert "skill_installation" not in manifest


def test_skills_install_with_no_pending_skills_is_a_no_op(tmp_path, capsys) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex").mkdir()
    (consumer / ".spaex/manifest.json").write_text(
        json.dumps({"spaex_version": "4", "identity": "com.example.consumer", "compounds": []})
    )
    rc = skills_cli.run_install(_install_args(consumer))
    assert rc == 0
    assert "no external skill references are pending" in capsys.readouterr().out


def test_disabled_policy_skips_install_without_adapter(
    consumer_with_pending_skill, monkeypatch, capsys
) -> None:
    manifest_path = consumer_with_pending_skill / ".spaex/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["skill_installation"] = {"mode": "disabled"}
    manifest_path.write_text(json.dumps(manifest))

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    rc = skills_cli.run_install(_install_args(consumer_with_pending_skill))
    assert rc == 0
    assert "disabled" in capsys.readouterr().out


def test_non_interactive_refusal_without_persisted_policy(
    consumer_with_pending_skill, monkeypatch
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(InteractiveSelectionUnavailableError):
        skills_cli.run_install(_install_args(consumer_with_pending_skill))
    manifest = json.loads((consumer_with_pending_skill / ".spaex/manifest.json").read_text())
    assert "skill_installation" not in manifest


def test_prompt_eof_cancels_without_writing(consumer_with_pending_skill, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", _TTYStringIO(""))
    with pytest.raises(SkillInstallationCancelledError):
        skills_cli.run_install(_install_args(consumer_with_pending_skill))
    manifest = json.loads((consumer_with_pending_skill / ".spaex/manifest.json").read_text())
    assert "skill_installation" not in manifest


def test_managed_policy_invokes_adapter_with_molecule_manifest(
    consumer_with_pending_skill, monkeypatch, tmp_path, capsys
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    output_path = tmp_path / "adapter-output.json"
    _write_fake_adapter(bin_dir, "fake-adapter", exit_code=0, output_path=output_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    manifest_path = consumer_with_pending_skill / ".spaex/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["skill_installation"] = {
        "mode": "managed",
        "adapter": "fake-adapter",
        "scope": "project",
        "agents": ["codex"],
    }
    manifest_path.write_text(json.dumps(manifest))

    rc = skills_cli.run_install(_install_args(consumer_with_pending_skill))
    assert rc == 0
    out = capsys.readouterr().out
    assert f"installed external skill for {_MOLECULE_ID} via fake-adapter" in out

    received = json.loads(output_path.read_text())
    assert received == [
        {"repository": _SKILL_REPO, "revision": _SKILL_REVISION, "path": _SKILL_PATH}
    ]


def test_adapter_failure_raises_and_leaves_manifest_unaffected(
    consumer_with_pending_skill, monkeypatch, tmp_path
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    output_path = tmp_path / "adapter-output.json"
    _write_fake_adapter(bin_dir, "failing-adapter", exit_code=1, output_path=output_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    manifest_path = consumer_with_pending_skill / ".spaex/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["skill_installation"] = {
        "mode": "managed",
        "adapter": "failing-adapter",
        "scope": "project",
        "agents": ["codex"],
    }
    manifest_path.write_text(json.dumps(manifest))
    before_install_lock = (consumer_with_pending_skill / ".spaex/install.lock").read_bytes()

    with pytest.raises(SkillAdapterFailedError):
        skills_cli.run_install(_install_args(consumer_with_pending_skill))

    assert (consumer_with_pending_skill / ".spaex/install.lock").read_bytes() == before_install_lock


def test_unavailable_adapter_raises_without_launching(
    consumer_with_pending_skill, monkeypatch
) -> None:
    manifest_path = consumer_with_pending_skill / ".spaex/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["skill_installation"] = {
        "mode": "managed",
        "adapter": "definitely-not-a-real-adapter-binary",
        "scope": "project",
        "agents": ["codex"],
    }
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SkillAdapterUnavailableError):
        skills_cli.run_install(_install_args(consumer_with_pending_skill))


def test_persistence_failure_prevents_adapter_launch(
    consumer_with_pending_skill, monkeypatch, tmp_path
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    output_path = tmp_path / "adapter-output.json"
    _write_fake_adapter(bin_dir, "fake-adapter", exit_code=0, output_path=output_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(sys, "stdin", _TTYStringIO("managed\nfake-adapter\nproject\ncodex\n"))

    def _boom(target, data):
        raise OSError("disk full")

    monkeypatch.setattr(skills_cli.atomic, "write_replace", _boom)

    with pytest.raises(SkillInstallationPersistError):
        skills_cli.run_install(_install_args(consumer_with_pending_skill))
    assert not output_path.exists()


def test_prompt_flow_persists_and_installs_in_one_invocation(
    consumer_with_pending_skill, monkeypatch, tmp_path, capsys
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    output_path = tmp_path / "adapter-output.json"
    _write_fake_adapter(bin_dir, "fake-adapter", exit_code=0, output_path=output_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(sys, "stdin", _TTYStringIO("managed\nfake-adapter\nproject\ncodex\n"))

    rc = skills_cli.run_install(_install_args(consumer_with_pending_skill))
    assert rc == 0
    assert output_path.exists()

    manifest = json.loads((consumer_with_pending_skill / ".spaex/manifest.json").read_text())
    assert manifest["skill_installation"] == {
        "mode": "managed",
        "adapter": "fake-adapter",
        "scope": "project",
        "agents": ["codex"],
    }


def test_configure_persists_disabled_without_removing_pending_reference(
    consumer_with_pending_skill, monkeypatch
) -> None:
    monkeypatch.setattr(sys, "stdin", _TTYStringIO("disabled\n"))
    rc = skills_cli.run_configure(_install_args(consumer_with_pending_skill))
    assert rc == 0

    manifest = json.loads((consumer_with_pending_skill / ".spaex/manifest.json").read_text())
    assert manifest["skill_installation"] == {"mode": "disabled"}
    # Retracting nothing: the adopted compound/molecule is untouched.
    assert manifest["compounds"][0]["molecules"] == [_MOLECULE_ID]


def test_configure_never_invokes_an_adapter(
    consumer_with_pending_skill, monkeypatch, tmp_path, capsys
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    output_path = tmp_path / "adapter-output.json"
    _write_fake_adapter(bin_dir, "fake-adapter", exit_code=0, output_path=output_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(sys, "stdin", _TTYStringIO("managed\nfake-adapter\nproject\ncodex\n"))

    rc = skills_cli.run_configure(_install_args(consumer_with_pending_skill))
    assert rc == 0
    assert not output_path.exists()


def test_configure_without_tty_fails_without_writing(
    consumer_with_pending_skill, monkeypatch
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(InteractiveSelectionUnavailableError):
        skills_cli.run_configure(_install_args(consumer_with_pending_skill))
    manifest = json.loads((consumer_with_pending_skill / ".spaex/manifest.json").read_text())
    assert "skill_installation" not in manifest
