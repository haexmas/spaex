"""Publisher SHA resolution and shallow-fetch helpers — Spec 013 T073.

Two entry points:

- ``resolve_sha(source_url, revision)`` — when ``revision`` is a full 40-hex
  SHA, returned verbatim. When ``None``, ``git ls-remote <source_url> HEAD``
  resolves the current head.
- ``ensure_object(source_url, sha, state_root)`` — guarantees the resolved
  SHA exists in the publisher clone under
  ``$SPAEX_STATE/repos/<source-digest>/`` (initial clone or shallow
  fetch). Returns the clone directory.

Refusal keys: ``source-url-invalid`` (git remote not reachable) and
``revision-not-found`` (SHA absent at the remote).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from spaex.install.manifest_lock import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    ManifestLockContext,
)
from spaex.migrate.transform import clone_dir
from spaex.util.errors import RevisionNotFoundError, SourceUrlInvalidError

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_GIT_TIMEOUT_SECONDS = 60.0


def _run_git(
    *args: str,
    cwd: Path | None = None,
    capture: bool = True,
    timeout: float | None = _GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=capture,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        timeout_text = "without a timeout" if timeout is None else f"after {timeout:g}s"
        raise SourceUrlInvalidError(
            message=f"git {args[0]} timed out {timeout_text}",
            context={"args": " ".join(args)},
        ) from exc


def _ls_remote_head(source_url: str) -> str:
    proc = _run_git("ls-remote", source_url, "HEAD")
    if proc.returncode != 0:
        raise SourceUrlInvalidError(
            message=(
                f"git ls-remote {source_url!r} failed: {proc.stderr.strip() or 'no output'}"
            ),
            context={"source": source_url},
        )
    first_line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
    sha = first_line.split()[0] if first_line else ""
    if not _SHA40_RE.match(sha):
        raise SourceUrlInvalidError(
            message=f"unexpected git ls-remote output: {proc.stdout!r}",
            context={"source": source_url},
        )
    return sha


def resolve_sha(source_url: str, revision: str | None) -> str:
    """Return the full 40-hex SHA to pin for this add invocation.

    ``source_url`` is passed to git verbatim; canonicalization is the
    caller's responsibility (see ``cli/add.py``).
    """
    if revision is not None:
        if not _SHA40_RE.match(revision):
            raise RevisionNotFoundError(
                message=f"--revision must be a full 40-hex SHA: {revision!r}",
                context={"source": source_url, "revision": revision},
            )
        return revision
    return _ls_remote_head(source_url)


def ensure_object(source_url: str, sha: str, state_root: Path) -> Path:
    """Guarantee the publisher clone contains ``sha``; return its directory.

    ``source_url`` is passed to git verbatim; canonicalization is the
    caller's responsibility (see ``cli/add.py``).
    """
    canonical = source_url
    repo_dir = clone_dir(state_root, canonical)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    cache_lock = ManifestLockContext(
        repo_dir.with_name(repo_dir.name + ".lock"),
        timeout_seconds=DEFAULT_LOCK_TIMEOUT_SECONDS,
    )

    with cache_lock:
        if not repo_dir.exists():
            temp_dir = Path(
                tempfile.mkdtemp(prefix=f".{repo_dir.name}.tmp-", dir=str(repo_dir.parent))
            )
            try:
                init = _run_git("init", "-q", "--bare", cwd=temp_dir)
                if init.returncode != 0:
                    raise SourceUrlInvalidError(
                        message=f"git init failed for {canonical!r}: {init.stderr.strip()}",
                        context={"source": canonical},
                    )
                remote = _run_git("remote", "add", "origin", canonical, cwd=temp_dir)
                if remote.returncode != 0:
                    raise SourceUrlInvalidError(
                        message=(
                            f"git remote add origin {canonical!r} failed: "
                            f"{remote.stderr.strip()}"
                        ),
                        context={"source": canonical},
                    )
                bare = _run_git("rev-parse", "--is-bare-repository", cwd=temp_dir)
                if bare.returncode != 0 or bare.stdout.strip() != "true":
                    raise SourceUrlInvalidError(
                        message=f"git init did not create a bare repository for {canonical!r}",
                        context={"source": canonical},
                    )
                remote_check = _run_git("remote", "get-url", "origin", cwd=temp_dir)
                if remote_check.returncode != 0:
                    raise SourceUrlInvalidError(
                        message=(
                            f"git remote origin setup failed for {canonical!r}: "
                            f"{remote_check.stderr.strip()}"
                        ),
                        context={"source": canonical},
                    )
                try:
                    os.replace(temp_dir, repo_dir)
                except OSError:
                    if not repo_dir.is_dir():
                        raise
            except BaseException:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise

        if not repo_dir.is_dir():
            raise SourceUrlInvalidError(
                message=f"publisher cache path is not a directory: {repo_dir}",
                context={"source": canonical},
            )

        have = _run_git("cat-file", "-e", sha, cwd=repo_dir)
        if have.returncode == 0:
            return repo_dir

        fetch = _run_git(
            "fetch",
            "--depth",
            "1",
            "origin",
            sha,
            cwd=repo_dir,
        )
        if fetch.returncode != 0:
            stderr = fetch.stderr.strip()
            if "couldn't find remote ref" in stderr.lower() or "not our ref" in stderr.lower():
                raise RevisionNotFoundError(
                    message=f"revision {sha} not found at {canonical!r}: {stderr}",
                    context={"source": canonical, "revision": sha},
                )
            raise SourceUrlInvalidError(
                message=f"git fetch of {sha} at {canonical!r} failed: {stderr}",
                context={"source": canonical, "revision": sha},
            )
        return repo_dir
