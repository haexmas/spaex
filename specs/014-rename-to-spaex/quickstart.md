# Quickstart: spaex (v4)

**Spec**: 014
**Audience**: an operator who wants to (a) install `spaex` fresh, (b) adopt a molecule in a repo, or (c) migrate an existing v3 (`haex-hive`) project.

This quickstart shows the flows after the rename lands and the first PyPI release ships. Before that, replace `pipx install spaex` with `pip install -e .` from a checkout of the renamed repo.

## Prerequisites

- Python 3.10+
- Git 2.30+ on `$PATH`
- `pipx` (recommended for CLI-tool installs). On Debian/Ubuntu: `sudo apt install pipx && pipx ensurepath`

## Install from PyPI

```bash
pipx install spaex
spaex --version   # 4.0.0
```

## Adopt a molecule in an existing repo

```bash
cd /path/to/your/project
spaex add https://github.com/some-publisher/harness-atoms com.example.workflow.speckit
```

`spaex add`:
1. Fetches the publisher's `manifest.json` at the current HEAD (or at `--revision=<SHA>` if specified).
2. Locates the requested molecule id in the publisher's `molecules{}` map.
3. Adds a `compound` entry to `.spaex.json` with the source URL, resolved SHA, and molecule id.
4. Runs `spaex install` in the same invocation to write the molecule's files into the participating roots (`.claude/`, `.codex/`, `.spaex/`, etc.).

Adopt multiple molecules from the same source:

```bash
spaex add https://github.com/some-publisher/harness-atoms com.example.workflow.speckit,com.example.slash.debug
```

Adopt every molecule the publisher declares:

```bash
spaex add https://github.com/some-publisher/harness-atoms --all
```

Pin to a specific revision (instead of HEAD):

```bash
spaex add https://github.com/some-publisher/harness-atoms com.example.workflow.speckit \
    --revision 3fa85f6457174562b3fc2c963f66afa6c9d9ef8f
```

## Retract a molecule

```bash
spaex remove com.example.workflow.speckit
```

`spaex remove`:
1. Preflights every named id against `.spaex.json.compounds[].molecules[]`.
2. If any id is missing, refuses with `unknown-molecule-id` naming every absent id. No changes to the manifest.
3. On success, removes the ids, drops any compound whose `molecules[]` became empty, and runs `spaex install`. `spaex install` deletes files that only the retracted molecule contributed and leaves everything else intact.

## Migrate from v3 (haex-hive)

If your project has a `.haex-hive.json` with `haex_hive_version: "3"`:

```bash
# One-time upgrade path
pipx install spaex
cd /path/to/your/project

spaex migrate
```

`spaex migrate` walks your repo and writes `.migrated` sibling files for every v3 manifest it finds:

- `.haex-hive.json` → `.spaex.json.migrated`
- publisher-root `manifest.json` (if this is a publisher repo) → `manifest.json.migrated`
- per-molecule `manifest.json` (if this is a publisher repo) → `manifest.json.migrated`

Review the printed diffs. When satisfied, adopt each proposal:

```bash
# consumer
mv .spaex.json.migrated .spaex.json
rm .haex-hive.json

# publisher-root and each molecule (repeat per file)
mv path/to/manifest.json.migrated path/to/manifest.json

# runtime output (safe to delete; regenerated below)
rm -rf .haex-hive/

spaex install
```

After `spaex install` completes, `.spaex/install.lock` is present and byte-identical across two consecutive runs.

## Migrate from v1 or v2

The migrate chain covers v1 → v2 → v3 → v4 in one pass. Same command:

```bash
spaex migrate
```

Every legacy file gets a v4 proposal after one invocation.

## Environment variable

`spaex` honors `$SPAEX_STATE` for the per-invocation state directory (publisher clones, migration proposals, and other transient scratch space):

```bash
export SPAEX_STATE=/var/lib/spaex
spaex install
```

Unset uses the built-in default under the operator's XDG state dir.

## Common refusal keys

| Key | Meaning | What to do |
|---|---|---|
| `spaex-version-unsupported` | A read gate saw a `spaex_version` other than `"4"`, or a legacy `haex_hive_version` field. | Run `spaex migrate`. |
| `unsupported-min-version-constraint` | `spaex migrate` cannot rewrite a `haex_hive_min_version` constraint. | Manually simplify the constraint to exact `3.X.Y` or lower-bound `>=3.X.Y` first, then re-migrate. |
| `constitution-already-adopted` | `spaex add` on a molecule that would introduce a second constitution when one is already adopted. | Retract the current one first: `spaex remove <current-id>`, then re-add. |
| `manifest-lock-contended` | `.spaex.json.lock` is held by another `spaex` invocation. | Wait for it to finish, or pass `--lock-timeout=0` to fail fast, or `--lock-timeout=<sec>` to extend the wait. |
| `source-url-invalid` | The URL passed to `spaex add` does not resolve to a git remote. | Fix the URL. |
| `revision-not-found` | The SHA passed to `--revision` does not exist at the remote. | Check the SHA. |
| `publisher-manifest-missing` | The remote resolved but there is no `manifest.json` at the root of the fetched commit. | Confirm the publisher publishes a v4 `manifest.json`. |
| `publisher-manifest-invalid` | The `manifest.json` is present but does not validate against the v4 schema. | The publisher is on v3 or older; either wait for them to migrate, or (if you own it) run `spaex migrate` in their repo. |
| `unknown-molecule-id` | `spaex remove` was asked to retract an id that is not adopted. | Check `spaex.json` for the correct id spelling. |
| `atoms-category-overlap` | A molecule declares the same path under two atom categories. | Fix the molecule manifest; each path belongs to exactly one category. |
| `workflow-molecule-already-adopted` | Attempted to adopt a second workflow molecule. | Retract the current workflow molecule first. |
