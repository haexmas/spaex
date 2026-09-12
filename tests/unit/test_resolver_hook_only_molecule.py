"""T010 - resolve_molecules emits hook-only molecules (Spec 016 FR-007, FR-008)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from spaex.constitution.resolve import ResolvedMolecule, resolve_molecules
from spaex.git.cache import clone_dir
from spaex.model.consumer_manifest import CompoundEntry, ConfigEntry, ConsumerManifest
from spaex.model.molecule_manifest import InstallHook

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


def _git(repo: Path, *args: str) -> str:
    """Run Git in a fixture repository and return its stripped standard output."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _init_repo(root: Path) -> None:
    """Initialize a deterministic Git repository for resolver fixtures."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "haex-test@example.com")
    _git(root, "config", "user.name", "haex-test")
    _git(root, "config", "commit.gpgsign", "false")


def _publish(publisher: Path, publisher_manifest: dict, molecules: dict[str, dict]) -> str:
    """Commit publisher and molecule manifests, returning the commit revision."""
    publisher.mkdir(parents=True, exist_ok=True)
    _init_repo(publisher)
    (publisher / "manifest.json").write_text(
        json.dumps(publisher_manifest, sort_keys=True)
    )
    for path, molecule_manifest in molecules.items():
        molecule_dir = publisher / path
        molecule_dir.mkdir(parents=True, exist_ok=True)
        (molecule_dir / "manifest.json").write_text(
            json.dumps(molecule_manifest, sort_keys=True)
        )
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "publish")
    return _git(publisher, "rev-parse", "HEAD")


def _clone(state_root: Path, canonical: str, publisher: Path) -> None:
    """Copy a publisher repository into its canonical state-root clone path."""
    target = clone_dir(state_root, canonical)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, target)


def _manifest(compounds: list[CompoundEntry]) -> ConsumerManifest:
    """Build a consumer manifest from the supplied compound entries."""
    return ConsumerManifest(
        spaex_version="4",
        identity="com.github.example.consumer",
        compounds=tuple(compounds),
    )


def test_hook_only_molecule_is_returned_by_resolve_molecules(tmp_path: Path) -> None:
    """FR-007: hook-only molecule (no atoms.constitution) survives the resolver."""
    canonical = "https://github.com/example/publisher"
    publisher = tmp_path / "publisher"
    molecule_id = "com.github.example.publisher.hookonly"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_id: {"path": "hookonly", "version": "1.0.0"}},
        },
        {
            "hookonly": {
                "spaex_version": "4",
                "id": molecule_id,
                "version": "1.0.0",
                "priority": 30,
                "atoms": {"slash_commands": [".spaex/cmd.md"]},
                "install_hook": {
                    "interpreter": "python3",
                    "script": "install.py",
                    "on_failure": "warn",
                },
            }
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    manifest = _manifest(
        [
            CompoundEntry(
                source=canonical,
                revision=sha,
                molecules=(molecule_id,),
                config={},
            )
        ]
    )

    resolved = resolve_molecules(manifest, state_root)
    assert len(resolved) == 1
    record = resolved[0]
    assert isinstance(record, ResolvedMolecule)
    assert record.molecule_id == molecule_id
    assert record.source_url == canonical
    assert record.revision == sha.lower()
    assert record.repo_dir == clone_dir(state_root, canonical)
    assert record.molecule_path == "hookonly"
    assert record.effective_priority == 30
    assert record.install_hook == InstallHook(
        interpreter="python3",
        script="install.py",
        args=(),
        on_failure="warn",
    )


def test_consumer_priority_override_wins(tmp_path: Path) -> None:
    """FR-008: effective_priority reflects consumer override when present."""
    canonical = "https://github.com/example/publisher"
    publisher = tmp_path / "publisher"
    molecule_id = "com.github.example.publisher.demo"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_id: {"path": "demo", "version": "1.0.0"}},
        },
        {
            "demo": {
                "spaex_version": "4",
                "id": molecule_id,
                "version": "1.0.0",
                "priority": 5,
                "atoms": {"constitution": ["constitution.md"]},
            }
        },
    )
    (publisher / "demo" / "constitution.md").write_text("body")
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "constitution body")
    sha = _git(publisher, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    manifest = _manifest(
        [
            CompoundEntry(
                source=canonical,
                revision=sha,
                molecules=(molecule_id,),
                config={molecule_id: ConfigEntry(priority=77, values={})},
            )
        ]
    )
    resolved = resolve_molecules(manifest, state_root)
    assert len(resolved) == 1
    assert resolved[0].effective_priority == 77
    assert resolved[0].install_hook is None


def test_priority_sort_and_utf8_tiebreak(tmp_path: Path) -> None:
    """FR-010: sort is (effective_priority asc, molecule_id UTF-8 asc)."""
    canonical = "https://github.com/example/publisher"
    publisher = tmp_path / "publisher"
    a_id = "com.github.example.publisher.aaaa"
    b_id = "com.github.example.publisher.bbbb"
    c_id = "com.github.example.publisher.cccc"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {
                a_id: {"path": "a", "version": "1.0.0"},
                b_id: {"path": "b", "version": "1.0.0"},
                c_id: {"path": "c", "version": "1.0.0"},
            },
        },
        {
            "a": {
                "spaex_version": "4",
                "id": a_id,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"slash_commands": [".spaex/a.md"]},
            },
            "b": {
                "spaex_version": "4",
                "id": b_id,
                "version": "1.0.0",
                "priority": 10,
                "atoms": {"slash_commands": [".spaex/b.md"]},
            },
            "c": {
                "spaex_version": "4",
                "id": c_id,
                "version": "1.0.0",
                "priority": 10,
                "atoms": {"slash_commands": [".spaex/c.md"]},
            },
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    manifest = _manifest(
        [
            CompoundEntry(
                source=canonical,
                revision=sha,
                molecules=(c_id, a_id, b_id),
                config={},
            )
        ]
    )
    resolved = resolve_molecules(manifest, state_root)
    assert [r.molecule_id for r in resolved] == [b_id, c_id, a_id]
