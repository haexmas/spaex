# Quickstart: materialize a molecule tree, and see the safety checks refuse a hostile one

**Feature**: 017 | **Date**: 2026-09-08 | **Runnable acceptance for**: [spec.md § User Story 1 and User Story 3](./spec.md)

This quickstart is a Python-level walkthrough (not a CLI walkthrough — this feature introduces no new CLI surface) exercising the core `get_or_extract` capability directly, once implemented. It assumes the implementation from `/speckit-tasks` has landed in `spaex.git.molecule_store`.

## Prerequisites

- A spaex development checkout with this feature implemented.
- `git` on `PATH`.
- `pytest` available in the development environment.
- Python 3.10+ (matching the project baseline).

## 1. Materialize a well-formed molecule (User Story 1)

```python
import subprocess
import tempfile
from pathlib import Path

import pytest

from spaex.git.molecule_store import get_or_extract
from spaex.git import revparse
from spaex.git.cache import clone_dir
from spaex.util.errors import MoleculeTreeExtractionError, MoleculeTreePathNotFoundError

# --- Set up a tiny publisher repo with one molecule ---
publisher = Path(tempfile.mkdtemp()) / "publisher"
publisher.mkdir()
subprocess.run(["git", "init", "-q"], cwd=publisher, check=True)
subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=publisher, check=True)
subprocess.run(["git", "config", "user.name", "t"], cwd=publisher, check=True)
subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=publisher, check=True)

molecule_dir = publisher / "widgets" / "hello"
molecule_dir.mkdir(parents=True)
(molecule_dir / "manifest.json").write_text('{"id": "com.example.hello"}')
(molecule_dir / "helper.txt").write_text("hello from the molecule\n")

subprocess.run(["git", "add", "-A"], cwd=publisher, check=True)
subprocess.run(["git", "commit", "-q", "-m", "publish widgets/hello"], cwd=publisher, check=True)
sha = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=publisher, capture_output=True, text=True, check=True
).stdout.strip()

# get_or_extract reads from the same kind of bare clone that
# publisher_fetch.ensure_object() creates. The URL is the stable source
# identity; it is also what determines the cache digest.
repo_dir = publisher.parent / "publisher.git"
subprocess.run(["git", "clone", "-q", "--bare", str(publisher), str(repo_dir)], check=True)
canonical_source = "https://example.invalid/example/publisher"
state_root = Path(tempfile.mkdtemp()) / "state"
source_digest = clone_dir(state_root, canonical_source).name
canonical_sha = revparse.full_sha(repo_dir, sha)  # already full-length here, but canonicalize per contract
materialized = get_or_extract(repo_dir, canonical_source, canonical_sha, "widgets/hello", state_root)

print(materialized)                                   # a real directory
print((materialized / "manifest.json").read_text())   # {"id": "com.example.hello"}
print((materialized / "helper.txt").read_text())       # hello from the molecule
print(sorted(p.name for p in materialized.iterdir()))  # ['helper.txt', 'manifest.json'] — nothing else
```

**Verifies**: FR-001, FR-002, FR-003. The returned directory directly contains the two files — no extra `widgets/hello/` nesting level (FR-002).

## 2. Re-request the same key — no re-extraction (User Story 1, AS2)

```python
import unittest.mock as mock

with mock.patch("subprocess.run", wraps=subprocess.run) as spy:
    again = get_or_extract(repo_dir, canonical_source, canonical_sha, "widgets/hello", state_root)
    assert again == materialized
    # No `git archive` subprocess call should appear among spy's calls for this second request —
    # verifying SC-002 ("no additional remote-repository access on a cache hit").
    archive_calls = [c for c in spy.call_args_list if "archive" in c.args[0]]
    assert archive_calls == []
```

**Verifies**: FR-005, SC-002.

## 3. Request a molecule path that doesn't exist (User Story 1, AS3)

