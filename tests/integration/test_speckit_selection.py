from __future__ import annotations

import hashlib
import json
import sys
from io import StringIO
from pathlib import Path

import pytest

from spaex.constitution.resolve import ResolvedMolecule
from spaex.integrations.speckit import (
    declaration_fingerprint,
    prepare_install,
    select_integrations,
)
from spaex.model.install_lock import InstallLock, MoleculeEntry, SpeckitLockRecord
from spaex.model.molecule_manifest import MoleculeManifest
from spaex.util.errors import (
    SpeckitDeclarationConflictError,
    SpeckitSelectionRequiredError,
)


def _fake_cli(tmp_path: Path) -> tuple[str, str]:
    executable = tmp_path / "fake_specify.py"
    executable.write_text(
        f"""from pathlib import Path
import sys

CALLS = Path({str(tmp_path / "calls.log")!r})
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
    (Path.cwd() / ("installed-" + args[2])).touch()
    raise SystemExit(0)
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    return sys.executable, str(executable)


def _resolved(tmp_path: Path, *, molecule_id: str, options: dict[str, str]):
    manifest = MoleculeManifest.from_json(
        json.dumps(
            {
                "spaex_version": "4",
                "id": molecule_id,
                "version": "1.0.0",
                "priority": 1,
                "atoms": {},
                "speckit": {
                    "version_constraint": ">=0.8.1",
                    "integrations": {
                        key: {"integration_options": value} for key, value in options.items()
                    },
                },
            }
        ).encode()
    )
    return ResolvedMolecule(
        molecule_id=molecule_id,
        source_url="https://example.com/publisher",
        revision="a" * 40,
        repo_dir=tmp_path,
        molecule_path="molecule",
        install_hook=None,
        effective_priority=1,
        molecule_manifest=manifest,
        cache_dir=tmp_path,
    )


def _lock(resolved: ResolvedMolecule, record) -> InstallLock:
    return InstallLock(
        spaex_version="4",
        generation_id="g_20260914T120000Z_abcd",
        molecules=(
            MoleculeEntry(
                id=resolved.molecule_id,
                source=resolved.source_url,
                revision=resolved.revision,
                paths=(),
                speckit=record,
            ),
        ),
    )


def test_changed_selection_installs_only_the_new_agent(tmp_path: Path) -> None:
    executable = _fake_cli(tmp_path)
    resolved = [
        _resolved(
            tmp_path,
            molecule_id="com.example.speckit",
            options={"claude": "", "codex": "--skills"},
        )
    ]
    first = prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=None,
        explicit_selection="codex",
        executable=executable,
    )
    prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=_lock(resolved[0], first[resolved[0].molecule_id]),
        explicit_selection="claude,codex",
        executable=executable,
    )
    installs = [
        line for line in (tmp_path / "calls.log").read_text().splitlines() if " install " in line
    ]
    assert installs.count("integration install codex --integration-options=--skills") == 1
    assert installs.count("integration install claude") == 1


def test_conflicting_declarations_refuse_before_cli_invocation(tmp_path: Path) -> None:
    executable = _fake_cli(tmp_path)
    resolved = [
        _resolved(tmp_path, molecule_id="com.example.first", options={"codex": "--skills"}),
        _resolved(tmp_path, molecule_id="com.example.second", options={"codex": ""}),
    ]
    with pytest.raises(SpeckitDeclarationConflictError):
        prepare_install(
            resolved,
            repo_root=tmp_path,
            existing_lock=None,
            explicit_selection="codex",
            executable=executable,
        )
    assert not (tmp_path / "calls.log").exists()


def test_noninteractive_missing_selection_refuses(tmp_path: Path) -> None:
    with pytest.raises(SpeckitSelectionRequiredError):
        prepare_install(
            [_resolved(tmp_path, molecule_id="com.example.speckit", options={"codex": ""})],
            repo_root=tmp_path,
            existing_lock=None,
            executable=_fake_cli(tmp_path),
        )


def test_skipped_record_does_not_suppress_interactive_selection(tmp_path: Path) -> None:
    executable = _fake_cli(tmp_path)
    resolved = _resolved(tmp_path, molecule_id="com.example.speckit", options={"codex": ""})
    manifest = resolved.molecule_manifest
    assert manifest is not None and manifest.speckit is not None
    previous = SpeckitLockRecord(
        cli_version="not-run",
        declaration_fingerprint=declaration_fingerprint(
            manifest.speckit,
            resolved.source_url,
            resolved.revision,
        ),
        selected=(),
        outcomes={"codex": "skipped"},
    )
    output = StringIO()

    records = prepare_install(
        [resolved],
        repo_root=tmp_path,
        existing_lock=_lock(resolved, previous),
        executable=executable,
        stdin=StringIO("codex\n"),
        stdout=output,
    )

    assert records[resolved.molecule_id].selected == ("codex",)
    assert "Which agents should receive the Spec Kit skills?" in output.getvalue()
    assert "integration install codex" in (tmp_path / "calls.log").read_text()


def test_all_selection_requires_interactive_confirmation() -> None:
    output = StringIO()

    selected = select_integrations(
        "all",
        ("claude", "codex"),
        persisted=None,
        stdin=StringIO("codex\n"),
        stdout=output,
    )

    assert selected == ("codex",)
    assert "Which agents should receive the Spec Kit skills?" in output.getvalue()


def test_noninteractive_all_selection_refuses_before_cli_invocation(tmp_path: Path) -> None:
    with pytest.raises(SpeckitSelectionRequiredError, match="interactive selection"):
        prepare_install(
            [_resolved(tmp_path, molecule_id="com.example.speckit", options={"codex": ""})],
            repo_root=tmp_path,
            existing_lock=None,
            explicit_selection="all",
            executable=_fake_cli(tmp_path),
        )

    assert not (tmp_path / "calls.log").exists()


def test_legacy_lock_reuses_selection_without_reinstalling(tmp_path: Path) -> None:
    """Reuse a legacy lock selection without invoking installation again."""
    resolved = _resolved(tmp_path, molecule_id="com.example.speckit", options={"codex": ""})
    # Fingerprint payload written before CLI provisioning was introduced.
    payload = {
        "declaration": {
            "version_constraint": ">=0.8.1",
            "integrations": {"codex": ""},
        },
        "source": resolved.source_url,
        "revision": resolved.revision,
        "config": {},
    }
    fingerprint = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    previous = SpeckitLockRecord(
        cli_version="0.8.1",
        declaration_fingerprint=fingerprint,
        selected=("codex",),
        outcomes={"codex": "installed"},
    )
    records = prepare_install(
        [resolved],
        repo_root=tmp_path,
        existing_lock=_lock(resolved, previous),
        executable=_fake_cli(tmp_path),
    )
    assert records[resolved.molecule_id].selected == ("codex",)
    assert records[resolved.molecule_id].declaration_fingerprint == fingerprint
    # The drift check (`integration status --json`) runs but the fake CLI
    # doesn't implement it, so it fails closed (treated as "no drift") and
    # `install` is never invoked below.
    assert (tmp_path / "calls.log").read_text().splitlines() == [
        "version",
        "integration list",
        "integration status --json",
    ]
    assert not (tmp_path / "installed-codex").exists()


def test_opt_out_skips_cli_and_records_skip(tmp_path: Path) -> None:
    resolved = [_resolved(tmp_path, molecule_id="com.example.speckit", options={"codex": ""})]
    records = prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=None,
        disabled=True,
        executable=str(tmp_path / "missing-specify"),
    )
    assert records[resolved[0].molecule_id].outcomes == {"codex": "skipped"}


def test_opt_out_preserves_existing_selection_for_next_invocation(tmp_path: Path) -> None:
    executable = _fake_cli(tmp_path)
    resolved = [_resolved(tmp_path, molecule_id="com.example.speckit", options={"codex": ""})]
    first = prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=None,
        explicit_selection="codex",
        executable=executable,
    )
    disabled = prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=_lock(resolved[0], first[resolved[0].molecule_id]),
        disabled=True,
        executable=executable,
    )

    molecule_id = resolved[0].molecule_id
    assert disabled[molecule_id].selected == ()
    assert disabled.publication_records[molecule_id].selected == ("codex",)

    next_run = prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=_lock(resolved[0], disabled.publication_records[molecule_id]),
        executable=executable,
    )
    assert next_run[molecule_id].selected == ("codex",)
