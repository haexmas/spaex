"""T044/T024 - end-to-end `haex migrate` on a fixture v2 repo.

Originally Spec 013 T044 (v2->v3 chain). Under Spec 014 (T024) the chain
extends through v3->v4, so the proposals are now v4 shape and the consumer
sidecar filename becomes `.spaex.json.migrated`.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from spaex.cli import migrate as migrate_cli


def _make_v2_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".haex-hive.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "2",
                "identity": "com.example.project",
                "atoms": [
                    {
                        "source": "https://example.com/publisher",
                        "revision": "a" * 40,
                        "includes": [
                            "com.example.publisher.hello",
                            "com.example.publisher.world",
                        ],
                    }
                ],
            },
            indent=2,
        )
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "haex_hive_version": "2",
                "publisher": "com.example.publisher",
                "atoms": {
                    "com.example.publisher.hello": {
                        "path": "hello",
                        "version": "1.0.0",
                    },
                    "com.example.publisher.world": {
                        "path": "world",
                        "version": "2.0.0",
                    },
                },
            },
            indent=2,
        )
    )
    for name, contribution in (
        ("hello", ("constitution", "constitution.md")),
        ("world", ("skills", "skill.md")),
    ):
        mol_dir = root / name
        mol_dir.mkdir()
        category, path = contribution
        (mol_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "haex_hive_version": "2",
                    "id": f"com.example.publisher.{name}",
                    "version": "1.0.0" if name == "hello" else "2.0.0",
                    "priority": 100,
                    "contributes": {category: path},
                },
                indent=2,
            )
        )
        (mol_dir / path).write_text(f"# {name} {category}\n")


def test_fixture_v2_repo_yields_v4_proposals_for_every_manifest(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _make_v2_repo(repo)

    ns = SimpleNamespace(repo_root=str(repo), dry_run=False, check=False)
    rc = migrate_cli.run(ns)
    assert rc == 0

    consumer_proposal = repo / ".spaex.json.migrated"
    root_proposal = repo / "manifest.json.migrated"
    hello_proposal = repo / "hello" / "manifest.json.migrated"
    world_proposal = repo / "world" / "manifest.json.migrated"
    for path in (consumer_proposal, root_proposal, hello_proposal, world_proposal):
        assert path.exists(), f"expected proposal at {path}"

    consumer_v4 = json.loads(consumer_proposal.read_text())
    assert consumer_v4["spaex_version"] == "4"
    assert "haex_hive_version" not in consumer_v4
    assert consumer_v4["compounds"][0]["molecules"] == [
        "com.example.publisher.hello",
        "com.example.publisher.world",
    ]

    root_v4 = json.loads(root_proposal.read_text())
    assert root_v4["spaex_version"] == "4"
    assert set(root_v4["molecules"].keys()) == {
        "com.example.publisher.hello",
        "com.example.publisher.world",
    }

    hello_v4 = json.loads(hello_proposal.read_text())
    assert hello_v4["spaex_version"] == "4"
    assert hello_v4["atoms"] == {"constitution": ["constitution.md"]}
    world_v4 = json.loads(world_proposal.read_text())
    assert world_v4["spaex_version"] == "4"
    assert world_v4["atoms"] == {"skills": ["skill.md"]}


def test_originals_are_never_touched(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _make_v2_repo(repo)
    originals = {
        path: path.read_bytes()
        for path in (
            repo / ".haex-hive.json",
            repo / "manifest.json",
            repo / "hello" / "manifest.json",
            repo / "world" / "manifest.json",
        )
    }

    ns = SimpleNamespace(repo_root=str(repo), dry_run=False, check=False)
    migrate_cli.run(ns)

    for path, before in originals.items():
        assert path.read_bytes() == before, f"{path} was modified"
