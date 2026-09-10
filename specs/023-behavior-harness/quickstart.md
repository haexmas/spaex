# Quickstart: Behavior Harness

Walkthrough of what a consumer and a molecule author do once spec 023 lands.

## For a consumer (developer using spaex)

### One-time: install the global bootstrap

```bash
spaex install --global claude,codex
```

Result: `~/.claude/CLAUDE.md` and `~/.config/codex/AGENTS.md` each get a small delimited spaex block instructing the runtime to read `.spaex.md` from the current project's root. Nothing else is touched.

Verify with `--check`:

```bash
spaex install --global --check
```

Exits 0 when both blocks are current.

### Per project: pin a molecule that ships behavior fragments

Edit `.spaex.json`:

```json
{
  "compounds": [
    {
      "molecule": "github.com/haexmas/atoms",
      "revision": "c1db86a…",
      "atoms": ["speckit-strict", "graphify-first-authoring"]
    }
  ]
}
```

Run:

```bash
spaex install
```

Result:
1. spaex materializes the molecules' fragments into `.spaex/constitution.d/<molecule-id>/<fragment-id>.md`.
2. Mechanical pre-check runs; hard intra-molecule conflicts abort with exit code 20.
3. Composer runs (via your Anthropic API key or the `claude` CLI, per `SPAEX_LLM_MODEL`); produces `.spaex.md` at the repo root.
4. If the Composer asks a clarification question, you answer once; the answer persists in `.spaex/clarifications.json` and is reused on future installs.

Stage and commit:

```bash
git add .spaex.json .spaex.md .spaex/constitution.d/ .spaex/clarifications.json
git commit -m "chore: adopt speckit-strict behavior harness"
```

### Runtime: open your agent

Any of `claude`, `codex`, `gemini` opened in this project now reads `.spaex.md` at session start and treats its MUST directives as inviolable.

Trace where a rule came from:

```bash
spaex constitution trace tests-before-commit
```

### Adding a project-local rule (additive-only)

Edit `.spaex.json` to add a local fragment:

```json
{
  "compounds": [...],
  "constitution": {
    "local_fragments": [
      {
        "id": "http-through-shared-client",
        "atom_source": "_project",
        "modality": "MUST",
        "body": "**MUST** route all outbound HTTP calls through the shared `httpx.AsyncClient` in `src/network/client.py`."
      }
    ]
  }
}
```

`spaex install`:
- Local fragment materializes under `.spaex/constitution.d/_project/http-through-shared-client.md`.
- Composer merges it into `.spaex.md` alongside atom-provided rules.
- If your local fragment tries to modify or downgrade a molecule-provided rule (same molecule-scoped id), install aborts with exit code 22 explaining the additive-only remedy.

## For a molecule author

### Ship a behavior fragment as an atom

In your molecule's source tree:

```text
your-molecule/
├── manifest.json
├── atoms/
│   └── behavior/
│       └── tests-before-commit.md
```

`your-molecule/manifest.json`:

```json
{
  "schema_version": 4,
  "molecule_id": "your-molecule",
  "atoms": {
    "behavior": ["tests-before-commit"]
  }
}
```

`your-molecule/atoms/behavior/tests-before-commit.md`:

```markdown
---
id: tests-before-commit
kind: constitution_fragment
atom_source: behavior.tests-before-commit
modality: MUST
tags: [testing, git]
---
**MUST** run the project's test suite before creating any commit. If tests fail,
address the failures before writing the commit.

**Rationale:** mocked test runs have historically masked broken migrations.
```

Publish the molecule at a commit SHA. Consumers pin the SHA and see the fragment materialize on their next `spaex install`.

### Ship behavior via a typed atom

Add a `constitution_fragments` block to your existing atom's manifest:

```json
{
  "type": "speckit_workflow",
  "id": "speckit-strict",
  "constitution_fragments": [
    {
      "id": "spec-first",
      "modality": "MUST",
      "body": "**MUST** run /speckit-specify before any implementation work on a non-trivial feature."
    }
  ]
}
```

Materialization treats inline entries identically to standalone fragments.

## For a maintainer developing spaex itself

### Run the fault-injection test suite

```bash
uv run pytest tests/behavior/fault_injection/
```

Covers the five Composer failure categories (timeout, runtime-error, invalid-output, quota, no-runtime) against a mock Composer harness.

### Run the reproducibility test

```bash
uv run pytest tests/behavior/integration/test_reproducibility.py
```

Runs `spaex install` twice on the same fixture project, asserts `.spaex.md` is byte-identical.

### Regenerate `.spaex.md` without a full install

```bash
spaex constitution build --force
```

Bypasses the source-hash check; useful for iterating on the Composer prompt.

### Manual verification: cross-runtime discoverability (SC-007)

The automated `test_bootstrap_discoverability.py` covers the CLI-level file-read behavior via mocks. Once per spaex release, a maintainer manually verifies that real runtimes actually respect `.spaex.md`:

1. Run `spaex install --global claude,codex,gemini` on a scratch account.
2. Create a fixture project with a single MUST fragment declaring an unambiguous constraint (e.g., "MUST prefix every reply with the token `HARNESS-OK`").
3. Open each runtime in the project and issue any prompt.
4. Verify each response begins with `HARNESS-OK`. This confirms the runtime actually read `.spaex.md` after the bootstrap indirection.
5. Record the observation in the release notes.

This is a small human-in-the-loop step because full-agent-behavior verification is out of scope for automated tests.

## Common failure modes and remedies

| Symptom | Exit code | Remedy |
|---------|-----------|--------|
| Two fragments same molecule same id, contradictory modality | 20 | Fix the molecule; one of its atoms has an author bug. |
| Cross-molecule semantic contradiction, operator declined to reconcile | 21 | Remove one molecule from `.spaex.json`, or add a project-local fragment that supersedes both, or provide a reconciling answer. |
| Project-local fragment tries to override atom-provided rule | 22 | Remove the offending molecule instead of trying to override its rule. |
| Composer timeout | 30 | Reduce fragment count, increase `SPAEX_COMPOSER_TIMEOUT`, or switch runtime. |
| Composer produced invalid output | 32 | Check `$SPAEX_COMPOSER_LOG` (default `.spaex/composer.log`); retry; report if reproducible. |
| No LLM runtime available | 34 | Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`; or install `claude`, `codex`, or `gemini` CLI. |

## What is NOT covered by this MVP

- Contextual-scope fragments (`scope: contextual`, `when: "..."`).
- Named preset switching (spec 019, roadmap Phase B).
- GUI composition surface (spec 021, roadmap Phase D).
- dsh emission target.
- `--allow-degraded` fallback to raw fragment concatenation.

All are on the roadmap; none block MVP.
