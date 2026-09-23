"""`spaex status` end-to-end (Spec 028 T021-T022, contracts/status-and-trace-cli.md).

No git/molecule resolution is needed here: `spaex status` reads
`.spaex/manifest.json`, `.spaex/install.lock`, `.spaex/constitution.d/`, and
`.spaex/constitution.md` directly off disk, so fixtures are hand-written,
mirroring `test_provenance_trace.py`'s style.
"""

from __future__ import annotations

import getpass
import json
import re
import socket
from dataclasses import replace
from pathlib import Path, PureWindowsPath

from spaex.behavior.composer.clarifications import ClarificationsStore
from spaex.behavior.composer.prompt import (
    COMPOSER_PROMPT_VERSION,
    effective_prompt_sha256,
    load_effective_prompt,
)
from spaex.behavior.emit import compute_build_input_hash, compute_source_hash
from spaex.behavior.fragment import BehaviorFragment
from spaex.cli.main import main
from spaex.model.install_lock import InstallLock, MoleculeEntry

_MOL_BEHAVIOR = "com.example.behavior-only"
_MOL_ARTIFACT_A = "com.example.composed-artifact-a"
_MOL_ARTIFACT_B = "com.example.composed-artifact-b"
_MOL_FILE = "com.example.plain-file"
_SHARED_ARTIFACT_PATH = ".spaex/generated/nix-packages.json"
_REV = "1" * 40


def _assert_repo_relative_posix_path(path: str) -> None:
    assert not Path(path).is_absolute()
    assert not PureWindowsPath(path).is_absolute()
    assert not path.startswith("~")
    assert "\\" not in path


def _write_manifest(repo: Path, *, compounds: list[dict[str, object]]) -> None:
    (repo / ".spaex").mkdir(parents=True, exist_ok=True)
    (repo / ".spaex/manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.status-consumer",
                "compounds": compounds,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_fragment(repo: Path, *, molecule_id: str, fragment_id: str) -> BehaviorFragment:
    target_dir = repo / ".spaex" / "constitution.d" / molecule_id
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{fragment_id}.md"
    path.write_text(
        "---\n"
        f"id: {fragment_id}\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.tool\n"
        "modality: MUST\n"
        "---\n"
        "**MUST** do the thing.\n",
        encoding="utf-8",
    )
    return BehaviorFragment.from_file(path, molecule_id=molecule_id)


def _write_matching_constitution(repo: Path, fragment: BehaviorFragment) -> None:
    source_hash = compute_source_hash([fragment])
    prompt_hash = effective_prompt_sha256(load_effective_prompt(repo))
    build_input_hash = compute_build_input_hash(
        effective_prompt_sha256=prompt_hash,
        composer_prompt_version=COMPOSER_PROMPT_VERSION,
        valid_clarifications=ClarificationsStore().entries.values(),
    )
    (repo / ".spaex/constitution.md").write_text(
        f'<!-- spaex-composed:source_hash="{source_hash}" '
        f'build_input_hash="{build_input_hash}" version="1" -->\n'
        "# spaex Behavior Harness\n\n"
        "## MUST\n"
        f"- Do the thing. _[from `{fragment.scoped_id}`]_\n",
        encoding="utf-8",
    )


def _snapshot(repo: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(repo)): p.read_bytes()
        for p in repo.rglob("*")
        if p.is_file()
    }


