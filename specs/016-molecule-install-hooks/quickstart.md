# Post-implementation acceptance walkthrough: publish and adopt a molecule with `install_hook`

**Feature**: 016 | **Date**: 2026-09-08 | **Status**: verified end-to-end against spaex 4.1.0 (Phase 9, 2026-09-10)

This walkthrough exercises the P1 story: a molecule author declares `install_hook` in the manifest, a consumer adopts the molecule via `spaex add`, and the hook runs producing a verifiable side effect. It uses only the spaex 4.1.0 CLI and git; no external dependencies. Section 5 also covers the P2 (`on_failure`) and P3 (`--no-install-hooks`) stories.

## Prerequisites

- spaex 4.1.0 installed (`pip install spaex==4.1.0`).
- git ≥ 2.30 (for `git worktree`).
- python3 on `PATH` (for the hook script).
- A shell (bash or zsh).

## Setup: emulate an HTTPS publisher on localhost

`spaex add` refuses `file://` source URLs by design (Principle IV requires an authenticated remote address for pinning). To run this walkthrough offline without a real HTTPS server, use a fake canonical URL AND pre-seed the state cache with a local bare clone. spaex's `ensure_object` short-circuits when the requested SHA is already present in the cache, so no network access is attempted.

```bash
export SPAEX_STATE=/tmp/spaex-016-quickstart/state
export CANONICAL=https://example.invalid/demo/publisher
# spaex.migrate.transform.clone_dir shape: <state>/repos/<sha256-first-16>
DIGEST=$(python3 -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])" "$CANONICAL")
export CACHE_DIR="$SPAEX_STATE/repos/$DIGEST"
mkdir -p "$SPAEX_STATE/repos"
```

The pre-seed step happens after section 1 (once the publisher repo exists).

## 1. Author the publisher molecule

Create a fresh git repo that will host one molecule with an `install_hook`:

```bash
mkdir -p /tmp/spaex-016-quickstart/publisher
cd /tmp/spaex-016-quickstart/publisher
git init -q -b main
git config user.email "author@example.com"
git config user.name "Author"
git config commit.gpgsign false
```

Write the publisher root manifest at `manifest.json`:

```json
{
  "spaex_version": "4",
  "publisher": "com.example.demo",
  "molecules": {
    "com.example.demo.hello-hook": {
      "path": "hello-hook",
      "version": "1.0.0"
    }
  }
}
```

Write the molecule at `hello-hook/manifest.json`:

```json
{
  "spaex_version": "4",
  "id": "com.example.demo.hello-hook",
  "version": "1.0.0",
  "priority": 20,
  "atoms": {
    "constitution": ["constitution.md"]
  },
  "install_hook": {
    "interpreter": "python3",
    "script": "install.py",
    "on_failure": "warn"
  }
}
```

Write the molecule constitution at `hello-hook/constitution.md`:

```markdown
# Principle: hello-hook demo

This constitution fragment is materialised into the consumer's assembled constitution by `spaex install`. The install_hook writes an additional side-effect file into the consumer repo.
```

Write the hook script at `hello-hook/install.py`. Note the idempotency contract: appending only when absent.

```python
#!/usr/bin/env python3
"""Idempotent install-hook for the hello-hook molecule."""
from pathlib import Path

MARKER = "hello-hook installed"
GITIGNORE_LINE = "hello-hook-out/"

def main() -> int:
    repo = Path.cwd()  # cwd is the consumer repo root, per FR-012

    marker_file = repo / ".spaex-hook" / "hello-hook.marker"
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    if not marker_file.exists():
        marker_file.write_text(MARKER + "\n", encoding="utf-8")
        print(f"hello-hook: wrote {marker_file.relative_to(repo)}")
    else:
        print(f"hello-hook: {marker_file.relative_to(repo)} already present, skipping")

    gitignore = repo / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    if GITIGNORE_LINE not in {line.strip() for line in lines}:
        with gitignore.open("a", encoding="utf-8") as fh:
            if lines and lines[-1] != "":
                fh.write("\n")
            fh.write(f"{GITIGNORE_LINE}\n")
        print(f"hello-hook: appended {GITIGNORE_LINE} to .gitignore")
    else:
        print(f"hello-hook: {GITIGNORE_LINE} already in .gitignore, skipping")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

Commit and record the SHA the consumer will pin:

```bash
git add -A
git commit -qm "hello-hook 1.0.0 with install_hook"
PUBLISHER_SHA=$(git rev-parse HEAD)
echo "Publisher SHA: $PUBLISHER_SHA"
```

Pre-seed the state cache so `$CANONICAL` resolves locally:

```bash
git clone --bare -q /tmp/spaex-016-quickstart/publisher "$CACHE_DIR"
```

## 2. Adopt from a consumer

Set up a fresh consumer repo:

```bash
mkdir -p /tmp/spaex-016-quickstart/consumer
cd /tmp/spaex-016-quickstart/consumer
git init -q
git config user.email "operator@example.com"
git config user.name "Operator"
git config commit.gpgsign false
touch README.md
git add README.md
git commit -qm "seed"
```

Seed the consumer manifest at `.spaex.json`:

```bash
cat > .spaex.json <<'JSON'
{
  "spaex_version": "4",
  "identity": "com.example.demo-consumer",
  "compounds": []
}
JSON
```

Adopt the molecule (spaex `add` runs `install` internally):

```bash
spaex --repo-root . add "$CANONICAL" com.example.demo.hello-hook \
  --revision "$PUBLISHER_SHA"
