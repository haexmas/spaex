"""Unit tests for `flatten_compound_pins` (Spec 028 T008, research.md R5 addendum)."""

from __future__ import annotations

from spaex.model.consumer_manifest import (
    CompoundEntry,
    ConsumerManifest,
    flatten_compound_pins,
)


def _manifest(compounds: list[CompoundEntry]) -> ConsumerManifest:
    return ConsumerManifest(
        spaex_version="4",
        identity="com.github.example.consumer",
        compounds=tuple(compounds),
    )


def test_flattens_molecules_from_every_compound() -> None:
    """Molecule ids from every compound end up in the same flat map."""
    manifest = _manifest(
        [
            CompoundEntry(
                source="https://github.com/example/one",
                revision="1" * 40,
                molecules=("com.example.one.alpha", "com.example.one.beta"),
            ),
            CompoundEntry(
                source="https://github.com/example/two",
                revision="2" * 40,
                molecules=("com.example.two.gamma",),
            ),
        ]
    )

    pins = flatten_compound_pins(manifest)

    assert pins == {
        "com.example.one.alpha": ("https://github.com/example/one", "1" * 40),
        "com.example.one.beta": ("https://github.com/example/one", "1" * 40),
        "com.example.two.gamma": ("https://github.com/example/two", "2" * 40),
    }


def test_later_compound_wins_on_duplicated_molecule_id() -> None:
    """A molecule id repeated across compounds resolves to the later pin."""
    manifest = _manifest(
        [
            CompoundEntry(
                source="https://github.com/example/old",
                revision="1" * 40,
                molecules=("com.example.shared",),
            ),
            CompoundEntry(
                source="https://github.com/example/new",
                revision="2" * 40,
                molecules=("com.example.shared",),
            ),
        ]
    )

    pins = flatten_compound_pins(manifest)

    assert pins == {
        "com.example.shared": ("https://github.com/example/new", "2" * 40),
    }
