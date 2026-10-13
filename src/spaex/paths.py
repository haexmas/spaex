"""Canonical repository-local spaex paths."""

from __future__ import annotations

from pathlib import Path

SPAEX_DIRNAME = ".spaex"
MANIFEST_FILENAME = "manifest.json"
MANIFEST_RELATIVE_PATH = f"{SPAEX_DIRNAME}/{MANIFEST_FILENAME}"
MANIFEST_LOCK_FILENAME = "manifest.json.lock"
MANIFEST_LOCK_RELATIVE_PATH = f"{SPAEX_DIRNAME}/{MANIFEST_LOCK_FILENAME}"
COMPOSED_CONSTITUTION_RELATIVE_PATH = f"{SPAEX_DIRNAME}/constitution.md"
LOCAL_DIRNAME = "local"
LOCAL_RELATIVE_DIR = f"{SPAEX_DIRNAME}/{LOCAL_DIRNAME}"
LOCAL_MANIFEST_RELATIVE_PATH = f"{LOCAL_RELATIVE_DIR}/{MANIFEST_FILENAME}"
LOCAL_CONSTITUTION_RELATIVE_PATH = f"{LOCAL_RELATIVE_DIR}/constitution.md"


def manifest_path(repo_root: Path) -> Path:
    """Return the consumer manifest path."""
    return repo_root / MANIFEST_RELATIVE_PATH


def manifest_lock_path(repo_root: Path) -> Path:
    """Return the consumer manifest lock path."""
    return repo_root / MANIFEST_LOCK_RELATIVE_PATH


def composed_constitution_path(repo_root: Path) -> Path:
    """Return the composed spaex Constitution artifact path."""
    return repo_root / COMPOSED_CONSTITUTION_RELATIVE_PATH


def composed_constitution_relative_path(repo_root: Path) -> str:
    """Return the active composed Constitution path relative to the repo."""
    return composed_constitution_path(repo_root).relative_to(repo_root).as_posix()


def local_dir(repo_root: Path) -> Path:
    """Return the uncommitted per-checkout local-scope directory (Spec 029)."""
    return repo_root / LOCAL_RELATIVE_DIR


def local_manifest_path(repo_root: Path) -> Path:
    """Return the local overlay manifest path."""
    return repo_root / LOCAL_MANIFEST_RELATIVE_PATH


def local_lock_path(repo_root: Path) -> Path:
    """Return the local install record path."""
    return local_dir(repo_root) / "install.lock"


def local_constitution_path(repo_root: Path) -> Path:
    """Return the composed local behavior document path."""
    return repo_root / LOCAL_CONSTITUTION_RELATIVE_PATH


__all__ = [
    "COMPOSED_CONSTITUTION_RELATIVE_PATH",
    "LOCAL_CONSTITUTION_RELATIVE_PATH",
    "LOCAL_DIRNAME",
    "LOCAL_MANIFEST_RELATIVE_PATH",
    "LOCAL_RELATIVE_DIR",
    "MANIFEST_FILENAME",
    "MANIFEST_LOCK_FILENAME",
    "MANIFEST_LOCK_RELATIVE_PATH",
    "MANIFEST_RELATIVE_PATH",
    "SPAEX_DIRNAME",
    "composed_constitution_path",
    "composed_constitution_relative_path",
    "local_constitution_path",
    "local_dir",
    "local_lock_path",
    "local_manifest_path",
    "manifest_lock_path",
    "manifest_path",
]