```

Expected output includes:

```text
hello-hook: wrote .spaex-hook/hello-hook.marker
hello-hook: appended hello-hook-out/ to .gitignore
installed generation g_<timestamp>_<pid>
added 1 molecule(s) at https://example.invalid/demo/publisher@<12-char-sha>:
  com.example.demo.hello-hook
```

## 3. Verify the acceptance criteria (User Story 1)

```bash
# AS1: gitignore contains the line exactly once
grep -c "^hello-hook-out/$" .gitignore
# → 1

# AS1: constitution materialised
cat .spaex/constitution.md | head -5
# → begins with "# Principle: hello-hook demo"

# AS1: hook_status recorded as "ok" in install.lock
python3 -c "import json; d=json.load(open('.spaex/install.lock')); print(d['molecules'][0]['hook_status'])"
# → ok

# AS2: re-run install; hook runs again; no duplicate .gitignore line
spaex --repo-root . install
grep -c "^hello-hook-out/$" .gitignore
# → 1

# The hook output confirms idempotency
# → "hello-hook: hello-hook-out/ already in .gitignore, skipping"
```

## 4. Exercise the `--no-install-hooks` opt-out (User Story 3)

Remove the marker to prove the hook does not run:

```bash
rm .spaex-hook/hello-hook.marker
spaex --repo-root . install --no-install-hooks

# Marker was NOT recreated
ls .spaex-hook/hello-hook.marker 2>&1
# → (no such file)

# install.lock records skipped
python3 -c "import json; d=json.load(open('.spaex/install.lock')); print(d['molecules'][0]['hook_status'])"
# → skipped
```

Re-run without the flag to confirm skipping is per-invocation only:

```bash
spaex --repo-root . install
ls .spaex-hook/hello-hook.marker
# → .spaex-hook/hello-hook.marker (present)
python3 -c "import json; d=json.load(open('.spaex/install.lock')); print(d['molecules'][0]['hook_status'])"
# → ok
```

## 5. Exercise the `on_failure` policy (User Story 2)

Modify the hook to fail, republish, repin, observe.

In the publisher repo:

```bash
cd /tmp/spaex-016-quickstart/publisher
# Make the hook fail
python3 - <<'PY'
from pathlib import Path

path = Path("hello-hook/install.py")
text = path.read_text(encoding="utf-8")
needle = '    return 0\n\nif __name__ == "__main__":'
replacement = '    return 1\n\nif __name__ == "__main__":'
if needle not in text:
    raise SystemExit("could not find main() return in hello-hook/install.py")
path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
PY
git add hello-hook/install.py
git commit -qm "hello-hook: force failure for demo"
PUBLISHER_SHA_FAIL=$(git rev-parse HEAD)

# Fetch the new commit into the pre-seeded state cache.
git -C "$CACHE_DIR" fetch -q /tmp/spaex-016-quickstart/publisher main:main
```

In the consumer, repin to the failing SHA. Since the molecule declares `on_failure: "warn"`:

```bash
cd /tmp/spaex-016-quickstart/consumer
spaex --repo-root . add "$CANONICAL" com.example.demo.hello-hook \
  --revision "$PUBLISHER_SHA_FAIL"
# Expected: install proceeds, WARN line appears after the process exits,
# install.lock records hook_status: "failed", CLI exits 0
```

To demonstrate the `abort` policy with the same failing hook, change the
manifest's `on_failure` to `"abort"`, republish, and repin:

```bash
cd /tmp/spaex-016-quickstart/publisher
python3 - <<'PY'
from pathlib import Path

path = Path("hello-hook/manifest.json")
text = path.read_text(encoding="utf-8")
path.write_text(text.replace('"on_failure": "warn"', '"on_failure": "abort"'), encoding="utf-8")
PY
git add hello-hook/manifest.json
git commit -qm "hello-hook: demonstrate abort policy"
PUBLISHER_SHA_ABORT=$(git rev-parse HEAD)
git -C "$CACHE_DIR" fetch -q /tmp/spaex-016-quickstart/publisher main:main

cd /tmp/spaex-016-quickstart/consumer
spaex --repo-root . add "$CANONICAL" com.example.demo.hello-hook \
  --revision "$PUBLISHER_SHA_ABORT"
# Expected: install fails with install-failed, managed .spaex state rolls back,
# and the delegated .spaex.json compound update is reverted.
```

## 6. Cleanup

```bash
rm -rf /tmp/spaex-016-quickstart
```

## What this quickstart proves

- **User Story 1 (P1)**: `spaex add` invokes the declared install_hook after atoms materialise, producing a real side effect in the consumer repo, and records `hook_status: "ok"` in install.lock.
- **Idempotency (AS2 of Story 1)**: repeat `spaex install` calls do not duplicate the gitignore line or the marker.
- **User Story 3 (P3)**: `--no-install-hooks` skips the hook, records `"skipped"`, and does not persist across invocations.
- **User Story 2 (P2)**: `on_failure: "warn"` produces a non-fatal failure with `hook_status: "failed"` in install.lock and CLI exit 0. Switching to `on_failure: "abort"` demonstrates the rollback path.

Consumer artefacts observed (all locations relative to the consumer repo root):
- `.spaex.json` (compound entry with pinned SHA, unchanged shape from Spec 013/014)
- `.spaex/constitution.md` (assembled from the molecule's constitution atom)
- `.spaex/install.lock` (new `hook_status` field on the per-molecule record)
- `.gitignore` (line appended by the hook)
- `.spaex-hook/hello-hook.marker` (side-effect file written by the hook outside the managed `.spaex/` generation)