def _make_full_fixture(tmp_path: Path) -> Path:
    """One molecule of each atom-grouping kind, plus a matching constitution."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    fragment = _write_fragment(repo, molecule_id=_MOL_BEHAVIOR, fragment_id="cmd")
    _write_matching_constitution(repo, fragment)

    _write_manifest(
        repo,
        compounds=[
            {
                "source": "https://github.com/example/atoms",
                "revision": _REV,
                "molecules": [_MOL_BEHAVIOR, _MOL_ARTIFACT_A, _MOL_ARTIFACT_B, _MOL_FILE],
            }
        ],
    )

    lock = InstallLock(
        "4",
        "g_20260101T000000Z_0000",
        (
            MoleculeEntry(
                id=_MOL_BEHAVIOR,
                source="https://github.com/example/atoms",
                revision=_REV,
                paths=(".spaex/constitution.md",),
                hook_status="ok",
            ),
            MoleculeEntry(
                id=_MOL_ARTIFACT_A,
                source="https://github.com/example/atoms",
                revision=_REV,
                paths=(_SHARED_ARTIFACT_PATH,),
            ),
            MoleculeEntry(
                id=_MOL_ARTIFACT_B,
                source="https://github.com/example/atoms",
                revision=_REV,
                paths=(_SHARED_ARTIFACT_PATH,),
            ),
            MoleculeEntry(
                id=_MOL_FILE,
                source="https://github.com/example/atoms",
                revision=_REV,
                paths=("flake.nix",),
            ),
        ),
    )
    (repo / ".spaex/install.lock").write_bytes(lock.to_json_bytes())
    return repo


def test_status_text_format(tmp_path: Path, capsys) -> None:
    repo = _make_full_fixture(tmp_path)
    before = _snapshot(repo)

    rc = main(["--repo-root", str(repo), "status"])
    out = capsys.readouterr().out

    assert rc == 0
    assert f"{_MOL_BEHAVIOR}@{_REV[:8]} — installed" in out
    assert "behavior fragments: cmd" in out
    assert f"composed artifacts: {_SHARED_ARTIFACT_PATH}" in out
    assert "files: flake.nix" in out
    assert "Constitution: 1 clauses (MUST: 1)" in out
    assert f"contributing molecules: {_MOL_BEHAVIOR}" in out
    assert "status: current" in out
    assert _snapshot(repo) == before


def test_status_text_shows_both_revisions_on_mismatch(tmp_path: Path, capsys) -> None:
    repo = _make_full_fixture(tmp_path)
    lock = InstallLock.from_json((repo / ".spaex/install.lock").read_bytes())
    installed_revision = "2" * 40
    changed_molecule = replace(lock.molecules[0], revision=installed_revision)
    (repo / ".spaex/install.lock").write_bytes(
        replace(lock, molecules=(changed_molecule, *lock.molecules[1:])).to_json_bytes()
    )

    rc = main(["--repo-root", str(repo), "status"])
    out = capsys.readouterr().out

    assert rc == 0
    assert (
        f"{_MOL_BEHAVIOR}@{installed_revision[:8]} "
        f"(pinned @{_REV[:8]}) — installed"
    ) in out


def test_status_json_format(tmp_path: Path, capsys) -> None:
    repo = _make_full_fixture(tmp_path)
    before = _snapshot(repo)

    rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    out = capsys.readouterr().out

    assert rc == 0
    payload = json.loads(out)
    assert payload["format_version"] == 1
    assert payload["drift"] == []

    molecules = {m["molecule_id"]: m for m in payload["molecules"]}
    behavior = molecules[_MOL_BEHAVIOR]
    assert behavior["pinned"] == {"source": "https://github.com/example/atoms", "revision": _REV}
    assert behavior["installed"] == {
        "source": "https://github.com/example/atoms",
        "revision": _REV,
    }
    assert behavior["install_state"] == "installed"
    assert behavior["hook_status"] == "ok"
    assert behavior["atoms"]["behavior_fragments"] == ["cmd"]
    assert behavior["atoms"]["composed_artifacts"] == []
    assert behavior["atoms"]["files"] == []

    artifact_a = molecules[_MOL_ARTIFACT_A]
    assert artifact_a["atoms"]["composed_artifacts"] == [_SHARED_ARTIFACT_PATH]
    assert artifact_a["atoms"]["files"] == []
    assert artifact_a["hook_status"] is None

    plain_file = molecules[_MOL_FILE]
    assert plain_file["atoms"]["files"] == ["flake.nix"]
    assert plain_file["atoms"]["composed_artifacts"] == []

    constitution = payload["constitution"]
    assert constitution["exists"] is True
    assert constitution["clause_counts"] == {"MUST": 1}
    assert constitution["contributing_molecules"] == [_MOL_BEHAVIOR]
    assert constitution["project_local_fragment_ids"] == []
    assert constitution["stale"] is False

    assert _snapshot(repo) == before


def test_status_missing_manifest_exits_7(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()

    rc = main(["--repo-root", str(repo), "status"])

    assert rc == 7


def test_status_manifest_without_install_lock(tmp_path: Path, capsys) -> None:
    """Nothing installed yet: every molecule is pinned_not_installed, no constitution."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    _write_manifest(
        repo,
        compounds=[
            {
                "source": "https://github.com/example/atoms",
                "revision": _REV,
                "molecules": [_MOL_BEHAVIOR],
            }
        ],
    )

    rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    out = capsys.readouterr().out

    assert rc == 0
    payload = json.loads(out)
    assert len(payload["molecules"]) == 1
    molecule = payload["molecules"][0]
    assert molecule["install_state"] == "pinned_not_installed"
    assert molecule["installed"] is None
    assert molecule["hook_status"] is None
    assert payload["constitution"] is None


