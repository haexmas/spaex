"""Spec 027 — generic atom-category delivery and removal.

Exercises the reference use case end to end: an exclusive `dev_environment`
category (flake.nix-style root files) and the composable `nix_packages`
category (multiple molecules contributing orthogonal package fragments),
via the real `spaex add`/`spaex remove` CLI entry points against a fixture
publisher repo — mirroring the existing `haex_add_helpers` pattern other
integration tests in this suite already use.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from spaex.model.install_lock import InstallLock
from spaex.util.errors import HaexError


def _local_git(cwd: Path, *args: str) -> str:
    """Run Git in a fixture repository and return its trimmed output."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _make_publisher_with_files(
    tmp_path: Path,
    molecules: dict[str, dict],
    *,
    clone_dir,
    name: str = "publisher",
) -> tuple[str, str, Path]:
    """Like `haex_add_helpers["make_publisher"]`, but each molecule supplies
    explicit `{relative_path: content}` file content instead of an
    auto-generated placeholder — needed here so a `nix_packages` fragment
    can be real JSON rather than a markdown comment line.
    """
    working = tmp_path / f"{name}-working"
    working.mkdir()
    _local_git(working, "init", "-q", "-b", "main")
    _local_git(working, "config", "user.email", "t@e")
    _local_git(working, "config", "user.name", "t")
    _local_git(working, "config", "commit.gpgsign", "false")
    publisher = "com.example.publisher"
    publisher_manifest = {
        "spaex_version": "4",
        "publisher": publisher,
        "molecules": {
            mid: {"path": info["path"], "version": info["version"]}
            for mid, info in molecules.items()
        },
    }
    (working / "manifest.json").write_text(json.dumps(publisher_manifest, indent=2))
    for mid, info in molecules.items():
        mol_dir = working / info["path"]
        mol_dir.mkdir(parents=True)
        molecule_manifest = {
            "spaex_version": "4",
            "id": mid,
            "version": info["version"],
            "priority": info.get("priority", 100),
            "atoms": info["atoms"],
        }
        (mol_dir / "manifest.json").write_text(json.dumps(molecule_manifest, indent=2))
        for rel_path, content in info["files"].items():
            target = mol_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    _local_git(working, "add", ".")
    _local_git(working, "commit", "-q", "-m", "publisher")
    head = _local_git(working, "rev-parse", "HEAD")

    canonical_url = f"https://example.com/{name}"
    state_root = tmp_path / "state"
    target_dir = clone_dir(state_root, canonical_url)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target_dir)], check=True
    )
    return canonical_url, head, state_root


_BASE_ID = "com.example.publisher.nix-devshell-base"
_PYTHON_ID = "com.example.publisher.python"
_RUST_ID = "com.example.publisher.rust"


def _base_and_language_publisher(tmp_path: Path, clone_dir):
    """Create a publisher with one exclusive and two composable contributors."""
    return _make_publisher_with_files(
        tmp_path,
        clone_dir=clone_dir,
        molecules={
            _BASE_ID: {
                "path": "base",
                "version": "1.0.0",
                "atoms": {"dev_environment": ["flake.nix", ".envrc"]},
                "files": {
                    "flake.nix": "{ outputs = { }; }\n",
                    ".envrc": "use flake\n",
                },
            },
            _PYTHON_ID: {
                "path": "python",
                "version": "1.0.0",
                "atoms": {"nix_packages": ["packages.json"]},
                "files": {"packages.json": json.dumps(["python312"])},
            },
            _RUST_ID: {
                "path": "rust",
                "version": "1.0.0",
                "atoms": {"nix_packages": ["packages.json"]},
                "files": {"packages.json": json.dumps(["cargo", "rustc"])},
            },
        },
    )


