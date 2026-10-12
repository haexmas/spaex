from __future__ import annotations

import json
import sys
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from spaex.constitution.resolve import ResolvedMolecule
from spaex.integrations.speckit import prepare_install
from spaex.model.molecule_manifest import MoleculeManifest, SpeckitCliProvisioning
from spaex.model.version_constraint import VersionConstraint
from spaex.util.errors import (
    SpeckitCliFailedError,
    SpeckitCliMissingError,
    SpeckitCliVersionIncompatibleError,
    SpeckitIntegrationUnsupportedError,
)


def _resolved(tmp_path: Path, *, integration_key: str = "codex") -> list[ResolvedMolecule]:
    manifest = MoleculeManifest.from_json(
        json.dumps(
            {
                "spaex_version": "4",
                "id": "com.example.speckit",
                "version": "1.0.0",
                "priority": 1,
                "atoms": {},
                "speckit": {
                    "version_constraint": "0.8.1",
                    "integrations": {integration_key: {"integration_options": "--skills"}},
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


def _cli(tmp_path: Path, *, version: str = "0.8.1", fail_install: bool = False) -> tuple[str, str]:
    # An already-initialized Spec Kit project, so no `specify init` runs.
    (tmp_path / ".specify").mkdir(exist_ok=True)
    executable = tmp_path / "fake_specify.py"
    target = "partial.md" if fail_install else "specify.md"
    exit_code = 7 if fail_install else 0
    executable.write_text(
        f"""from pathlib import Path
import sys

args = sys.argv[1:]
if args == ["version"]:
    print("CLI Version {version}")
    raise SystemExit(0)
if args[:2] == ["integration", "list"]:
    sys.stdout.buffer.write("│ codex │ Codex CLI │\\n".encode("utf-8"))
    raise SystemExit(0)
if args[:2] == ["integration", "install"]:
    skills = Path.cwd() / ".agents" / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    (skills / "{target}").touch()
    raise SystemExit({exit_code})
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    return sys.executable, str(executable)


def test_missing_cli_is_typed(tmp_path: Path) -> None:
    with pytest.raises(SpeckitCliMissingError):
        prepare_install(
            _resolved(tmp_path, integration_key="gemini"),
            repo_root=tmp_path,
            existing_lock=None,
            explicit_selection="gemini",
            executable=str(tmp_path / "missing"),
        )


def test_incompatible_cli_is_typed(tmp_path: Path) -> None:
    with pytest.raises(SpeckitCliVersionIncompatibleError):
        prepare_install(
            _resolved(tmp_path),
            repo_root=tmp_path,
            existing_lock=None,
            explicit_selection="codex",
            executable=_cli(tmp_path, version="0.7.0"),
        )


def test_unsupported_selection_is_rejected_before_install(tmp_path: Path) -> None:
    with pytest.raises(SpeckitIntegrationUnsupportedError):
        prepare_install(
            _resolved(tmp_path, integration_key="gemini"),
            repo_root=tmp_path,
            existing_lock=None,
            explicit_selection="gemini",
            executable=_cli(tmp_path),
        )


@pytest.mark.parametrize("actual_version", ["0.8.1", "0.8.3"])
def test_cli_must_match_exact_pin_even_when_policy_allows_it(
    tmp_path: Path, actual_version: str
) -> None:
    resolved = _resolved(tmp_path)[0]
    manifest = resolved.molecule_manifest
    assert manifest is not None and manifest.speckit is not None
    declaration = replace(
        manifest.speckit,
        version_constraint=VersionConstraint.parse(">=0.8.1"),
        cli=SpeckitCliProvisioning("specify-cli", VersionConstraint.parse("0.8.2")),
    )
    resolved = replace(resolved, molecule_manifest=replace(manifest, speckit=declaration))
    with pytest.raises(SpeckitCliVersionIncompatibleError, match="0.8.2"):
        prepare_install(
            [resolved],
            repo_root=tmp_path,
            existing_lock=None,
            explicit_selection="codex",
            executable=_cli(tmp_path, version=actual_version),
        )
    assert not (tmp_path / ".agents").exists()


def test_all_selection_rejects_unsupported_before_install(tmp_path: Path) -> None:
    with pytest.raises(SpeckitIntegrationUnsupportedError):
        prepare_install(
            _resolved(tmp_path, integration_key="gemini"),
            repo_root=tmp_path,
            existing_lock=None,
            explicit_selection="all",
            stdin=StringIO("all\n"),
            executable=_cli(tmp_path),
        )


def test_failed_official_install_preserves_external_boundary(tmp_path: Path) -> None:
    executable = _cli(tmp_path, fail_install=True)
    with pytest.raises(SpeckitCliFailedError):
        prepare_install(
            _resolved(tmp_path),
            repo_root=tmp_path,
            existing_lock=None,
            explicit_selection="codex",
            executable=executable,
        )
    assert (tmp_path / ".agents/skills/partial.md").exists()
