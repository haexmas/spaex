"""Unit tests for `path_owners` (Spec 028 T010, research.md R2 addendum)."""

from __future__ import annotations

from spaex.model.install_lock import InstallLock, MoleculeEntry, path_owners


def test_single_owner_path() -> None:
    """A path recorded by only one molecule maps to a one-element tuple."""
    lock = InstallLock(
        "4",
        "g_20260101T000000Z_0000",
        (
            MoleculeEntry(
                id="com.example.alpha",
                source="https://github.com/example/alpha",
                revision="1" * 40,
                paths=(".spaex/cmd.md",),
            ),
        ),
    )

    assert path_owners(lock) == {".spaex/cmd.md": ("com.example.alpha",)}


def test_shared_path_lists_every_owner() -> None:
    """A path recorded by several molecules (e.g. .spaex/constitution.md) lists all owners."""
    lock = InstallLock(
        "4",
        "g_20260101T000000Z_0000",
        (
            MoleculeEntry(
                id="com.example.alpha",
                source="https://github.com/example/alpha",
                revision="1" * 40,
                paths=(".spaex/constitution.md",),
            ),
            MoleculeEntry(
                id="com.example.beta",
                source="https://github.com/example/beta",
                revision="2" * 40,
                paths=(".spaex/constitution.md",),
            ),
        ),
    )

    assert path_owners(lock) == {
        ".spaex/constitution.md": ("com.example.alpha", "com.example.beta")
    }


def test_empty_lock_has_no_owners() -> None:
    """An empty install lock owns no paths."""
    lock = InstallLock("4", "g_20260101T000000Z_0000", ())

    assert path_owners(lock) == {}
