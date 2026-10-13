"""Per-worktree spaex block in git's per-clone exclude file (Spec 029, ADR 0027).

Local-scope outputs outside `.spaex/local/` (repo-root exclusive atoms, Spec
Kit output, files a local hook created) must stay out of git without editing
any committed ignore file. Git's `info/exclude` is the built-in per-clone,
never-committed ignore list. spaex owns only its own marker-delimited block,
one per worktree, and never touches any other line.

ponytail: `info/exclude` lives in the common git dir, so every worktree of a
clone reads every block — an entry from worktree A also hides an untracked
file at the same path in worktree B. Upgrade path: per-worktree
`core.excludesFile` via `extensions.worktreeConfig`, once someone needs it.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

from spaex.io import atomic
from spaex.util.errors import LocalExcludeMalformedError

_START_RE = re.compile(r'^# spaex-local:start worktree="(?P<key>[^"]*)"$')
_END_RE = re.compile(r'^# spaex-local:end worktree="(?P<key>[^"]*)"$')
_GITIGNORE_SPECIAL = re.compile(r"([\\*?\[\]])")


def _git(repo_root: Path, *args: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def exclude_file(repo_root: Path) -> Path | None:
    """Return this clone's `info/exclude` path, or None outside a git repo."""
    raw = _git(repo_root, "rev-parse", "--git-path", "info/exclude")
    if raw is None:
        return None
    path = Path(raw)
    return path if path.is_absolute() else repo_root / path


def worktree_key(repo_root: Path) -> str:
    """Name this worktree's block: the basename of its git dir (`.git` for the main one)."""
    raw = _git(repo_root, "rev-parse", "--git-dir")
    return Path(raw).name if raw else ".git"


def _anchored(path: str) -> str:
    escaped = _GITIGNORE_SPECIAL.sub(r"\\\1", path)
    if escaped.endswith(" "):
        escaped = escaped[:-1] + "\\ "
    return "/" + escaped


def _split_blocks(lines: list[str], target: Path) -> list[tuple[str, int, int]]:
    """Return `(key, start, end)` line indexes of every well-formed spaex block."""
    def malformed(key: str) -> LocalExcludeMalformedError:
        return LocalExcludeMalformedError(
            message=f"unbalanced spaex-local block for worktree {key!r} in {target}",
            context={"path": str(target), "worktree": key},
        )

    blocks: list[tuple[str, int, int]] = []
    open_key: str | None = None
    open_index = 0
    for index, line in enumerate(lines):
        if (start := _START_RE.match(line)) is not None:
            if open_key is not None:
                raise malformed(open_key)
            open_key, open_index = start.group("key"), index
        elif (end := _END_RE.match(line)) is not None:
            if open_key is None or open_key != end.group("key"):
                raise malformed(end.group("key"))
            blocks.append((open_key, open_index, index))
            open_key = None
    if open_key is not None:
        raise malformed(open_key)
    return blocks


def block_paths(repo_root: Path) -> tuple[str, ...]:
    """Return the anchored entries of this worktree's block (empty when absent)."""
    target = exclude_file(repo_root)
    if target is None or not target.is_file():
        return ()
    lines = target.read_text(encoding="utf-8").splitlines()
    key = worktree_key(repo_root)
    for block_key, start, end in _split_blocks(lines, target):
        if block_key == key:
            return tuple(lines[start + 1 : end])
    return ()


def reconcile(repo_root: Path, paths: Iterable[str]) -> None:
    """Make this worktree's block list exactly `paths` (repo-relative, POSIX).

    Rewrites through a temporary file plus atomic rename. Removes the block
    when `paths` is empty. A no-op outside a git repository.
    """
    target = exclude_file(repo_root)
    if target is None:
        return
    entries = sorted({_anchored(path) for path in paths})
    existing = target.read_text(encoding="utf-8") if target.is_file() else ""
    lines = existing.splitlines()
    key = worktree_key(repo_root)
    kept = list(lines)
    for block_key, start, end in reversed(_split_blocks(lines, target)):
        if block_key == key:
            del kept[start : end + 1]
    if entries:
        kept.extend(
            [
                f'# spaex-local:start worktree="{key}"',
                *entries,
                f'# spaex-local:end worktree="{key}"',
            ]
        )
    updated = "\n".join(kept) + "\n" if kept else ""
    if updated == existing:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_replace(target, updated.encode("utf-8"))


__all__ = ["block_paths", "exclude_file", "reconcile", "worktree_key"]
