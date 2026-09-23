"""`spaex status` drift detection end-to-end (Spec 028 T036, User Story 4).

Each of the four drift cases is seeded independently in its own fixture;
a fifth, fully-consistent fixture confirms an empty `drift` list. Exit
code stays 0 in every case (drift is informational, FR-007).
"""

from __future__ import annotations

import json
from pathlib import Path

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

_SOURCE = "https://github.com/example/atoms"
_REV_A = "1" * 40
_REV_B = "2" * 40


def _write_manifest(repo: Path, *, compounds: list[dict[str, object]]) -> None:
    (repo / ".spaex").mkdir(parents=True, exist_ok=True)
    (repo / ".spaex/manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.drift-consumer",
                "compounds": compounds,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_lock(repo: Path, molecules: tuple[MoleculeEntry, ...]) -> None:
    lock = InstallLock("4", "g_20260101T000000Z_0000", molecules)
    (repo / ".spaex").mkdir(parents=True, exist_ok=True)
    (repo / ".spaex/install.lock").write_bytes(lock.to_json_bytes())


def _drift_by_kind(payload: dict[str, object]) -> dict[str, object]:
    drift = payload["drift"]
    assert isinstance(drift, list)
    return {finding["kind"]: finding for finding in drift}


def test_pinned_not_installed_drift(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    _write_manifest(
        repo,
        compounds=[
            {"source": _SOURCE, "revision": _REV_A, "molecules": ["com.example.atoms.only-pinned"]}
        ],
    )
    _write_lock(repo, ())

    rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    by_kind = _drift_by_kind(payload)
    finding = by_kind["pinned_not_installed"]
    assert finding["molecule_id"] == "com.example.atoms.only-pinned"
    assert finding["pinned"] == {"source": _SOURCE, "revision": _REV_A}
    assert finding["installed"] is None


def test_installed_not_pinned_drift(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    _write_manifest(repo, compounds=[])
    _write_lock(
        repo,
        (
            MoleculeEntry(
                id="com.example.atoms.only-installed",
                source=_SOURCE,
                revision=_REV_A,
                paths=("flake.nix",),
            ),
        ),
    )

    rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    by_kind = _drift_by_kind(payload)
    finding = by_kind["installed_not_pinned"]
    assert finding["molecule_id"] == "com.example.atoms.only-installed"
    assert finding["installed"] == {"source": _SOURCE, "revision": _REV_A}
    assert finding["pinned"] is None


def test_revision_mismatch_drift(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    _write_manifest(
        repo,
        compounds=[
            {"source": _SOURCE, "revision": _REV_A, "molecules": ["com.example.atoms.mismatch"]}
        ],
    )
    _write_lock(
        repo,
        (
            MoleculeEntry(
                id="com.example.atoms.mismatch",
                source=_SOURCE,
                revision=_REV_B,
                paths=("flake.nix",),
            ),
        ),
    )

    rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    by_kind = _drift_by_kind(payload)
    finding = by_kind["revision_mismatch"]
    assert finding["molecule_id"] == "com.example.atoms.mismatch"
    assert finding["pinned"] == {"source": _SOURCE, "revision": _REV_A}
    assert finding["installed"] == {"source": _SOURCE, "revision": _REV_B}


def test_constitution_stale_drift(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    (repo / ".spaex").mkdir()
    _write_manifest(
        repo,
        compounds=[
            {"source": _SOURCE, "revision": _REV_A, "molecules": ["com.example.atoms.behavior"]}
        ],
    )
    _write_lock(
        repo,
        (
            MoleculeEntry(
                id="com.example.atoms.behavior",
                source=_SOURCE,
                revision=_REV_A,
                paths=(".spaex/constitution.md",),
            ),
        ),
    )
    fragment_dir = repo / ".spaex/constitution.d/com.example.atoms.behavior"
    fragment_dir.mkdir(parents=True)
    (fragment_dir / "cmd.md").write_text(
        "---\nid: cmd\nkind: constitution_fragment\natom_source: pkg.tool\n"
        "modality: MUST\n---\n**MUST** do the thing.\n",
        encoding="utf-8",
    )
    # No composed constitution.md at all: fragments present, header missing -> stale.

    rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    by_kind = _drift_by_kind(payload)
    finding = by_kind["constitution_stale"]
    assert finding["molecule_id"] is None
    assert finding["pinned"] is None
    assert finding["installed"] is None


def test_fully_consistent_repository_has_no_drift(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    (repo / ".spaex").mkdir()
    _write_manifest(
        repo,
        compounds=[
            {"source": _SOURCE, "revision": _REV_A, "molecules": ["com.example.atoms.behavior"]}
        ],
    )
    _write_lock(
        repo,
        (
            MoleculeEntry(
                id="com.example.atoms.behavior",
                source=_SOURCE,
                revision=_REV_A,
                paths=(".spaex/constitution.md",),
            ),
        ),
    )
    fragment_dir = repo / ".spaex/constitution.d/com.example.atoms.behavior"
    fragment_dir.mkdir(parents=True)
    fragment_path = fragment_dir / "cmd.md"
    fragment_path.write_text(
        "---\nid: cmd\nkind: constitution_fragment\natom_source: pkg.tool\n"
        "modality: MUST\n---\n**MUST** do the thing.\n",
        encoding="utf-8",
    )
    fragment = BehaviorFragment.from_file(fragment_path, molecule_id="com.example.atoms.behavior")
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
        "## MUST\n"
        f"- Do the thing. _[from `{fragment.scoped_id}`]_\n",
        encoding="utf-8",
    )

    rc = main(["--repo-root", str(repo), "status", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["drift"] == []
    assert payload["constitution"]["stale"] is False


def test_drift_text_rendering_includes_hint(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    _write_manifest(
        repo,
        compounds=[
            {"source": _SOURCE, "revision": _REV_A, "molecules": ["com.example.atoms.only-pinned"]}
        ],
    )
    _write_lock(repo, ())

    rc = main(["--repo-root", str(repo), "status"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Drift:" in out
    assert "com.example.atoms.only-pinned: pinned but not installed" in out
    assert "run `spaex install` to reconcile" in out
