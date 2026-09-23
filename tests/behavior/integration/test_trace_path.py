"""`spaex trace <path>` end-to-end (Spec 028 T029, contracts/status-and-trace-cli.md).

No git/molecule resolution is needed here: `spaex trace` reads
`.spaex/manifest.json` and `.spaex/install.lock` directly off disk, so
fixtures are hand-written, mirroring `test_provenance_trace.py`'s style.
"""

from __future__ import annotations

import getpass
import json
import re
import socket
from pathlib import Path

from spaex.cli.main import main
from spaex.model.install_lock import InstallLock, MoleculeEntry

_SOURCE = "https://github.com/example/atoms"
_REV_NIX_PYTHON = "a" * 40
_REV_AST_GREP = "b" * 40
_REV_GENERAL_CODING = "c" * 40


def _write_manifest(repo: Path) -> None:
    (repo / ".spaex").mkdir(parents=True, exist_ok=True)
    (repo / ".spaex/manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.trace-consumer",
                "compounds": [],
            }
        ),
        encoding="utf-8",
    )


def _make_fixture(tmp_path: Path) -> Path:
    """One sole-owner file, and `.spaex/constitution.md` shared by two molecules."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    _write_manifest(repo)
    lock = InstallLock(
        "4",
        "g_20260101T000000Z_0000",
        (
            MoleculeEntry(
                id="com.example.atoms.ast-grep",
                source=_SOURCE,
                revision=_REV_AST_GREP,
                paths=(".spaex/constitution.md",),
            ),
            MoleculeEntry(
                id="com.example.atoms.general-coding",
                source=_SOURCE,
                revision=_REV_GENERAL_CODING,
                paths=(".spaex/constitution.md",),
            ),
            MoleculeEntry(
                id="com.example.atoms.nix-python",
                source=_SOURCE,
                revision=_REV_NIX_PYTHON,
                paths=("flake.nix",),
            ),
        ),
    )
    (repo / ".spaex/install.lock").write_bytes(lock.to_json_bytes())
    return repo


def test_single_owner_file_text(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(["--repo-root", str(repo), "trace", "flake.nix"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Path: flake.nix" in out
    assert "Owner:" in out
    assert f"com.example.atoms.nix-python@{_REV_NIX_PYTHON[:8]}" in out
    assert "(recorded in .spaex/install.lock)" in out


def test_shared_constitution_path_text(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(["--repo-root", str(repo), "trace", ".spaex/constitution.md"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Path: .spaex/constitution.md" in out
    assert "Owners (2):" in out
    assert "com.example.atoms.ast-grep" in out
    assert "com.example.atoms.general-coding" in out
    assert "For clause-level provenance, run `spaex constitution trace <query>`." in out


def test_directory_query(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    _write_manifest(repo)
    lock = InstallLock(
        "4",
        "g_20260101T000000Z_0000",
        (
            MoleculeEntry(
                id="com.example.atoms.docs",
                source=_SOURCE,
                revision=_REV_NIX_PYTHON,
                paths=(".spaex/docs/one.md", ".spaex/docs/two.md"),
            ),
        ),
    )
    (repo / ".spaex/install.lock").write_bytes(lock.to_json_bytes())

    rc = main(["--repo-root", str(repo), "trace", ".spaex/docs", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["kind"] == "directory"
    assert [m["path"] for m in payload["matches"]] == [".spaex/docs/one.md", ".spaex/docs/two.md"]


def test_repository_root_queries_match_all_recorded_paths(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)

    for query in (".", str(repo)):
        rc = main(["--repo-root", str(repo), "trace", query, "--format", "json"])
        out = capsys.readouterr().out
        assert rc == 0, f"query {query!r} failed: {out}"
        payload = json.loads(out)
        assert payload["query"] == "."
        assert payload["kind"] == "directory"
        assert [match["path"] for match in payload["matches"]] == [
            ".spaex/constitution.md",
            "flake.nix",
        ]


def test_no_match_text(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(["--repo-root", str(repo), "trace", "README.md"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "No molecule is recorded for README.md." in out
    assert "Hand-written files and files created by a molecule's install_hook" in out
    assert "not\ntracked by spaex." in out


def test_no_match_json(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(["--repo-root", str(repo), "trace", "README.md", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 1
    payload = json.loads(out)
    assert payload["matches"] == []
    assert payload["error"] == "no molecule is recorded for README.md"


def test_all_four_path_forms_agree(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    forms = [
        "flake.nix",
        str(repo / "flake.nix"),
        "./flake.nix",
        "flake.nix/",
    ]
    for form in forms:
        rc = main(["--repo-root", str(repo), "trace", form, "--format", "json"])
        out = capsys.readouterr().out
        assert rc == 0, f"form {form!r} failed: {out}"
        payload = json.loads(out)
        assert payload["query"] == "flake.nix"
        assert payload["matches"][0]["path"] == "flake.nix"


def test_path_outside_repository_exits_64(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    outside = tmp_path.parent / "elsewhere.txt"
    rc = main(["--repo-root", str(repo), "trace", str(outside)])
    assert rc == 64


def test_json_format_shape(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(["--repo-root", str(repo), "trace", "flake.nix", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["format_version"] == 1
    assert payload["query"] == "flake.nix"
    assert payload["kind"] == "file"
    assert payload["error"] is None
    match = payload["matches"][0]
    assert match["constitution_trace_hint"] is False
    owner = match["owners"][0]
    assert owner == {
        "molecule_id": "com.example.atoms.nix-python",
        "source": _SOURCE,
        "revision": _REV_NIX_PYTHON,
    }


def test_trace_json_is_byte_identical_across_runs(tmp_path: Path, capsys) -> None:
    """SC-004: `--format json` is a deterministic, reproducible contract."""
    repo = _make_fixture(tmp_path)

    main(["--repo-root", str(repo), "trace", "flake.nix", "--format", "json"])
    first = capsys.readouterr().out
    main(["--repo-root", str(repo), "trace", "flake.nix", "--format", "json"])
    second = capsys.readouterr().out

    assert first == second


def test_trace_json_has_no_machine_specific_values(tmp_path: Path, capsys) -> None:
    """FR-013: no absolute path, `~`-path, timestamp, or host/user name leaks."""
    repo = _make_fixture(tmp_path)

    main(["--repo-root", str(repo), "trace", ".spaex/constitution.md", "--format", "json"])
    out = capsys.readouterr().out

    assert str(repo) not in out
    assert "~" not in out
    assert not re.search(r"\d{4}-\d{2}-\d{2}", out)
    assert not re.search(r"\d{8}T\d{6}Z", out)
    assert socket.gethostname() not in out
    assert getpass.getuser() not in out


def test_trace_json_is_versioned_and_matches_sorted_by_path(tmp_path: Path, capsys) -> None:
    """FR-013: `format_version` is present and a directory query's matches are sorted."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    _write_manifest(repo)
    lock = InstallLock(
        "4",
        "g_20260101T000000Z_0000",
        (
            MoleculeEntry(
                id="com.example.atoms.docs",
                source=_SOURCE,
                revision=_REV_NIX_PYTHON,
                paths=(".spaex/docs/one.md", ".spaex/docs/two.md", ".spaex/docs/zzz.md"),
            ),
        ),
    )
    (repo / ".spaex/install.lock").write_bytes(lock.to_json_bytes())

    rc = main(["--repo-root", str(repo), "trace", ".spaex/docs", "--format", "json"])
    out = capsys.readouterr().out

    assert rc == 0
    payload = json.loads(out)
    assert payload["format_version"] == 1
    paths = [m["path"] for m in payload["matches"]]
    assert paths == sorted(paths)
