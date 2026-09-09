"""Materialize a molecule's tree from a bare git clone onto local disk.

Spec 017. `get_or_extract()` is the sole entry point: given a bare clone
(`repo_dir`), its canonical source URL, a canonical full-length revision, and
a molecule-directory path, it returns a real, on-disk directory containing
that subtree's content, cached indefinitely under
`state_root/molecule-store/<source-digest>/<revision>/<molecule_path>/`.

Extraction runs `git archive <revision> -- <molecule_path>` against the bare
clone and parses the resulting tar stream with the stdlib `tarfile` module —
never the external `tar` binary, to keep the `py3-none-any` wheel target
intact. Every tar member is validated for path-containment before it is
extracted (`_validate_and_extract`), since Python's `tarfile.extractall`
`filter="data"` safety net is 3.12+ only and this project's baseline is
3.10+. Validation runs in archive order and tracks which destination
directories have been established as safe (extracted regular directories)
so far. A later member's path is resolved via `Path.resolve()`, which
transparently follows any real, already-extracted symlink to its actual
target — so nesting under an *accepted* symlink is safe exactly when that
symlink's target is itself an established-safe directory, while nesting
under a *rejected* symlink (never created on disk) fails the ancestor
check, since its lexical-only path was never added to the safe set.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from spaex.install.manifest_lock import DEFAULT_LOCK_TIMEOUT_SECONDS, ManifestLockContext
from spaex.migrate.transform import clone_dir
from spaex.model.repo_relative_path import RepoRelativePath
from spaex.util.errors import MoleculeTreeExtractionError, MoleculeTreePathNotFoundError

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_GIT_ARCHIVE_TIMEOUT_SECONDS = 60.0


def _is_absolute_link_target(target: str) -> bool:
    """Return whether a tar member's link target is absolute on any platform.

    Refused unconditionally regardless of where it would resolve (2026-09-08
    clarification) — an absolute path baked into a molecule's tree is
    inherently non-portable and there is no legitimate reason for one.
    """
    return (
        target.startswith("/")
        or bool(_WINDOWS_DRIVE_RE.match(target))
        or target.startswith("\\")
    )


def _extract_member(tar: tarfile.TarFile, member: tarfile.TarInfo, destination: Path) -> None:
    """Extract one already-validated member on every supported Python version."""
    if sys.version_info >= (3, 11, 4):
        tar.extract(member, path=destination, set_attrs=False, filter="data")
    else:
        tar.extract(member, path=destination, set_attrs=False)


def _validate_and_extract(tar: tarfile.TarFile, destination: Path) -> None:
    """Extract every member of `tar` into `destination`, validating each first.

    Implements contracts/tar-member-validation.md: per member, in archive
    order, reject `..`-escapes, reject absolute-path link targets
    unconditionally, reject relative link targets that resolve outside
    `destination`, and reject any member whose parent directory was not
    itself established as safe by an earlier, accepted directory member
    (defeats the chained/sandwich escape — a symlink is never trusted as a
    safe anchor for later members, even one that itself resolves inside
    `destination`).

    Raises MoleculeTreeExtractionError on the first rejected member. No
    partial extraction of "the safe subset" — the whole pass fails together.
    """
    destination = destination.resolve()
    safe_dirs: set[Path] = {destination}

    for member in tar.getmembers():
        member_path = (destination / member.name).resolve()

        try:
            member_path.relative_to(destination)
        except ValueError:
            raise MoleculeTreeExtractionError(
                message=f"tar member {member.name!r} escapes the destination directory",
                context={"member": member.name},
            ) from None
        if member_path == destination:
            raise MoleculeTreeExtractionError(
                message=f"tar member {member.name!r} resolves to the destination directory itself",
                context={"member": member.name},
            )

        if member_path.parent not in safe_dirs:
            raise MoleculeTreeExtractionError(
                message=(
                    f"tar member {member.name!r} nests under a directory that was not "
                    "established as safe (missing directory entry or a rejected/symlink ancestor)"
                ),
                context={"member": member.name},
            )

        if member.issym() or member.islnk():
            if _is_absolute_link_target(member.linkname):
                raise MoleculeTreeExtractionError(
                    message=(
                        f"tar member {member.name!r} has an absolute link target "
                        f"{member.linkname!r}"
                    ),
                    context={"member": member.name, "linkname": member.linkname},
                )
            resolved_target = (member_path.parent / member.linkname).resolve()
            try:
                resolved_target.relative_to(destination)
            except ValueError:
                raise MoleculeTreeExtractionError(
                    message=(
                        f"tar member {member.name!r} link target {member.linkname!r} "
                        "escapes the destination directory"
                    ),
                    context={"member": member.name, "linkname": member.linkname},
                ) from None
            _extract_member(tar, member, destination)
            # Not added to safe_dirs directly: a later member nested under
            # this symlink resolves (via Path.resolve() above) through the
            # real filesystem link we just created, so its ancestor check
            # is evaluated against the symlink's actual target, not its own
            # path — safe when that target is itself an established directory.
            continue

        if member.isdir():
            member_path.mkdir(parents=True, exist_ok=True)
            safe_dirs.add(member_path)
            continue

        _extract_member(tar, member, destination)


def get_or_extract(
    repo_dir: Path,
    source_url: str,
    revision: str,
    molecule_path: str,
    state_root: Path,
) -> Path:
    """Return a real, on-disk directory for `molecule_path` at `revision`.

    `repo_dir` is the local bare clone to read from (an execution input, not
    part of the cache key). `source_url` is the canonical, credential-free
    source identity used to derive the cache partition — never `repo_dir`'s
    local path, which is device-specific. `revision` MUST already be a
    canonical full 40-hex SHA (callers resolve short/symbolic refs via
    `git_revparse.full_sha()` beforehand); a non-canonical-looking value is a
    caller-contract violation (`ValueError`), not a runtime condition.

    Idempotent: a second call for the identical (source_url, revision,
    molecule_path) returns the same directory without re-extracting.
    """
    RepoRelativePath.validate(molecule_path)
    if not _SHA40_RE.match(revision):
        raise ValueError(f"revision must be a canonical 40-hex SHA, got {revision!r}")

    source_digest = clone_dir(state_root, source_url).name
    revision_root = state_root / "molecule-store" / source_digest / revision
    final_dir = revision_root / molecule_path

    lock = ManifestLockContext(
        final_dir.with_name(final_dir.name + ".lock"),
        timeout_seconds=DEFAULT_LOCK_TIMEOUT_SECONDS,
    )
    with lock:
        if final_dir.exists():
            return final_dir

        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_dir), "archive", revision, "--", molecule_path],
                capture_output=True,
                timeout=_GIT_ARCHIVE_TIMEOUT_SECONDS,
                check=False,
                env={**os.environ, "LC_ALL": "C"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MoleculeTreeExtractionError(
                message=f"git archive failed to run for {molecule_path!r} at {revision}: {exc}",
                context={"molecule_path": molecule_path, "revision": revision},
            ) from exc
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")
            if "did not match any files" in stderr:
                raise MoleculeTreePathNotFoundError(
                    message=f"molecule path {molecule_path!r} not found at revision {revision}",
                    context={"molecule_path": molecule_path, "revision": revision},
                )
            raise MoleculeTreeExtractionError(
                message=f"git archive failed for {molecule_path!r} at {revision}: {stderr.strip()}",
                context={"molecule_path": molecule_path, "revision": revision},
            )

        revision_root.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(
            tempfile.mkdtemp(prefix=f".{revision_root.name}.tmp-", dir=str(revision_root.parent))
        )
        try:
            try:
                with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r") as tar:
                    if not tar.getmembers():
                        (temp_dir / molecule_path).mkdir(parents=True, exist_ok=True)
                    else:
                        _validate_and_extract(tar, temp_dir)
            except tarfile.TarError as exc:
                raise MoleculeTreeExtractionError(
                    message=f"malformed tar stream for {molecule_path!r} at {revision}: {exc}",
                    context={"molecule_path": molecule_path, "revision": revision},
                ) from exc

            temp_molecule_dir = temp_dir / molecule_path
            if not temp_molecule_dir.is_dir():
                raise MoleculeTreeExtractionError(
                    message=(
                        f"archive for {molecule_path!r} at {revision} did not yield a "
                        "directory tree at that path"
                    ),
                    context={"molecule_path": molecule_path, "revision": revision},
                )
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_molecule_dir, final_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        return final_dir
