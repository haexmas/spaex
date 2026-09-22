# Contract: `spaex status` and `spaex trace` CLI

New, read-only spaex CLI subcommands. Both are siblings of `constitution`/`install`/`add`/`remove` at the top level (not nested under `constitution`; see research.md R6 for why `spaex trace` stays a separate command from `spaex constitution trace`).

## New subcommands

### `spaex status`

Prints a summary of the repository's active spaex composition: every pinned/installed molecule, what each one's atoms materialized into, the composed constitution, and any drift between the manifest, the install lock and the constitution.

**Arguments**:
- Positional: none.
- `--format text|json`: output format. Default `text`.

**Read-only contract**: MUST NOT write to the repository, the local molecule cache, or the user configuration, and MUST NOT access the network (FR-002). It never resolves a molecule from its source; every fact it reports comes from `.spaex/manifest.json`, `.spaex/install.lock`, `.spaex/constitution.d/`, `.spaex/constitution.md`, and generated artifacts such as `.spaex/generated/nix-packages.json` (data-model.md).

**Exit codes**:
- 0: report produced, including when `drift` is non-empty. Drift is informational and never changes the exit code (spec.md Assumption "Drift is informational").
- 4: `.spaex/install.lock` is present but invalid.
- 7: `.spaex/manifest.json` is missing or invalid (reuses `spaex.cli.install._load_consumer_manifest`'s existing `INCOMPLETE_TRANSACTION` code, per research.md R7 — not 5, despite `exit_codes.py`'s stale comment for that code).

**Sample output** (`--format text`):

```text
spaex status

Molecules (3 pinned, 3 installed):
  com.github.haexmas.atoms.general-coding@1a292194 — installed
    behavior fragments: general-coding
  com.github.haexmas.atoms.nix-python@a1b2c3d4 — installed
    composed artifacts: .spaex/generated/nix-packages.json
  com.github.haexmas.atoms.old-tool@e5f6a7b8 — pinned, not installed

Constitution: 42 clauses (MUST: 30, SHOULD: 10, MAY: 2)
  contributing molecules: com.github.haexmas.atoms.general-coding
  project-local fragments: none
  status: current

Drift:
  com.github.haexmas.atoms.old-tool: pinned but not installed
  → run `spaex install` to reconcile
```

**Sample output** (`--format json`, abbreviated):

```json
{
  "format_version": 1,
  "molecules": [
    {
      "molecule_id": "com.github.haexmas.atoms.general-coding",
      "pinned": {"source": "https://github.com/haexmas/atoms", "revision": "1a292194..."},
      "installed": {"source": "https://github.com/haexmas/atoms", "revision": "1a292194..."},
      "install_state": "installed",
      "hook_status": null,
      "atoms": {
        "behavior_fragments": ["general-coding"],
        "composed_artifacts": [],
        "files": []
      }
    }
  ],
  "constitution": {
    "exists": true,
    "clause_counts": {"MUST": 30, "SHOULD": 10, "MAY": 2},
    "contributing_molecules": ["com.github.haexmas.atoms.general-coding"],
    "project_local_fragment_ids": [],
    "stale": false
  },
  "drift": [
    {
      "kind": "pinned_not_installed",
      "molecule_id": "com.github.haexmas.atoms.old-tool",
      "pinned": {"source": "https://github.com/haexmas/atoms", "revision": "e5f6a7b8..."},
      "installed": null
    }
  ]
}
```

---

### `spaex trace <path>`

Prints which molecule(s) wrote a given repo-relative file, or every recorded file under a directory.

**Arguments**:
- `<path>`: a file or directory path. Accepts a repo-relative path, an absolute path inside the repository, a `./`-prefixed path, and a trailing slash (FR-011); all normalize to the same repo-relative answer. A path outside the repository is a usage error, not a "no match".
- `--format text|json`: output format. Default `text`.

**Read-only contract**: same as `spaex status` (FR-002).

**Exit codes**:
- 0: at least one owning molecule found.
- 1: no molecule is recorded for `<path>` (same convention `spaex constitution trace` already uses for "no match").
- 4: `.spaex/install.lock` is present but invalid.
- 7: `.spaex/manifest.json` is missing or invalid (see the note under `spaex status`'s exit codes).
- 64: `<path>` resolves outside the repository.

A missing `.spaex/install.lock` (manifest present, nothing installed yet) is not an error: every query reports "no match" (exit 1), since nothing has been installed.

**Relationship to `spaex constitution trace`**: `spaex trace .spaex/constitution.md` lists every molecule that contributes behavior and additionally prints a pointer to `spaex constitution trace <query>` for clause-level provenance (FR-009); it does not itself parse or list constitution clauses.

**Sample output** (`--format text`, single owner):

```text
Path: flake.nix
Owner:
  com.github.haexmas.atoms.nix-python@a1b2c3d4 (pinned in .spaex/manifest.json)
```

**Sample output** (`--format text`, shared path):

```text
Path: .spaex/constitution.md
Owners (3):
  com.github.haexmas.atoms.general-coding@1a292194
  com.github.haexmas.atoms.ponytail@1a292194
  com.github.haexmas.atoms.ast-grep@1a292194

For clause-level provenance, run `spaex constitution trace <query>`.
```

**Sample output** (`--format text`, no match):

```text
No molecule is recorded for README.md.
Hand-written files and files created by a molecule's install_hook are not
tracked by spaex.
```

**Sample output** (`--format json`, single owner):

```json
{
  "format_version": 1,
  "query": "flake.nix",
  "kind": "file",
  "matches": [
    {
      "path": "flake.nix",
      "owners": [
        {
          "molecule_id": "com.github.haexmas.atoms.nix-python",
          "source": "https://github.com/haexmas/atoms",
          "revision": "a1b2c3d4..."
        }
      ],
      "constitution_trace_hint": false
    }
  ],
  "error": null
}
```

**Sample output** (`--format json`, no match):

```json
{
  "format_version": 1,
  "query": "README.md",
  "kind": "file",
  "matches": [],
  "error": "no molecule is recorded for README.md"
}
```

## Modified subcommands

None. `spaex constitution trace` (Spec 023) is unchanged in behavior, output, exit codes and options (FR-016); it only moves its internal clause parser to a shared module (research.md R5), which is not user-visible.
