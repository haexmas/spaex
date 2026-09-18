"""Spec 027 — atom-category kind classification."""

from __future__ import annotations

from spaex.model.atom_category import is_exclusive


def test_behavior_is_not_exclusive() -> None:
    """Keep behavior on its dedicated composition pipeline."""
    assert not is_exclusive("behavior")


def test_legacy_constitution_is_not_exclusive() -> None:
    """Keep legacy constitution atoms on their dedicated pipeline."""
    assert not is_exclusive("constitution")


def test_composable_category_is_not_exclusive() -> None:
    """Classify nix_packages as the fixed composable category."""
    assert not is_exclusive("nix_packages")


def test_reserved_skill_categories_are_not_exclusive() -> None:
    """Keep retired skill category names reserved and non-exclusive."""
    assert not is_exclusive("skill")
    assert not is_exclusive("skills")


def test_novel_category_is_exclusive() -> None:
    """Any category not on the fixed non-exclusive list is a generic exclusive atom."""
    assert is_exclusive("dev_environment")
    assert is_exclusive("anything-a-publisher-invents")
