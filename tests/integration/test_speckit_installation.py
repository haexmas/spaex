from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

import pytest

from spaex.constitution.resolve import ResolvedMolecule
from spaex.integrations.speckit import prepare_install
from spaex.model.install_lock import InstallLock, MoleculeEntry
from spaex.model.molecule_manifest import MoleculeManifest


@pytest.mark.parametrize("provisioned", [False, True])
def test_prepare_install_delegates_selected_agent_to_official_cli(
    tmp_path: Path, provisioned: bool
) -> None:
    calls = tmp_path / "calls.log"
    # An already-initialized Spec Kit project, so no `specify init` runs.
    (tmp_path / ".specify").mkdir(exist_ok=True)
    executable = tmp_path / "fake_specify.py"
    executable.write_text(
        f"""from pathlib import Path
import sys

CALLS = Path({str(calls)!r})
args = sys.argv[1:]
CALLS.open("a", encoding="utf-8").write(" ".join(args) + "\\n")
if args == ["version"]:
    print("CLI Version 0.8.1.dev0")
    raise SystemExit(0)
if args[:2] == ["integration", "list"]:
    sys.stdout.buffer.write(
        "│ claude │ Claude Code │\\n│ codex │ Codex CLI │\\n".encode("utf-8")
    )
    raise SystemExit(0)
if args[:2] == ["integration", "install"]:
    if args[2] == "claude":
        skills = Path.cwd() / ".claude" / "skills"
    elif args[2] == "codex":
        skills = Path.cwd() / ".agents" / "skills"
    else:
        raise SystemExit(2)
    skills.mkdir(parents=True, exist_ok=True)
    (skills / "specify.md").touch()
    raise SystemExit(0)
raise SystemExit(2)
""",
        encoding="utf-8",
    )

    manifest = MoleculeManifest.from_json(
        json.dumps(
            {
                "spaex_version": "4",
                "id": "com.example.publisher.speckit",
                "version": "1.0.0",
                "priority": 1,
                "atoms": {},
                "speckit": {
                    "version_constraint": ">=0.8.1",
                    **(
                        {"cli": {"package": "specify-cli", "version": "0.8.1"}}
                        if provisioned
                        else {}
                    ),
                    "integrations": {
                        "claude": {"integration_options": "--skills"},
                        "codex": {"integration_options": "--skills"},
                    },
                },
            }
        ).encode()
    )
    resolved = [
        ResolvedMolecule(
            molecule_id=manifest.id,
            source_url="https://example.com/publisher",
            revision="a" * 40,
            repo_dir=tmp_path,
            molecule_path="molecule",
            install_hook=None,
            effective_priority=1,
            molecule_manifest=manifest,
            cache_dir=tmp_path,
        )
    ]

    records = prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=None,
        explicit_selection="codex",
        executable=(sys.executable, str(executable)),
    )

    assert (tmp_path / ".agents/skills/specify.md").exists()
    assert not (tmp_path / ".claude/skills/specify.md").exists()
    assert records[manifest.id].outcomes == {"codex": "installed"}
    assert "integration install codex --integration-options=--skills" in calls.read_text()

    lock = InstallLock(
        spaex_version="4",
        generation_id="g_20260914T120000Z_abcd",
        molecules=(
            MoleculeEntry(
                id=manifest.id,
                source="https://example.com/publisher",
                revision="a" * 40,
                paths=(),
                speckit=records[manifest.id],
            ),
        ),
    )
    prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=lock,
        explicit_selection=None,
        executable=(sys.executable, str(executable)),
    )
    assert (
        calls.read_text()
        .splitlines()
        .count("integration install codex --integration-options=--skills")
        == 1
    )

    prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=lock,
        explicit_selection="all",
        stdin=StringIO("all\n"),
        executable=(sys.executable, str(executable)),
    )
    assert (tmp_path / ".claude/skills/specify.md").exists()