```python
with pytest.raises(MoleculeTreePathNotFoundError):
    get_or_extract(
        repo_dir,
        canonical_source,
        canonical_sha,
        "widgets/does-not-exist",
        state_root,
    )

would_be_final_dir = (
    state_root
    / "molecule-store"
    / source_digest
    / canonical_sha
    / "widgets"
    / "does-not-exist"
)
assert not would_be_final_dir.exists()
```

**Verifies**: FR-004.

## 4. Construct a hostile tree and watch every escape attempt get refused (User Story 3)

```python
import io
import tarfile

from spaex.git.molecule_store import _validate_and_extract  # internal, illustrative only
from spaex.util.errors import MoleculeTreeExtractionError

def validate_archive(add_members, *, expect_refusal):
    """Build one independent archive and validate it exactly once."""
    destination = Path(tempfile.mkdtemp())
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        add_members(tar)
    buf.seek(0)

    try:
        with tarfile.open(fileobj=buf, mode="r") as archive:
            _validate_and_extract(archive, destination)
    except MoleculeTreeExtractionError:
        if not expect_refusal:
            raise AssertionError("legitimate archive was refused")
        return destination

    if expect_refusal:
        raise AssertionError("hostile archive was accepted")
    return destination


# (a) `..`-escaping path — its own archive
def add_escape_path(tar):
    info = tarfile.TarInfo(name="../../etc/passwd")
    info.size = 0
    tar.addfile(info, io.BytesIO(b""))


# (b) absolute symlink target — refused unconditionally per the clarification
def add_absolute_link(tar):
    info = tarfile.TarInfo(name="innocuous.txt")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    tar.addfile(info)


# (c) relative symlink target escaping through `..` — its own archive
def add_relative_escape_link(tar):
    info = tarfile.TarInfo(name="subdir/link")
    info.type = tarfile.SYMTYPE
    info.linkname = "../../outside"
    tar.addfile(info)


validate_archive(add_escape_path, expect_refusal=True)
validate_archive(add_absolute_link, expect_refusal=True)
validate_archive(add_relative_escape_link, expect_refusal=True)


# (d) a legitimate file gets its own archive and must be accepted
def add_legitimate_file(tar):
    info = tarfile.TarInfo(name="README.md")
    content = b"nothing malicious here\n"
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))


good_destination = validate_archive(add_legitimate_file, expect_refusal=False)
assert (good_destination / "README.md").read_bytes() == b"nothing malicious here\n"
```

**Verifies**: FR-010, FR-011 (including the absolute-path clarification), User Story 3's core safety guarantee. (A full test for FR-012's archive-order/chained-escape case needs a slightly more elaborate two-member sequence — see `contracts/tar-member-validation.md`'s worked example 4 — and belongs in the actual test suite rather than this illustrative quickstart.)

## 5. Constitution resolution still works, now through the same path (User Story 4)

```python
from spaex.constitution.resolve import resolve_constitution_contributions
from spaex.model.consumer_manifest import CompoundEntry, ConsumerManifest

# ... (publish a molecule that also declares atoms.constitution: ["constitution.md"], as in
# tests/unit/test_resolve.py's existing _publish() helper) ...

manifest = ConsumerManifest(
    spaex_version="4",
    identity="com.example.consumer",
    compounds=(CompoundEntry(source=canonical_source, revision=sha, molecules=("com.example.hello",)),),
)
contributions = resolve_constitution_contributions(manifest, state_root)
print(contributions[0].body)  # the constitution.md content, read via the new materialized-directory path
```

**Verifies**: FR-015, FR-016, FR-017, User Story 4's non-regression goal — this call produces the identical result it produced before the migration, just via a different internal read mechanism.

## What this quickstart proves

- **User Story 1**: materialization produces a correct, correctly-shaped directory and caches it.
- **User Story 3**: the path-containment validation refuses every attempted escape and does not falsely refuse legitimate content.
- **User Story 4**: constitution resolution's observable behavior is unchanged after migrating onto this new capability.

(User Story 2's concurrency/interruption guarantees are process-level properties not practically demonstrable in a linear quickstart script — they belong in the test suite's dedicated concurrency tests, per `plan.md`'s `tests/unit/test_molecule_store_concurrency.py`.)
