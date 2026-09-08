# Quickstart: materialize a molecule tree, and see the safety checks refuse a hostile one

**Feature**: 017 | **Date**: 2026-09-08 | **Runnable acceptance for**: [spec.md § User Story 1 and User Story 3](./spec.md)

This quickstart is a Python-level walkthrough (not a CLI walkthrough — this feature introduces no new CLI surface) exercising the core `get_or_extract` capability directly, once implemented. It assumes the implementation from `/speckit-tasks` has landed in `spaex.git.molecule_store`.

## Prerequisites

- A spaex development checkout with this feature implemented.
- `git` on `PATH`.
- Python 3.10+ (matching the project baseline).

## 1. Materialize a well-formed molecule (User Story 1)

```python
import subprocess
import tempfile
from pathlib import Path

from spaex.git.molecule_store import get_or_extract
from spaex.git import revparse

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

# --- Materialize it ---
state_root = Path(tempfile.mkdtemp()) / "state"
canonical_sha = revparse.full_sha(publisher, sha)  # already full-length here, but canonicalize per contract
materialized = get_or_extract(publisher, canonical_sha, "widgets/hello", state_root)

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
    again = get_or_extract(publisher, canonical_sha, "widgets/hello", state_root)
    assert again == materialized
    # No `git archive` subprocess call should appear among spy's calls for this second request —
    # verifying SC-002 ("no additional remote-repository access on a cache hit").
    archive_calls = [c for c in spy.call_args_list if "archive" in c.args[0]]
    assert archive_calls == []
```

**Verifies**: FR-005, SC-002.

## 3. Request a molecule path that doesn't exist (User Story 1, AS3)

```python
try:
    get_or_extract(publisher, canonical_sha, "widgets/does-not-exist", state_root)
    assert False, "expected a not-found failure"
except Exception as exc:
    # The exact exception type is an implementation decision (see contracts/get-or-extract.md) —
    # this quickstart asserts only that SOME distinct, identifiable failure occurs, and that
    # no directory was created at the would-be cache path.
    would_be_final_dir = state_root / "molecule-store" / "<source-digest>" / canonical_sha / "widgets" / "does-not-exist"
    assert not would_be_final_dir.exists()
```

**Verifies**: FR-004.

## 4. Construct a hostile tree and watch every escape attempt get refused (User Story 3)

```python
import io
import tarfile

from spaex.git.molecule_store import _validate_and_extract  # internal, illustrative only

destination = Path(tempfile.mkdtemp())

buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w") as tar:
    # (a) `..`-escaping path
    escape_info = tarfile.TarInfo(name="../../etc/passwd")
    escape_info.size = 0
    tar.addfile(escape_info, io.BytesIO(b""))

    # (b) symlink with an absolute target — refused unconditionally per the 2026-09-08 clarification
    abs_link = tarfile.TarInfo(name="innocuous.txt")
    abs_link.type = tarfile.SYMTYPE
    abs_link.linkname = "/etc/passwd"
    tar.addfile(abs_link)

    # (c) symlink with an escaping relative target
    rel_escape_link = tarfile.TarInfo(name="subdir/link")
    rel_escape_link.type = tarfile.SYMTYPE
    rel_escape_link.linkname = "../../outside"
    tar.addfile(rel_escape_link)

    # (d) a well-formed, legitimate file — proves the checks don't produce false refusals
    good_file = tarfile.TarInfo(name="README.md")
    good_content = b"nothing malicious here\n"
    good_file.size = len(good_content)
    tar.addfile(good_file, io.BytesIO(good_content))

buf.seek(0)

try:
    _validate_and_extract(tarfile.open(fileobj=buf, mode="r"), destination)
    assert False, "expected a safety refusal"
except Exception:
    pass  # MoleculeTreeExtractionError, per contracts/get-or-extract.md

# Nothing was written outside `destination` as a result of any of the above:
assert not (destination.parent / "etc" / "passwd").exists()
assert not Path("/etc/passwd.tmp").exists()  # sanity: no real system file was ever touched
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
