"""T091 — end-to-end: adopt an atoms-repo molecule and install it (SC-001).

Closes SC-001: a molecule published by the ``haexmas/atoms`` repository
installs into a v3-adopted consumer through a single `haex add` call
(which delegates to `haex install`), with the molecule's contributed
files landing under `.haex-hive/`.

Hermetic by design: the fixture stages a bare git clone at the exact
``$HAEX_HIVE_STATE/repos/<sha256(url)[:16]>/`` path the tool would use
for the real ``https://github.com/haexmas/atoms`` URL. This lets
`haex add` resolve the SHA against the local clone instead of the
network, so the test does not depend on GitHub availability.

The real atoms repo at HEAD ``ff6fda21…`` today declares a v2
publisher-root ``manifest.json`` (with `atoms:` instead of `molecules:`)
even though the ``graphify-first-authoring`` molecule itself is v3.
A network `haex add` against the real remote would therefore refuse
with `publisher-manifest-invalid` at the publisher gate; migrating the
publisher-root manifest to v3 is a follow-up on the atoms repo itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from haex_hive.model.install_lock import InstallLock

_ATOMS_URL = "https://github.com/haexmas/atoms"
_GRAPHIFY_ID = "com.github.haexmas.atoms.graphify-first-authoring"


@pytest.fixture
def atoms_repo_fixture(tmp_path: Path, haex_add_helpers):
    """Bare clone that mimics the atoms repo's v3-throughout shape."""
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _GRAPHIFY_ID: {
                "path": "graphify-first-authoring",
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"constitution": ["constitution.md", "annex.md"]},
            },
        },
        publisher="com.github.haexmas.atoms",
        name="atoms",
        canonical=_ATOMS_URL,
    )
    assert canonical == _ATOMS_URL
    return {"canonical": canonical, "head": head, "state_root": state_root}


def test_add_graphify_from_atoms_repo_installs_end_to_end(
    tmp_path: Path,
    atoms_repo_fixture: dict,
    monkeypatch: pytest.MonkeyPatch,
    haex_add_helpers,
) -> None:
    """One `haex add` on the atoms repo lands the graphify constitution."""
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    rc = haex_add_helpers["run_add"](
        consumer,
        atoms_repo_fixture["state_root"],
        monkeypatch,
        source_url=atoms_repo_fixture["canonical"],
        molecule_ids=_GRAPHIFY_ID,
        revision=atoms_repo_fixture["head"],
    )
    assert rc == 0

    # `.haex-hive.json` records the adopted molecule at the pinned SHA
    manifest = json.loads((consumer / ".haex-hive.json").read_text())
    assert manifest["compounds"] == [
        {
            "source": _ATOMS_URL,
            "revision": atoms_repo_fixture["head"],
            "molecules": [_GRAPHIFY_ID],
        }
    ]

    # The constitution file lands under .haex-hive/
    published_constitution = consumer / ".haex-hive" / "constitution.md"
    assert published_constitution.exists()
    assert published_constitution.read_bytes() == (
        f"# {_GRAPHIFY_ID} constitution constitution.md\n\n"
        f"# {_GRAPHIFY_ID} constitution annex.md\n".encode()
    )

    # install.lock records exactly one molecule with the exact
    # (source, revision, paths) triple.
    install_lock = InstallLock.from_json(
        (consumer / ".haex-hive" / "install.lock").read_bytes()
    )
    assert len(install_lock.molecules) == 1
    entry = install_lock.molecules[0]
    assert entry.id == _GRAPHIFY_ID
    assert entry.source == _ATOMS_URL
    assert entry.revision == atoms_repo_fixture["head"]
    assert entry.paths == (".haex-hive/constitution.md",)


def test_second_add_invocation_is_idempotent(
    tmp_path: Path,
    atoms_repo_fixture: dict,
    monkeypatch: pytest.MonkeyPatch,
    haex_add_helpers,
) -> None:
    """A repeat `haex add` at the same SHA is a no-op end to end."""
    consumer = haex_add_helpers["make_consumer"](tmp_path)

    first_rc = haex_add_helpers["run_add"](
        consumer,
        atoms_repo_fixture["state_root"],
        monkeypatch,
        source_url=atoms_repo_fixture["canonical"],
        molecule_ids=_GRAPHIFY_ID,
        revision=atoms_repo_fixture["head"],
    )
    assert first_rc == 0
    first_lock_bytes = (consumer / ".haex-hive" / "install.lock").read_bytes()

    rc = haex_add_helpers["run_add"](
        consumer,
        atoms_repo_fixture["state_root"],
        monkeypatch,
        source_url=atoms_repo_fixture["canonical"],
        molecule_ids=_GRAPHIFY_ID,
        revision=atoms_repo_fixture["head"],
    )
    assert rc == 0
    second_lock_bytes = (consumer / ".haex-hive" / "install.lock").read_bytes()
    assert second_lock_bytes == first_lock_bytes, (
        "re-adding the same molecule at the same SHA must not allocate a "
        "new generation"
    )
