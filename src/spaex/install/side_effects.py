"""Repository side-effect guard for local-scope hooks and Spec Kit (Spec 029 FR-014).

Local install hooks and the local Spec Kit run are arbitrary code writing into
the consumer checkout. Their effects must stay invisible to git and must never
alter team-owned state, so each run is observed rather than trusted:

* a change to a git-tracked path, a project-owned path, or anything under
  `.spaex/` is reverted and refuses the install;
* every newly created untracked, not-yet-ignored path is reported so the
  caller can record it in the local lock and exclude it from git.

Outside a git repository only the project-owned paths are checked; nothing
can be committed there, so new files need no exclusion.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType
from typing import Literal

from spaex.io import atomic
from spaex.paths import SPAEX_DIRNAME
from spaex.util.errors import LocalHookSideEffectError


def _git(repo_root: Path, *args: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "--literal-pathspecs", "-C", str(repo_root), *args],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def _nul_paths(raw: bytes) -> set[str]:
    return {token.decode("utf-8") for token in raw.split(b"\0") if token}


def _dirty_tracked(repo_root: Path, prefix: str) -> set[str] | None:
    """Tracked paths whose worktree or index differs from HEAD, repo_root-relative."""
    raw = _git(
        repo_root, "status", "--porcelain=v1", "-z", "--untracked-files=no", "--no-renames"
    )
    if raw is None:
        return None
    # Porcelain paths are relative to the git top level, not to `repo_root`.
    return {
        entry[3:].decode("utf-8").removeprefix(prefix)
        for entry in raw.split(b"\0")
        if len(entry) > 3 and entry[3:].decode("utf-8").startswith(prefix)
    }


def _untracked(repo_root: Path) -> set[str]:
    raw = _git(repo_root, "ls-files", "--others", "--exclude-standard", "-z")
    return _nul_paths(raw) if raw is not None else set()


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() and not path.is_symlink() else None


class RepoSideEffectGuard:
    """Context manager observing one local hook or Spec Kit run.

    After a clean exit, `created` lists the new untracked paths. A forbidden
    change raises `LocalHookSideEffectError` after reverting it.
    """

    def __init__(self, repo_root: Path, *, actor: str, protected: Iterable[str]) -> None:
        self._root = repo_root
        self._actor = actor
        self._protected = frozenset(protected)
        self.created: tuple[str, ...] = ()

    def __enter__(self) -> RepoSideEffectGuard:
        raw_prefix = _git(self._root, "rev-parse", "--show-prefix")
        self._prefix = raw_prefix.decode("utf-8").strip() if raw_prefix is not None else ""
        raw_index = _git(self._root, "rev-parse", "--git-path", "index")
        self._index_path = None
        self._index_before = None
        if raw_index is not None:
            index_path = Path(raw_index.decode("utf-8").strip())
            self._index_path = index_path if index_path.is_absolute() else self._root / index_path
            if self._index_path.is_file():
                self._index_before = self._index_path.read_bytes()
        raw_tracked = _git(self._root, "ls-files", "-z")
        self._tracked_before = _nul_paths(raw_tracked) if raw_tracked is not None else set()
        self._dirty_before = _dirty_tracked(self._root, self._prefix)
        self._untracked_before = (
            _untracked(self._root) if self._dirty_before is not None else set()
        )
        watched = self._protected | (self._dirty_before or set())
        self._saved = {path: _read(self._root / path) for path in watched}
        spaex_root = self._root / SPAEX_DIRNAME
        self._spaex_before = {
            path.relative_to(self._root).as_posix(): path.read_bytes()
            for path in spaex_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        self._saved.update(self._spaex_before)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exc_type is not None:
            return False
        changed = {
            path for path, before in self._saved.items() if _read(self._root / path) != before
        }
        created: set[str] = set()
        if self._dirty_before is not None:
            changed |= (_dirty_tracked(self._root, self._prefix) or set()) - self._dirty_before
            created = _untracked(self._root) - self._untracked_before
        index_after = (
            self._index_path.read_bytes()
            if self._index_path is not None and self._index_path.is_file()
            else None
        )
        if index_after != self._index_before:
            changed |= self._dirty_before or set()
            changed |= _dirty_tracked(self._root, self._prefix) or set()
        spaex_root = self._root / SPAEX_DIRNAME
        spaex_after = {
            path.relative_to(self._root).as_posix(): path.read_bytes()
            for path in spaex_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        changed |= {
            path
            for path in self._spaex_before.keys() | spaex_after.keys()
            if self._spaex_before.get(path) != spaex_after.get(path)
        }
        inside_spaex = {path for path in created if path.split("/", 1)[0] == SPAEX_DIRNAME}
        changed |= inside_spaex
        if changed:
            self._revert(changed)
            raise LocalHookSideEffectError(
                message=(
                    f"{self._actor} changed team-owned path(s) "
                    f"{', '.join(sorted(changed))}; the change was reverted"
                ),
                context={"actor": self._actor, "paths": ",".join(sorted(changed))},
            )
        self.created = tuple(sorted(created))
        return False

    def _revert(self, changed: set[str]) -> None:
        if self._index_path is not None:
            if self._index_before is None:
                self._index_path.unlink(missing_ok=True)
            else:
                atomic.write_replace(self._index_path, self._index_before)
        restore_from_index = sorted(path for path in changed if path not in self._saved)
        for path in sorted(changed - set(restore_from_index)):
            target = self._root / path
            before = self._saved.get(path)
            if before is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic.write_replace(target, before)
        new_files = [
            path
            for path in restore_from_index
            if path.split("/", 1)[0] == SPAEX_DIRNAME or path not in self._tracked_before
        ]
        for path in new_files:
            (self._root / path).unlink(missing_ok=True)
        tracked = [path for path in restore_from_index if path not in new_files]
        if tracked:
            _git(self._root, "checkout", "--", *tracked)


__all__ = ["RepoSideEffectGuard"]