def test_exclusive_atom_delivered_and_reinstall_is_idempotent(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    canonical, head, state_root = _base_and_language_publisher(
        tmp_path, haex_add_helpers["clone_dir"]
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    rc = haex_add_helpers["run_add"](
        consumer, state_root, monkeypatch,
        source_url=canonical, molecule_ids=_BASE_ID, revision=head,
    )
    assert rc == 0
    assert (consumer / "flake.nix").read_text() == "{ outputs = { }; }\n"
    assert (consumer / ".envrc").read_text() == "use flake\n"

    lock = InstallLock.from_json((consumer / ".spaex/install.lock").read_bytes())
    entry = next(m for m in lock.molecules if m.id == _BASE_ID)
    assert set(entry.paths) == {"flake.nix", ".envrc"}
    assert set(lock.content_hashes) == {"flake.nix", ".envrc"}

    generation_before = lock.generation_id
    flake_mtime_before = (consumer / "flake.nix").stat().st_mtime_ns

    rc_again = haex_add_helpers["run_add"](
        consumer, state_root, monkeypatch,
        source_url=canonical, molecule_ids=_BASE_ID, revision=head,
    )
    assert rc_again == 0
    lock_after = InstallLock.from_json((consumer / ".spaex/install.lock").read_bytes())
    assert lock_after.generation_id == generation_before, "unchanged inputs must no-op"
    assert (consumer / "flake.nix").stat().st_mtime_ns == flake_mtime_before


def test_exclusive_atom_overwrites_preexisting_unowned_file(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    canonical, head, state_root = _base_and_language_publisher(
        tmp_path, haex_add_helpers["clone_dir"]
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    (consumer / "flake.nix").write_text("# hand-authored, not spaex-owned\n")

    rc = haex_add_helpers["run_add"](
        consumer, state_root, monkeypatch,
        source_url=canonical, molecule_ids=_BASE_ID, revision=head,
    )
    assert rc == 0
    assert (consumer / "flake.nix").read_text() == "{ outputs = { }; }\n"


def test_exclusive_atom_cross_molecule_collision_refused(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    canonical, head, state_root = _make_publisher_with_files(
        tmp_path,
        {
            "com.example.publisher.a": {
                "path": "a",
                "version": "1.0.0",
                "atoms": {"dev_environment": ["flake.nix"]},
                "files": {"flake.nix": "# a\n"},
            },
            "com.example.publisher.b": {
                "path": "b",
                "version": "1.0.0",
                "atoms": {"dev_environment": ["flake.nix"]},
                "files": {"flake.nix": "# b\n"},
            },
        },
        clone_dir=haex_add_helpers["clone_dir"],
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    with pytest.raises(HaexError):
        haex_add_helpers["run_add"](
            consumer, state_root, monkeypatch,
            source_url=canonical,
            molecule_ids="com.example.publisher.a,com.example.publisher.b",
            revision=head,
        )
    assert not (consumer / "flake.nix").exists()
    assert not (consumer / ".spaex/install.lock").exists()


def test_exclusive_atom_path_escapes_repo_refused(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    # A dot-prefixed nested path (the schema's other accepted path shape,
    # alongside a bare single-segment filename) whose ancestor directory is
    # a symlink pointing outside the repo — FR-010 must catch this even
    # though the declared path string itself is lexically repo-relative.
    canonical, head, state_root = _make_publisher_with_files(
        tmp_path,
        {
            "com.example.publisher.escape": {
                "path": "escape",
                "version": "1.0.0",
                "atoms": {"dev_environment": [".outside/marker.txt"]},
                "files": {".outside/marker.txt": "should never land here\n"},
            },
        },
        clone_dir=haex_add_helpers["clone_dir"],
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    outside_target = tmp_path / "outside-escape-target"
    outside_target.mkdir()
    (consumer / ".outside").symlink_to(outside_target, target_is_directory=True)

    with pytest.raises(HaexError):
        haex_add_helpers["run_add"](
            consumer, state_root, monkeypatch,
            source_url=canonical, molecule_ids="com.example.publisher.escape", revision=head,
        )
    assert not (outside_target / "marker.txt").exists()


def test_exclusive_atom_removed_on_retract_and_warns_when_modified(
    tmp_path: Path, haex_add_helpers, monkeypatch, capsys
) -> None:
    canonical, head, state_root = _base_and_language_publisher(
        tmp_path, haex_add_helpers["clone_dir"]
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    haex_add_helpers["run_add"](
        consumer, state_root, monkeypatch,
        source_url=canonical, molecule_ids=_BASE_ID, revision=head,
    )
    assert (consumer / "flake.nix").exists()
    assert (consumer / ".envrc").exists()

    (consumer / ".envrc").write_text("use flake\n# operator added a local override\n")

    rc = haex_add_helpers["run_remove"](consumer, state_root, monkeypatch, molecule_ids=_BASE_ID)
    assert rc == 0
    assert not (consumer / "flake.nix").exists(), "unmodified exclusive atom must be deleted"
    assert (consumer / ".envrc").exists(), "modified-since-install file must be preserved (FR-007)"
    assert "modified" in capsys.readouterr().err.lower()


def test_constitution_contributor_own_exclusive_atom_tracked_and_removed(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    """A molecule using the legacy `atoms.constitution` category *and* an
    exclusive generic-atom category must have both paths recorded against
    its own `install.lock` entry, so `spaex remove` cleans up the generic
    atom too — not just the classic constitution file. Regression test for
    a CodeRabbit finding: the two categories used to publish through
    different code paths, and only the constitution path was ever
    attributed to the contributor's own entry.
    """
    combo_id = "com.example.publisher.combo"
    canonical, head, state_root = _make_publisher_with_files(
        tmp_path,
        {
            combo_id: {
                "path": "combo",
                "version": "1.0.0",
                "atoms": {
                    "constitution": ["constitution.md"],
                    "dev_environment": ["flake.nix"],
                },
                "files": {
                    "constitution.md": "# rules\n",
                    "flake.nix": "{ outputs = { }; }\n",
                },
            },
        },
        clone_dir=haex_add_helpers["clone_dir"],
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    rc = haex_add_helpers["run_add"](
        consumer, state_root, monkeypatch,
        source_url=canonical, molecule_ids=combo_id, revision=head,
    )
    assert rc == 0
    assert (consumer / "flake.nix").exists()

    lock = InstallLock.from_json((consumer / ".spaex/install.lock").read_bytes())
    entry = next(m for m in lock.molecules if m.id == combo_id)
    assert set(entry.paths) == {".spaex/constitution.md", "flake.nix"}

    rc2 = haex_add_helpers["run_remove"](
        consumer, state_root, monkeypatch, molecule_ids=combo_id
    )
    assert rc2 == 0
    assert not (consumer / "flake.nix").exists(), (
        "the contributor's own exclusive atom must be cleaned up on retraction"
    )


def test_exclusive_atom_nested_path_without_dot_segment_refused(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    """A nested exclusive-atom path with no leading dot-segment (e.g.
    `config/tool.toml`) cannot round-trip through install.lock's schema and
    must be refused at install time rather than corrupt a later
    `install.lock` read.
    """
    canonical, head, state_root = _make_publisher_with_files(
        tmp_path,
        {
            "com.example.publisher.nested": {
                "path": "nested",
                "version": "1.0.0",
                "atoms": {"dev_environment": ["config/tool.toml"]},
                "files": {"config/tool.toml": "# config\n"},
            },
        },
        clone_dir=haex_add_helpers["clone_dir"],
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    with pytest.raises(HaexError):
        haex_add_helpers["run_add"](
            consumer, state_root, monkeypatch,
            source_url=canonical,
            molecule_ids="com.example.publisher.nested",
            revision=head,
        )
    assert not (consumer / "config").exists()
    assert not (consumer / ".spaex/install.lock").exists()


def test_nix_packages_composition_and_removal(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    canonical, head, state_root = _base_and_language_publisher(
        tmp_path, haex_add_helpers["clone_dir"]
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    rc = haex_add_helpers["run_add"](
        consumer, state_root, monkeypatch,
        source_url=canonical,
        molecule_ids=f"{_BASE_ID},{_PYTHON_ID}",
        revision=head,
    )
    assert rc == 0
    generated = consumer / ".spaex/generated/nix-packages.json"
    assert json.loads(generated.read_text()) == ["python312"]

    lock = InstallLock.from_json((consumer / ".spaex/install.lock").read_bytes())
    owners = sorted(
        m.id for m in lock.molecules if ".spaex/generated/nix-packages.json" in m.paths
    )
    assert owners == [_PYTHON_ID]

    rc2 = haex_add_helpers["run_add"](
        consumer, state_root, monkeypatch,
        source_url=canonical, molecule_ids=_RUST_ID, revision=head,
    )
    assert rc2 == 0
    assert json.loads(generated.read_text()) == ["cargo", "python312", "rustc"]

    rc3 = haex_add_helpers["run_remove"](consumer, state_root, monkeypatch, molecule_ids=_PYTHON_ID)
    assert rc3 == 0
    assert json.loads(generated.read_text()) == ["cargo", "rustc"], (
        "regenerated from the remaining contributor, not deleted"
    )
    assert (consumer / "flake.nix").exists(), "base molecule's own atoms are untouched"

    rc4 = haex_add_helpers["run_remove"](consumer, state_root, monkeypatch, molecule_ids=_RUST_ID)
    assert rc4 == 0
    assert not generated.exists(), "deleted once the last contributor is retracted"


def test_nix_packages_malformed_fragment_refuses_whole_install(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    canonical, head, state_root = _make_publisher_with_files(
        tmp_path,
        {
            "com.example.publisher.good": {
                "path": "good",
                "version": "1.0.0",
                "atoms": {"nix_packages": ["packages.json"]},
                "files": {"packages.json": json.dumps(["python312"])},
            },
            "com.example.publisher.bad": {
                "path": "bad",
                "version": "1.0.0",
                "atoms": {"nix_packages": ["packages.json"]},
                "files": {"packages.json": "{}"},
            },
        },
        clone_dir=haex_add_helpers["clone_dir"],
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    with pytest.raises(HaexError):
        haex_add_helpers["run_add"](
            consumer, state_root, monkeypatch,
            source_url=canonical,
            molecule_ids="com.example.publisher.good,com.example.publisher.bad",
            revision=head,
        )
    assert not (consumer / ".spaex/generated/nix-packages.json").exists()
    assert not (consumer / ".spaex/install.lock").exists()
