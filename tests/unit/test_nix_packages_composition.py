"""Spec 027 research.md §2 — deterministic nix_packages composition."""

from __future__ import annotations

from spaex.install.nix_packages import PackageFragment, compose


def test_compose_returns_none_for_no_fragments() -> None:
    assert compose(()) is None


def test_compose_sorts_and_deduplicates_across_molecules() -> None:
    fragments = (
        PackageFragment(molecule_id="com.example.rust", packages=("rustc", "cargo")),
        PackageFragment(molecule_id="com.example.python", packages=("python312",)),
    )
    composed = compose(fragments)
    assert composed is not None
    assert composed.packages == ("cargo", "python312", "rustc")
    assert composed.contributing_molecule_ids == ("com.example.python", "com.example.rust")


def test_compose_deduplicates_exact_duplicate_across_molecules() -> None:
    fragments = (
        PackageFragment(molecule_id="com.example.a", packages=("shared-tool",)),
        PackageFragment(molecule_id="com.example.b", packages=("shared-tool",)),
    )
    composed = compose(fragments)
    assert composed is not None
    assert composed.packages == ("shared-tool",)
    assert composed.contributing_molecule_ids == ("com.example.a", "com.example.b")


def test_compose_result_independent_of_fragment_order() -> None:
    """Same active set, different order -> byte-identical composed output (FR-005)."""
    a = PackageFragment(molecule_id="com.example.a", packages=("zeta", "alpha"))
    b = PackageFragment(molecule_id="com.example.b", packages=("mid",))
    assert compose((a, b)).packages == compose((b, a)).packages  # type: ignore[union-attr]
    assert compose((a, b)).to_json_bytes() == compose((b, a)).to_json_bytes()  # type: ignore[union-attr]


def test_composed_file_serializes_as_bare_array() -> None:
    composed = compose((PackageFragment(molecule_id="com.example.a", packages=("one", "two")),))
    assert composed is not None
    import json

    assert json.loads(composed.to_json_bytes()) == ["one", "two"]
