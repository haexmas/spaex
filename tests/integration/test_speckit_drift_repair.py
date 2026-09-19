"""Regression coverage for Spec 027 speckit drift repair.

``install.lock`` only remembers that an integration key was *selected*; it
never checks whether the official CLI's own output tree (``.claude/``,
``.agents/``, ...) still exists on disk. That tree is typically per-checkout
and gitignored, so a fresh clone, a ``git clean``, or a manual deletion all
silently desync it from the lock without spaex noticing, and a repeat
``spaex install`` used to skip the key forever because it trusted the lock
over the filesystem. These tests cover the fix: a drift check against the
official CLI's own health check (``integration status --json``), and the
targeted repair (clearing just the drifted key's own registration) that
unblocks a genuine reinstall.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from spaex.constitution.resolve import ResolvedMolecule
from spaex.integrations.speckit import (
    _clear_stale_registrations,
    _detect_drifted_keys,
    prepare_install,
)
from spaex.model.install_lock import InstallLock, MoleculeEntry, SpeckitLockRecord
from spaex.model.molecule_manifest import MoleculeManifest


def _resolved(tmp_path: Path, *, molecule_id: str, options: dict[str, str]) -> ResolvedMolecule:
    """Build a resolved molecule with the requested Spec Kit integrations."""
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


def _lock(resolved: ResolvedMolecule, record: SpeckitLockRecord) -> InstallLock:
    """Build an install lock containing one resolved molecule record."""
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


def _status_only_cli(tmp_path: Path, *, response: str, exit_code: int = 0) -> tuple[str, str]:
    """A fake `specify` that only answers `integration status --json`."""
    executable = tmp_path / "fake_status.py"
    executable.write_text(
        f"""import sys
args = sys.argv[1:]
if args[:3] == ["integration", "status", "--json"]:
    sys.stdout.write({response!r})
    raise SystemExit({exit_code})
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    return sys.executable, str(executable)


def test_detect_drifted_keys_flags_key_absent_from_manifests(tmp_path: Path) -> None:
    """Treat an installed key omitted from the CLI manifest map as drifted."""
    payload = json.dumps({"manifests": {"claude": {"readable": True, "missing_files": []}}})
    executable = _status_only_cli(tmp_path, response=payload)
    drifted = _detect_drifted_keys(("claude", "codex"), repo_root=tmp_path, executable=executable)
    assert drifted == frozenset({"codex"})


def test_detect_drifted_keys_flags_missing_files(tmp_path: Path) -> None:
    """Treat an integration with missing managed files as drifted."""
    payload = json.dumps(
        {"manifests": {"codex": {"readable": True, "missing_files": [".agents/skills/x.md"]}}}
    )
    executable = _status_only_cli(tmp_path, response=payload)
    drifted = _detect_drifted_keys(("codex",), repo_root=tmp_path, executable=executable)
    assert drifted == frozenset({"codex"})


def test_detect_drifted_keys_flags_unreadable_manifest(tmp_path: Path) -> None:
    """Treat an integration with an unreadable manifest as drifted."""
    payload = json.dumps({"manifests": {"codex": {"readable": False, "missing_files": []}}})
    executable = _status_only_cli(tmp_path, response=payload)
    drifted = _detect_drifted_keys(("codex",), repo_root=tmp_path, executable=executable)
    assert drifted == frozenset({"codex"})


def test_detect_drifted_keys_trusts_a_healthy_manifest(tmp_path: Path) -> None:
    """Keep an integration whose manifest and managed files are healthy."""
    payload = json.dumps({"manifests": {"codex": {"readable": True, "missing_files": []}}})
    executable = _status_only_cli(tmp_path, response=payload)
    drifted = _detect_drifted_keys(("codex",), repo_root=tmp_path, executable=executable)
    assert drifted == frozenset()


def test_detect_drifted_keys_fails_closed_on_cli_error(tmp_path: Path) -> None:
    """Report no drift when the official CLI status command fails."""
    executable = _status_only_cli(tmp_path, response="", exit_code=2)
    drifted = _detect_drifted_keys(("codex",), repo_root=tmp_path, executable=executable)
    assert drifted == frozenset()


def test_detect_drifted_keys_fails_closed_on_malformed_json(tmp_path: Path) -> None:
    """Report no drift when the official CLI emits malformed status JSON."""
    executable = _status_only_cli(tmp_path, response="not json")
    drifted = _detect_drifted_keys(("codex",), repo_root=tmp_path, executable=executable)
    assert drifted == frozenset()


def test_detect_drifted_keys_fails_closed_on_non_object_json(tmp_path: Path) -> None:
    for response in ("null", "[]"):
        executable = _status_only_cli(tmp_path, response=response)
        drifted = _detect_drifted_keys(("codex",), repo_root=tmp_path, executable=executable)
        assert drifted == frozenset()


def test_clear_stale_registrations_removes_only_the_drifted_key(tmp_path: Path) -> None:
    """Remove only drifted keys and preserve unrelated integration state."""
    state = tmp_path / ".specify" / "integration.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "installed_integrations": ["claude", "codex"],
                "integration_settings": {
                    "claude": {"script": "sh"},
                    "codex": {"script": "sh"},
                },
                "default_integration": "claude",
            }
        )
    )
    _clear_stale_registrations(tmp_path, frozenset({"codex"}))
    data = json.loads(state.read_text())
    assert data["installed_integrations"] == ["claude"]
    assert "codex" not in data["integration_settings"]
    assert data["integration_settings"]["claude"] == {"script": "sh"}
    assert data["default_integration"] == "claude"


