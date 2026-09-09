"""T051 — unit tests for the D11 two-step lookup in constitution/resolve.py."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from spaex.constitution.resolve import resolve_constitution_contributions
from spaex.migrate.transform import clone_dir
from spaex.model.consumer_manifest import CompoundEntry, ConfigEntry, ConsumerManifest
from spaex.util.errors import (
    AtomIdCollisionError,
    ContributionFileNotFoundError,
    MissingAtomManifestError,
    MissingPublisherManifestError,
    MoleculeTreeExtractionError,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "haex-test@example.com")
    _git(root, "config", "user.name", "haex-test")
    _git(root, "config", "commit.gpgsign", "false")


def _publish(
    publisher: Path, publisher_manifest: dict, molecules: dict[str, tuple[dict, bytes]]
) -> str:
    """Write a publisher root manifest plus one directory per molecule, then commit."""
    publisher.mkdir(parents=True, exist_ok=True)
    _init_repo(publisher)
    (publisher / "manifest.json").write_text(json.dumps(publisher_manifest, sort_keys=True))
    for path, (molecule_manifest, body) in molecules.items():
        molecule_dir = publisher / path
        molecule_dir.mkdir(parents=True, exist_ok=True)
        (molecule_dir / "manifest.json").write_text(json.dumps(molecule_manifest, sort_keys=True))
        if body is not None:
            (molecule_dir / "constitution.md").write_bytes(body)
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "publish")
    return _git(publisher, "rev-parse", "HEAD")


def _clone(state_root: Path, canonical: str, publisher: Path) -> None:
    target = clone_dir(state_root, canonical)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, target)


def _manifest(compounds: list[CompoundEntry]) -> ConsumerManifest:
    return ConsumerManifest(
        spaex_version="4",
        identity="com.github.example.consumer",
        compounds=tuple(compounds),
    )


def test_publisher_key_atom_id_mismatch(tmp_path: Path) -> None:
    canonical = "https://github.com/example/publisher"
    publisher = tmp_path / "publisher"
    molecule_key = "com.github.example.publisher.constitution"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_key: {"path": "c", "version": "1.0.0"}},
        },
        {
            "c": (
                {
                    "spaex_version": "4",
                    "id": "com.github.example.publisher.wrong-id",
                    "version": "1.0.0",
                    "priority": 100,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"body",
            )
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    manifest = _manifest(
        [
            CompoundEntry(
                source=canonical,
                revision=sha,
                molecules=("com.github.example.publisher.constitution",),
            )
        ]
    )
    with pytest.raises(MissingAtomManifestError):
        resolve_constitution_contributions(manifest, state_root)


def test_version_mismatch(tmp_path: Path) -> None:
    canonical = "https://github.com/example/publisher"
    publisher = tmp_path / "publisher"
    molecule_id = "com.github.example.publisher.constitution"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_id: {"path": "c", "version": "2.0.0"}},
        },
        {
            "c": (
                {
                    "spaex_version": "4",
                    "id": molecule_id,
                    "version": "1.0.0",
                    "priority": 100,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"body",
            )
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    manifest = _manifest(
        [CompoundEntry(source=canonical, revision=sha, molecules=(molecule_id,))]
    )
    with pytest.raises(MissingAtomManifestError):
        resolve_constitution_contributions(manifest, state_root)


def test_atom_not_declared_by_publisher(tmp_path: Path) -> None:
    canonical = "https://github.com/example/publisher"
    publisher = tmp_path / "publisher"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {
                "com.github.example.publisher.other": {"path": "other", "version": "1.0.0"}
            },
        },
        {
            "other": (
                {
                    "spaex_version": "4",
                    "id": "com.github.example.publisher.other",
                    "version": "1.0.0",
                    "priority": 100,
                    "atoms": {"spec": ["spec.md"]},
                },
                None,
            )
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    manifest = _manifest(
        [
            CompoundEntry(
                source=canonical,
                revision=sha,
                molecules=("com.github.example.publisher.constitution",),
            )
        ]
    )
    with pytest.raises(MissingAtomManifestError):
        resolve_constitution_contributions(manifest, state_root)


def test_atom_id_collision_across_two_source_revision_pairs(tmp_path: Path) -> None:
    molecule_id = "com.github.example.publisher.constitution"

    canonical_a = "https://github.com/example/publisher-a"
    publisher_a = tmp_path / "publisher-a"
    sha_a = _publish(
        publisher_a,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_id: {"path": "c", "version": "1.0.0"}},
        },
        {
            "c": (
                {
                    "spaex_version": "4",
                    "id": molecule_id,
                    "version": "1.0.0",
                    "priority": 100,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"body-a",
            )
        },
    )
    canonical_b = "https://github.com/example/publisher-b"
    publisher_b = tmp_path / "publisher-b"
    sha_b = _publish(
        publisher_b,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_id: {"path": "c", "version": "1.0.0"}},
        },
        {
            "c": (
                {
                    "spaex_version": "4",
                    "id": molecule_id,
                    "version": "1.0.0",
                    "priority": 100,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"body-b",
            )
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical_a, publisher_a)
    _clone(state_root, canonical_b, publisher_b)

    manifest = _manifest(
        [
            CompoundEntry(source=canonical_a, revision=sha_a, molecules=(molecule_id,)),
            CompoundEntry(source=canonical_b, revision=sha_b, molecules=(molecule_id,)),
        ]
    )
    with pytest.raises(AtomIdCollisionError):
        resolve_constitution_contributions(manifest, state_root)


def test_same_atom_same_source_revision_is_not_a_collision(tmp_path: Path) -> None:
    """Two compounds[] entries pointing at the SAME (source, revision) and molecule-id is fine."""
    canonical = "https://github.com/example/publisher"
    molecule_id = "com.github.example.publisher.constitution"
    publisher = tmp_path / "publisher"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_id: {"path": "c", "version": "1.0.0"}},
        },
        {
            "c": (
                {
                    "spaex_version": "4",
                    "id": molecule_id,
                    "version": "1.0.0",
                    "priority": 100,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"body",
            )
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    manifest = _manifest(
        [
            CompoundEntry(source=canonical, revision=sha, molecules=(molecule_id,)),
            CompoundEntry(source=canonical, revision=sha, molecules=(molecule_id,)),
        ]
    )
    contributions = resolve_constitution_contributions(manifest, state_root)
    assert len(contributions) == 2
    assert all(c.body == b"body" for c in contributions)


def test_non_contribution_atom_is_filtered_not_errored(tmp_path: Path) -> None:
    canonical = "https://github.com/example/publisher"
    molecule_id = "com.github.example.publisher.profile"
    publisher = tmp_path / "publisher"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_id: {"path": "c", "version": "1.0.0"}},
        },
        {},
    )
    (publisher / "c").mkdir()
    (publisher / "c" / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": molecule_id,
                "version": "1.0.0",
                "priority": 100,
                "atoms": {"skills": ["skills.md"]},
            }
        )
    )
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "amend: non-contribution molecule")
    sha = _git(publisher, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    manifest = _manifest([CompoundEntry(source=canonical, revision=sha, molecules=(molecule_id,))])
    assert resolve_constitution_contributions(manifest, state_root) == []


def test_effective_priority_overrides_lexical_molecule_order(tmp_path: Path) -> None:
    """Order contributions by manifest priority and per-molecule overrides."""
    canonical = "https://github.com/example/publisher"
    ids = {
        suffix: f"com.github.example.publisher.{suffix}"
        for suffix in ("alpha", "beta", "gamma")
    }
    publisher = tmp_path / "publisher"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {
                ids["alpha"]: {"path": "alpha", "version": "1.0.0"},
                ids["beta"]: {"path": "beta", "version": "1.0.0"},
                ids["gamma"]: {"path": "gamma", "version": "1.0.0"},
            },
        },
        {
            "alpha": (
                {
                    "spaex_version": "4",
                    "id": ids["alpha"],
                    "version": "1.0.0",
                    "priority": 200,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"alpha",
            ),
            "beta": (
                {
                    "spaex_version": "4",
                    "id": ids["beta"],
                    "version": "1.0.0",
                    "priority": 100,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"beta",
            ),
            "gamma": (
                {
                    "spaex_version": "4",
                    "id": ids["gamma"],
                    "version": "1.0.0",
                    "priority": 300,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"gamma",
            ),
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    manifest = _manifest(
        [
            CompoundEntry(
                source=canonical,
                revision=sha,
                molecules=(ids["alpha"], ids["beta"], ids["gamma"]),
                config={ids["gamma"]: ConfigEntry(priority=0)},
            )
        ]
    )

    contributions = resolve_constitution_contributions(manifest, state_root)

    assert [contribution.source.id for contribution in contributions] == [
        ids["gamma"],
        ids["beta"],
        ids["alpha"],
    ]


def test_canonicalization_idempotence_refusal(tmp_path: Path) -> None:
    """resolve.py defensively re-validates source canonicality (D3, contract text)."""
    non_canonical = "https://github.com/example/publisher.git"
    manifest = _manifest(
        [CompoundEntry(source=non_canonical, revision="0" * 40, molecules=("com.example.atom",))]
    )
    with pytest.raises(ValueError):
        resolve_constitution_contributions(manifest, tmp_path / "state")


def test_publisher_manifest_not_found(tmp_path: Path) -> None:
    canonical = "https://github.com/example/publisher"
    publisher = tmp_path / "publisher"
    publisher.mkdir()
    _init_repo(publisher)
    (publisher / "README.md").write_text("no manifest here")
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "no manifest")
    sha = _git(publisher, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    manifest = _manifest(
        [CompoundEntry(source=canonical, revision=sha, molecules=("com.example.publisher.atom",))]
    )
    with pytest.raises(MissingPublisherManifestError):
        resolve_constitution_contributions(manifest, state_root)


def test_constitution_path_symlink_escape_is_refused(tmp_path: Path) -> None:
    """FR-018 — a constitution path resolving outside cache_dir raises MoleculeTreeExtractionError.

    Pre-populates the materialized cache directory so `get_or_extract` takes its
    cache-hit fast path, then plants a symlinked `constitution.md` inside that
    cache directory pointing at a file outside it. Exercises T018's direct-read
    containment check, not T004's archive-member validation (no `git archive`
    invocation reaches disk).
    """
    canonical = "https://github.com/example/publisher"
    molecule_key = "com.github.example.publisher.constitution"
    publisher = tmp_path / "publisher"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_key: {"path": "c", "version": "1.0.0"}},
        },
        {
            "c": (
                {
                    "spaex_version": "4",
                    "id": molecule_key,
                    "version": "1.0.0",
                    "priority": 100,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"body",
            )
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)

    source_digest = clone_dir(state_root, canonical).name
    cache_dir = state_root / "molecule-store" / source_digest / sha / "c"
    cache_dir.mkdir(parents=True)
    (cache_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": molecule_key,
                "version": "1.0.0",
                "priority": 100,
                "atoms": {"constitution": ["constitution.md"]},
            },
            sort_keys=True,
        )
    )
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"forbidden")
    (cache_dir / "constitution.md").symlink_to(outside)

    manifest = _manifest(
        [
            CompoundEntry(
                source=canonical,
                revision=sha,
                molecules=(molecule_key,),
            )
        ]
    )
    with pytest.raises(MoleculeTreeExtractionError):
        resolve_constitution_contributions(manifest, state_root)


def test_missing_molecule_tree_preserves_manifest_path_in_context(tmp_path: Path) -> None:
    canonical = "https://github.com/example/publisher"
    molecule_key = "com.github.example.publisher.constitution"
    publisher = tmp_path / "publisher"
    publisher.mkdir()
    _init_repo(publisher)
    (publisher / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "publisher": "com.github.example.publisher",
                "molecules": {molecule_key: {"path": "c", "version": "1.0.0"}},
            },
            sort_keys=True,
        )
    )
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "publish root manifest only")
    sha = _git(publisher, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)
    manifest = _manifest(
        [CompoundEntry(source=canonical, revision=sha, molecules=(molecule_key,))]
    )

    with pytest.raises(MissingAtomManifestError) as exc_info:
        resolve_constitution_contributions(manifest, state_root)

    assert exc_info.value.context["path"] == "c/manifest.json"


def test_non_file_molecule_manifest_is_typed(tmp_path: Path) -> None:
    canonical = "https://github.com/example/publisher"
    molecule_key = "com.github.example.publisher.constitution"
    publisher = tmp_path / "publisher"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_key: {"path": "c", "version": "1.0.0"}},
        },
        {
            "c": (
                {
                    "spaex_version": "4",
                    "id": molecule_key,
                    "version": "1.0.0",
                    "priority": 100,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"body",
            )
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)
    cache_dir = state_root / "molecule-store" / clone_dir(state_root, canonical).name / sha / "c"
    (cache_dir / "manifest.json").mkdir(parents=True)

    manifest = _manifest(
        [CompoundEntry(source=canonical, revision=sha, molecules=(molecule_key,))]
    )
    with pytest.raises(MissingAtomManifestError):
        resolve_constitution_contributions(manifest, state_root)


def test_non_file_constitution_path_is_typed(tmp_path: Path) -> None:
    canonical = "https://github.com/example/publisher"
    molecule_key = "com.github.example.publisher.constitution"
    publisher = tmp_path / "publisher"
    sha = _publish(
        publisher,
        {
            "spaex_version": "4",
            "publisher": "com.github.example.publisher",
            "molecules": {molecule_key: {"path": "c", "version": "1.0.0"}},
        },
        {
            "c": (
                {
                    "spaex_version": "4",
                    "id": molecule_key,
                    "version": "1.0.0",
                    "priority": 100,
                    "atoms": {"constitution": ["constitution.md"]},
                },
                b"body",
            )
        },
    )
    state_root = tmp_path / "state"
    _clone(state_root, canonical, publisher)
    cache_dir = state_root / "molecule-store" / clone_dir(state_root, canonical).name / sha / "c"
    cache_dir.mkdir(parents=True)
    (cache_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": molecule_key,
                "version": "1.0.0",
                "priority": 100,
                "atoms": {"constitution": ["constitution.md"]},
            },
            sort_keys=True,
        )
    )
    (cache_dir / "constitution.md").mkdir()

    manifest = _manifest(
        [CompoundEntry(source=canonical, revision=sha, molecules=(molecule_key,))]
    )
    with pytest.raises(ContributionFileNotFoundError):
        resolve_constitution_contributions(manifest, state_root)