def test_status_no_molecule_contributes_behavior(tmp_path: Path, capsys) -> None:
    """Installed molecules exist, but none contribute behavior: constitution is null."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    _write_manifest(
        repo,
        compounds=[
            {
                "source": "https://github.com/example/atoms",
                "revision": _REV,
                "molecules": [_MOL_FILE],
            }
        ],
    )
    lock = InstallLock(
        "4",
        "g_20260101T000000Z_0000",
        (
            MoleculeEntry(
                id=_MOL_FILE,
                source="https://github.com/example/atoms",
                revision=_REV,
                paths=("flake.nix",),
            ),
        ),
    )
    (repo / ".spaex").mkdir(exist_ok=True)
    (repo / ".spaex/install.lock").write_bytes(lock.to_json_bytes())
    (repo / ".spaex/constitution.d" / _MOL_FILE).mkdir(parents=True)

    rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    out = capsys.readouterr().out

    assert rc == 0
    payload = json.loads(out)
    assert payload["constitution"] is None
    molecule = payload["molecules"][0]
    assert molecule["atoms"] == {
        "behavior_fragments": [],
        "composed_artifacts": [],
        "files": ["flake.nix"],
    }


def test_status_empty_atom_buckets_reported_explicitly(tmp_path: Path, capsys) -> None:
    """A molecule contributing nothing observable still reports empty lists, not omission."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    _write_manifest(
        repo,
        compounds=[
            {
                "source": "https://github.com/example/atoms",
                "revision": _REV,
                "molecules": [_MOL_BEHAVIOR],
            }
        ],
    )
    lock = InstallLock(
        "4",
        "g_20260101T000000Z_0000",
        (
            MoleculeEntry(
                id=_MOL_BEHAVIOR,
                source="https://github.com/example/atoms",
                revision=_REV,
                paths=(),
            ),
        ),
    )
    (repo / ".spaex").mkdir(exist_ok=True)
    (repo / ".spaex/install.lock").write_bytes(lock.to_json_bytes())

    rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    out = capsys.readouterr().out

    assert rc == 0
    payload = json.loads(out)
    molecule = payload["molecules"][0]
    assert "atoms" in molecule
    assert molecule["atoms"] == {
        "behavior_fragments": [],
        "composed_artifacts": [],
        "files": [],
    }


def test_status_json_is_byte_identical_across_runs(tmp_path: Path, capsys) -> None:
    """SC-004: `--format json` is a deterministic, reproducible contract."""
    repo = _make_full_fixture(tmp_path)

    first_rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    first = capsys.readouterr().out
    second_rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    second = capsys.readouterr().out

    assert first_rc == second_rc == 0
    json.loads(first)
    json.loads(second)
    assert first == second


def test_status_json_has_no_machine_specific_values(tmp_path: Path, capsys, monkeypatch) -> None:
    """FR-013: no absolute path, `~`-path, timestamp, or host/user name leaks."""
    repo = _make_full_fixture(tmp_path)

    monkeypatch.setattr(getpass, "getuser", lambda: "spaex-test-user")
    monkeypatch.setattr(socket, "gethostname", lambda: "spaex-test-host")

    rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    out = capsys.readouterr().out

    assert rc == 0
    assert str(repo) not in out
    assert not re.search(r"\d{4}-\d{2}-\d{2}", out)
    assert not re.search(r"\d{8}T\d{6}Z", out)
    assert "spaex-test-user" not in out
    assert "spaex-test-host" not in out

    payload = json.loads(out)
    for molecule in payload["molecules"]:
        for path in molecule["atoms"]["composed_artifacts"]:
            _assert_repo_relative_posix_path(path)
        for path in molecule["atoms"]["files"]:
            _assert_repo_relative_posix_path(path)


def test_status_json_is_versioned_and_sorted(tmp_path: Path, capsys) -> None:
    """FR-013: `format_version` is present and every documented list is sorted."""
    repo = _make_full_fixture(tmp_path)

    main(["--repo-root", str(repo), "status", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["format_version"] == 1

    molecule_ids = [m["molecule_id"] for m in payload["molecules"]]
    assert molecule_ids == sorted(molecule_ids)
    for molecule in payload["molecules"]:
        atoms = molecule["atoms"]
        assert atoms["behavior_fragments"] == sorted(atoms["behavior_fragments"])
        assert atoms["composed_artifacts"] == sorted(atoms["composed_artifacts"])
        assert atoms["files"] == sorted(atoms["files"])

    constitution = payload["constitution"]
    assert constitution["contributing_molecules"] == sorted(constitution["contributing_molecules"])
    assert constitution["project_local_fragment_ids"] == sorted(
        constitution["project_local_fragment_ids"]
    )