def test_clear_stale_registrations_is_a_noop_without_a_state_file(tmp_path: Path) -> None:
    """Leave the repository untouched when no integration state file exists."""
    # Must not raise even though `.specify/integration.json` doesn't exist.
    _clear_stale_registrations(tmp_path, frozenset({"codex"}))
    assert not (tmp_path / ".specify").exists()


def test_clear_stale_registrations_is_a_noop_on_malformed_state(tmp_path: Path) -> None:
    """Preserve malformed integration state instead of rewriting it."""
    state = tmp_path / ".specify" / "integration.json"
    state.parent.mkdir(parents=True)
    state.write_text("not json")
    _clear_stale_registrations(tmp_path, frozenset({"codex"}))
    assert state.read_text() == "not json"


def test_clear_stale_registrations_is_a_noop_on_non_object_state(tmp_path: Path) -> None:
    state = tmp_path / ".specify" / "integration.json"
    state.parent.mkdir(parents=True)
    for payload in ("null", "[]"):
        state.write_text(payload)
        _clear_stale_registrations(tmp_path, frozenset({"codex"}))
        assert state.read_text() == payload


def _stateful_fake_cli(tmp_path: Path) -> tuple[str, str]:
    """A fake `specify` that mirrors the real CLI's own idempotency deadlock.

    Once a key is in `.specify/integration.json`'s `installed_integrations`,
    `integration install <key>` refuses to touch it again ("already
    installed ... no files changed") regardless of whether its managed
    files still exist — matching specify-cli 1.0.6's actual behavior.
    """
    executable = tmp_path / "stateful_specify.py"
    executable.write_text(
        f"""import json
import sys
from pathlib import Path

CALLS = Path({str(tmp_path / "calls.log")!r})
STATE = Path.cwd() / ".specify" / "integration.json"
args = sys.argv[1:]
CALLS.open("a", encoding="utf-8").write(" ".join(args) + "\\n")


def _state():
    if STATE.is_file():
        return json.loads(STATE.read_text())
    return {{"installed_integrations": []}}


def _save(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data))


def _marker(key):
    root = ".claude" if key == "claude" else ".agents"
    return Path.cwd() / root / "skills" / "specify.md"


if args == ["version"]:
    print("CLI Version 0.8.1.dev0")
    raise SystemExit(0)
if args[:2] == ["integration", "list"]:
    sys.stdout.buffer.write(
        "│ claude │ Claude Code │\\n│ codex │ Codex CLI │\\n".encode("utf-8")
    )
    raise SystemExit(0)
if args[:3] == ["integration", "status", "--json"]:
    data = _state()
    manifests = {{}}
    for key in data.get("installed_integrations", []):
        marker = _marker(key)
        manifests[key] = {{
            "readable": True,
            "missing_files": [] if marker.exists() else [str(marker)],
        }}
    print(json.dumps({{"manifests": manifests}}))
    raise SystemExit(0)
if args[:2] == ["integration", "install"]:
    key = args[2]
    data = _state()
    if key in data.get("installed_integrations", []):
        print(f"Integration '{{key}}' is already installed.")
        print("No files were changed.")
        raise SystemExit(0)
    marker = _marker(key)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    data.setdefault("installed_integrations", []).append(key)
    _save(data)
    print(f"Integration '{{key}}' installed successfully")
    raise SystemExit(0)
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    return sys.executable, str(executable)


def test_prepare_install_repairs_agent_output_lost_between_checkouts(tmp_path: Path) -> None:
    """Reinstall selected integrations whose managed output disappeared."""
    executable = _stateful_fake_cli(tmp_path)
    resolved = [_resolved(tmp_path, molecule_id="com.example.speckit", options={"codex": ""})]

    first = prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=None,
        explicit_selection="codex",
        executable=executable,
    )
    marker = tmp_path / ".agents" / "skills" / "specify.md"
    assert marker.exists()
    assert first[resolved[0].molecule_id].outcomes == {"codex": "installed"}

    lock = _lock(resolved[0], first[resolved[0].molecule_id])

    # Simulate a fresh checkout: the gitignored output tree is gone, but
    # install.lock (committed, travels with the repo) still says selected.
    marker.unlink()

    second = prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=lock,
        executable=executable,
    )

    assert marker.exists(), "drifted key must be genuinely reinstalled, not just re-recorded"
    assert second[resolved[0].molecule_id].outcomes == {"codex": "installed"}
    assert second[resolved[0].molecule_id].selected == ("codex",)


def test_prepare_install_leaves_healthy_selection_untouched(tmp_path: Path) -> None:
    """Avoid reinstalling a selected integration whose output remains healthy."""
    executable = _stateful_fake_cli(tmp_path)
    resolved = [_resolved(tmp_path, molecule_id="com.example.speckit", options={"codex": ""})]

    first = prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=None,
        explicit_selection="codex",
        executable=executable,
    )
    lock = _lock(resolved[0], first[resolved[0].molecule_id])
    calls_before = (tmp_path / "calls.log").read_text().splitlines()

    second = prepare_install(
        resolved,
        repo_root=tmp_path,
        existing_lock=lock,
        executable=executable,
    )

    calls_after = (tmp_path / "calls.log").read_text().splitlines()
    new_calls = calls_after[len(calls_before) :]
    assert "integration install codex" not in new_calls
    assert second[resolved[0].molecule_id].outcomes == {"codex": "installed"}
