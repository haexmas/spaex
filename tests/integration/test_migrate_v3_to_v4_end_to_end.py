"""T024 - end-to-end `haex migrate` v3 -> v4 on a fixture v3 repo (Spec 014).

Complements `test_migrate_end_to_end.py` (which chains a v2 fixture through
v2 -> v3 -> v4). Here the input is v3-native, exercising the v3 -> v4 leg in
isolation.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from spaex.cli import migrate as migrate_cli


def _make_v3_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".haex-hive.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "3",
                "identity": "com.example.project",
                "haex_hive_min_version": "3.1.0",
                "compounds": [
                    {
                        "source": "https://example.com/publisher",
                        "revision": "a" * 40,
                        "molecules": ["com.example.publisher.hello"],
                    }
                ],
            },
            indent=2,
        )
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "3",
                "publisher": "com.example.publisher",
                "molecules": {
                    "com.example.publisher.hello": {
                        "path": "hello",
                        "version": "1.0.0",
                    }
                },
            },
            indent=2,
        )
    )
    mol_dir = root / "hello"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "3",
                "id": "com.example.publisher.hello",
                "version": "1.0.0",
                "priority": 100,
                "atoms": {"constitution": ["constitution.md"]},
            },
            indent=2,
        )
    )
    (mol_dir / "constitution.md").write_text("# hello constitution\n")


def test_v3_repo_migrates_to_v4_end_to_end(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _make_v3_repo(repo)

    ns = SimpleNamespace(repo_root=str(repo), dry_run=False, check=False)
    rc = migrate_cli.run(ns)
    assert rc == 0

    consumer_proposal = repo / ".spaex.json.migrated"
    root_proposal = repo / "manifest.json.migrated"
    hello_proposal = repo / "hello" / "manifest.json.migrated"
    for path in (consumer_proposal, root_proposal, hello_proposal):
        assert path.exists(), f"missing proposal at {path}"

    consumer_v4 = json.loads(consumer_proposal.read_text())
    assert consumer_v4["spaex_version"] == "4"
    assert consumer_v4["spaex_min_version"] == "4.1.0"
    assert consumer_v4["compounds"][0]["molecules"] == [
        "com.example.publisher.hello"
    ]
    assert "haex_hive_version" not in consumer_v4
    assert "haex_hive_min_version" not in consumer_v4

    root_v4 = json.loads(root_proposal.read_text())
    assert root_v4["spaex_version"] == "4"
    assert "haex_hive_version" not in root_v4
    assert root_v4["molecules"]["com.example.publisher.hello"]["path"] == "hello"

    hello_v4 = json.loads(hello_proposal.read_text())
    assert hello_v4["spaex_version"] == "4"
    assert "haex_hive_version" not in hello_v4
    assert hello_v4["atoms"] == {"constitution": ["constitution.md"]}


def test_v3_repo_originals_untouched(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _make_v3_repo(repo)
    originals = {
        path: path.read_bytes()
        for path in (
            repo / ".haex-hive.json",
            repo / "manifest.json",
            repo / "hello" / "manifest.json",
        )
    }
    ns = SimpleNamespace(repo_root=str(repo), dry_run=False, check=False)
    migrate_cli.run(ns)
    for path, before in originals.items():
        assert path.read_bytes() == before, f"{path} was modified"


def test_v4_repo_already_at_v4_noop(tmp_path: Path) -> None:
    """A v4-native repo (`.spaex.json` present) reports no-op and writes nothing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project",
                "compounds": [],
            },
            indent=2,
        )
    )
    ns = SimpleNamespace(repo_root=str(repo), dry_run=False, check=False)
    rc = migrate_cli.run(ns)
    assert rc == 0
    assert not (repo / ".spaex.json.migrated").exists()
