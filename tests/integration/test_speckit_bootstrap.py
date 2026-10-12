"""A repo without `.specify/` is bootstrapped via the official `specify init`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from spaex.constitution.resolve import ResolvedMolecule
from spaex.integrations.speckit import prepare_install
from spaex.model.molecule_manifest import MoleculeManifest
from spaex.util.errors import SpeckitCliFailedError


def _fake_cli(tmp_path: Path, *, init_exit: int = 0) -> tuple[str, str]:
    """Mirror the official CLI: `integration list` fails outside a Spec Kit project."""
    executable = tmp_path / "fake_specify.py"
    executable.write_text(
        f"""from pathlib import Path
import sys

CALLS = Path({str(tmp_path / "calls.log")!r})
args = sys.argv[1:]
CALLS.open("a", encoding="utf-8").write(" ".join(args) + "\\n")
initialized = (Path.cwd() / ".specify").is_dir()
if args == ["version"]:
    print("CLI Version 1.0.11")
    raise SystemExit(0)
if args[0] == "init":
    if {init_exit}:
        raise SystemExit({init_exit})
    (Path.cwd() / ".specify").mkdir()
    raise SystemExit(0)
if args[:2] == ["integration", "list"]:
    if not initialized:
        print("Error: Not a Spec Kit project (no .specify/ directory)")
        raise SystemExit(1)
    sys.stdout.buffer.write(
        "│ claude │ Claude Code │\\n│ codex │ Codex CLI │\\n".encode("utf-8")
    )
    raise SystemExit(0)
if args[:2] == ["integration", "install"]:
    raise SystemExit(0 if initialized else 1)
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    return sys.executable, str(executable)


def _resolved(tmp_path: Path) -> list[ResolvedMolecule]:
    manifest = MoleculeManifest.from_json(
        json.dumps(
            {
                "spaex_version": "4",
                "id": "com.example.publisher.speckit",
                "version": "1.0.0",
                "priority": 1,
                "atoms": {},
                "speckit": {
                    "version_constraint": ">=1.0.0",
                    "integrations": {
                        "claude": {},
                        "codex": {"integration_options": "--skills"},
                    },
                },
            }
        ).encode()
    )
    return [
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


def test_fresh_repo_is_initialized_once_before_integrations_install(tmp_path: Path) -> None:
    executable = _fake_cli(tmp_path)

    records = prepare_install(
        _resolved(tmp_path),
        repo_root=tmp_path,
        existing_lock=None,
        explicit_selection="codex",
        executable=executable,
    )

    assert (tmp_path / ".specify").is_dir()
    assert records["com.example.publisher.speckit"].outcomes == {"codex": "installed"}
    assert (tmp_path / "calls.log").read_text().splitlines() == [
        "version",
        "init --here --force --non-interactive --ignore-agent-tools"
        " --integration codex --integration-options=--skills",
        "integration list",
        "integration install codex --integration-options=--skills",
    ]

    prepare_install(
        _resolved(tmp_path),
        repo_root=tmp_path,
        existing_lock=None,
        explicit_selection="claude",
        executable=executable,
    )
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert sum(call.startswith("init") for call in calls) == 1


def test_failed_init_stops_before_any_integration_install(tmp_path: Path) -> None:
    with pytest.raises(SpeckitCliFailedError, match="specify init"):
        prepare_install(
            _resolved(tmp_path),
            repo_root=tmp_path,
            existing_lock=None,
            explicit_selection="claude,codex",
            executable=_fake_cli(tmp_path, init_exit=3),
        )

    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert calls == [
        "version",
        "init --here --force --non-interactive --ignore-agent-tools --integration claude",
    ]
    assert not (tmp_path / ".specify").exists()
