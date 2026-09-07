# Spec 014: Rename `haex-hive` to `spaex` and release to PyPI

**Status**: 2026-09-07 requirements capture. Feeds `/speckit-specify` to open `specs/014-rename-to-spaex/`.

**Purpose**: three co-shipping changes.

1. Full rebrand of the project from `haex-hive` to `spaex`. Every layer moves: PyPI package name, Python package name, CLI binary, config filename, output directory, schema version field, min-version field, environment variable, GitHub repo. This is a v4 breaking change to the manifest vocabulary. Scope was set explicitly to "Layer 3" during design.
2. First PyPI release under the new name at version `4.0.0`, distributed via `pipx install spaex`. GitHub Actions release workflow with PyPI Trusted Publishing (OIDC), no long-lived tokens.
3. README rewrite to match the new brand and the reduced scope. The multi-device swarm vision moves out of this project (see [holzi](https://github.com/haexmas/holzi) for the personal-agent plane). spaex is now positioned as a single-repo, single-device reproducible coding harness.

These three changes ship together because the PyPI release is only meaningful under the new name, and the README rewrite is only meaningful once the new name is real in the code.

**Related**:
- [Spec 007: Unified Manifest v3](../../specs/007-unified-manifest-v2/spec.md): defines the v3 molecule model. Spec 014 bumps the schema-version field name and value to `spaex_version: "4"` without touching the structural shape.
- [Spec 008: Install Transaction](../../specs/008-install-transaction/): unchanged in mechanics; the paths it writes (`.haex-hive/install.lock`, `.haex-hive/pending/`) rename to `.spaex/install.lock`, `.spaex/pending/`.
- [Spec 013: `haex add` / `haex remove` and v3 vocabulary](../../specs/013-add-cli-and-molecule-rename/): landed 2026-09-06. Its `haex_hive_version: "3"` migrate output is the input for Spec 014's `v3_to_v4` transform.
- `holzi` (out-of-tree, separate project): absorbs the personal-agent-plane and multi-device concerns that were previously part of the haex-hive vision. Spec 014's README rewrite drops that framing entirely.

## Motivation

Two independent forces converged.

**Scope realignment**. The project's original name embedded a vision of a device swarm (a "hive" of devices sharing agent state). That vision has been split out into a separate project. What remains here is deliberately narrower: one repo, one device, a reproducible coding harness. The `hive` metaphor no longer describes the tool; keeping it would mislead new adopters.

**Distribution readiness**. Spec 013 landed the last big piece of the v3 vocabulary and the `add`/`remove` CLI. The tool is now usable end to end, and there is a real motivation to make it installable via `pipx` rather than a local `pip install -e .`. Publishing under a name we already intend to drop would burn a PyPI namespace we do not want.

**Name selection** (see conversation log 2026-09-07): candidates were surveyed across three metaphor worlds (chemistry, harness, workshop). Final choice `spaex` is a portmanteau of `spec` and `haex`, keeping the maintainer's personal signature while shedding the hive metaphor. Confirmed as available on PyPI and under `github.com/haexmas/spaex`.

## Scope

Layer 3 as defined during the 2026-09-07 planning conversation. Everything user-visible and everything on disk changes name in one coordinated rebrand. No feature additions.

### In scope

- PyPI package name `haex-hive` becomes `spaex`.
- Python package `src/haex_hive/` becomes `src/spaex/`.
- CLI binary `haex` becomes `spaex`.
- Config file `.haex-hive.json` becomes `.spaex.json`.
- Output directory `.haex-hive/` becomes `.spaex/`.
- Lock file `.haex-hive.json.lock` becomes `.spaex.json.lock`.
- Publication lock `.haex-hive/install.lock` becomes `.spaex/install.lock`.
- Schema-version field `haex_hive_version: "3"` becomes `spaex_version: "4"`.
- Min-version field `haex_hive_min_version` becomes `spaex_min_version`.
- Environment variable `$HAEX_HIVE_STATE` becomes `$SPAEX_STATE`.
- GitHub repository `haexmas/haex-hive` renames to `haexmas/spaex` (GitHub redirect handles old URLs automatically).
- Migrate chain gains `v3_to_v4` transform. Chain becomes v1→v2→v3→v4.
- Repo self-adoption: the repo's own `.haex-hive.json`, `manifest.json`, and `.specify/memory/manifest.json` migrate to v4 using `spaex migrate`.
- Constitution amendment: `.specify/memory/constitution.md` currently contains 18 `haex-hive` references including the title. Renamed to `spaex Constitution`, prose updated to reference `spaex` and `.spaex.json`. Principles themselves unchanged.
- First PyPI release: `spaex 4.0.0` published via GitHub Actions and OIDC Trusted Publishing (setup already registered by the maintainer on 2026-09-07).
- README rewrite reflecting the new brand and the reduced scope.

### Out of scope

- No new CLI verbs, no new features beyond the rename.
- No refactor of adjacent modules (Spec 008 install transaction, Spec 011 workflow, Spec 013 add/remove) beyond the mechanical rename.
- No dev-environment orchestration (`spaex enter`, `spaex shell`, container lifecycle). Slot 015 is reserved for a future spec if that direction is pursued (see Follow-ups).
- No TestPyPI branch in the release workflow. Add later if release cadence justifies it.
- No multi-platform wheel build. `py3-none-any` is enough for a pure-Python package.
- No auto-generated release notes as part of the workflow. `gh release create --generate-notes` remains a manual post-release step.

### Unchanged

- Domain vocabulary `atoms{}` / `molecules[]` / `compounds[]` stays. That naming survived Spec 013 and is a stable part of the model.
- Schema structural shape is unchanged. Only the version field name and value change (`haex_hive_version: "3"` becomes `spaex_version: "4"`).
- Molecule and publisher `manifest.json` filenames stay (`manifest.json` is a generic, unqualified name and needs no rebrand).
- Refusal keys, exit codes, and diagnostic wording of every existing command stay.
- `.specify/memory/constitution.md` principle text stays; only prose references and title rename.

## Rename mapping

Canonical table used by every phase.

| Category | Before | After |
|---|---|---|
| PyPI package | `haex-hive` | `spaex` |
| Python package | `haex_hive` | `spaex` |
| CLI binary | `haex` | `spaex` |
| Config file | `.haex-hive.json` | `.spaex.json` |
| Output directory | `.haex-hive/` | `.spaex/` |
| Config lock file | `.haex-hive.json.lock` | `.spaex.json.lock` |
| Publication lock | `.haex-hive/install.lock` | `.spaex/install.lock` |
| Schema-version field | `haex_hive_version: "3"` | `spaex_version: "4"` |
| Min-version field | `haex_hive_min_version` | `spaex_min_version` |
| Environment variable | `$HAEX_HIVE_STATE` | `$SPAEX_STATE` |
| GitHub repo slug | `haexmas/haex-hive` | `haexmas/spaex` |
| Schema `$id` URLs | `https://haex-hive.dev/schema/*.v3.json` (or equivalent) | `https://spaex.dev/schema/*.v4.json` (subject to actual current values; auditor checks) |

## Migration strategy

**Chained transform, not hard cut**. Extend `src/haex_hive/migrate/transform.py` (renamed to `src/spaex/migrate/transform.py` in Phase 2) with `v3_to_v4`. The chain becomes v1→v2→v3→v4. Idempotent on v4 inputs. Same defensive shape as Spec 013's v2→v3 addition.

**Rationale for keeping the shim**: pre-user status means we do not need a polished migration UX, but adding one link to the chain costs almost nothing and protects private side-branches or forks that still run v3. Cutting the chain to save a few hundred lines is not worth the risk.

**Field mapping in `v3_to_v4`**:
- `haex_hive_version: "3"` becomes `spaex_version: "4"`.
- `haex_hive_min_version: "3.x.y"` becomes `spaex_min_version: "4.x.y"`. Lower bound `>=3.x.y` becomes `>=4.0.0`. Any other major refuses with `unsupported-min-version-constraint`, matching the v2→v3 pattern exactly.
- Structural shape unchanged: `atoms{}`, `molecules[]`, `compounds[]` stay as they are.

**Proposal placement** (matching Spec 013's local placement contract):
- Input `.haex-hive.json` (v3) produces sibling `.spaex.json.migrated`.
- Input `manifest.json` (v3 publisher or molecule) produces sibling `manifest.json.migrated` with `spaex_version: "4"` in the body.
- Adoption instruction printed in the diff output: `mv .spaex.json.migrated .spaex.json && rm .haex-hive.json`.
- `.haex-hive/` (runtime output directory) is not touched by migrate. The operator deletes it after adoption, and the next `spaex install` produces `.spaex/`.

**Self-adoption in Phase 4** (mirrors Spec 013 tasks T030–T033):
1. Run `spaex migrate` against the repo root.
2. Adopt every `.migrated` sibling by rename plus deletion of the legacy input.
3. Rename `.haex-hive/` to nothing (delete). Runtime state, regenerated on next install.
4. Run `spaex install` locally against the migrated root.
5. Run `spaex install` a second time and confirm byte-identical `.spaex/install.lock` output. Spec 008 SC-003 in the new vocabulary.

**No removal of v1/v2 transformers**. They stay in `migrate/transform.py` as part of the chain. No reason to cut existing migration paths.

## Sequencing

Six phases, six PRs against `main`, in strict linear order. No parallel work between phases to keep merge conflicts controllable. Memory `pr_strategy_stacked_phases` applies: every phase PR targets `main`, not the previous phase's branch.

### Phase 1: schema payloads v4 and version dispatch (dead code)

- Add new schema files under `src/haex_hive/schema/data/`:
  - `consumer-manifest.v4.schema.json`
  - `molecule-manifest.v4.schema.json`
  - `publisher-manifest.v4.schema.json`
  - `install-lock.v4.schema.json`
- Schema loader keeps dispatching on v3 for now. The v4 files are inert.
- Version bump `pyproject.toml` from `3.0.0.dev0` to `4.0.0.dev0` (still dev, no release yet).
- `pyproject.toml` `description` field updated to reference `spaex 4.0` (still under the old `haex-hive` project name at this point).

### Phase 2: foundational rename

- `git mv src/haex_hive src/spaex` in one commit.
- Update every `from haex_hive.*` import in `src/` and `tests/` to `from spaex.*`.
- Update `pyproject.toml`: `name = "spaex"`, entry point `[project.scripts]` sets `spaex = "spaex.cli.main:main"`, `[tool.setuptools.package-data] spaex = ["schema/data/*.json"]`, mypy packages, pytest pythonpath.
- Rename config-file constants: `.haex-hive.json` becomes `.spaex.json`, `.haex-hive/` becomes `.spaex/`, `.haex-hive.json.lock` becomes `.spaex.json.lock`.
- Rename environment variable: `HAEX_HIVE_STATE` becomes `SPAEX_STATE`. Grep for every read site and every doc reference.
- Loader now dispatches on v4. v3 read path remains only inside the migrate module.
- Every test fixture rewritten from v3 to v4 shape. Grep for `haex_hive_version.*3` and convert to `spaex_version: "4"`.

### Phase 3: `v3_to_v4` migrate transform

- Extend `src/spaex/migrate/transform.py` with the `v3_to_v4` function.
- Unit tests: contract behavior on consumer, molecule, publisher, install-lock shapes. Idempotency on v4 inputs. Min-version rewrite per the mapping above.
- Integration test: run `spaex migrate` on a v3 fixture repo, adopt every proposal, confirm `spaex install` succeeds.
- CLI diff output references `spaex` in adoption instructions, not `haex`.

### Phase 4: self-adopt the repo

- Run `spaex migrate` against the repo root.
- Adopt every `.migrated` sibling. Delete the legacy `.haex-hive.json`, `.haex-hive/` and any legacy `manifest.json` intermediates.
- Rewrite `.specify/memory/constitution.md`: title becomes `spaex Constitution`, 18 prose references to `haex-hive`, `haex`, and `.haex-hive.json` update to the new names. Principle text unchanged.
- Rewrite `.specify/memory/manifest.json` to `spaex_version: "4"`.
- Update the repo's own `manifest.json` (publisher root) accordingly.
- Run `spaex install` twice. Confirm byte-identical `.spaex/install.lock` output. Commit the resulting state.

### Phase 5: docs sweep

- README rewrite following the outline in the README-Rewrite section below.
- Sweep every quickstart, every spec doc, every ADR, every plan doc for `haex-hive`, `haex_hive`, `haex`, `HAEX_HIVE`, `.haex-hive`. Update where they refer to the current name; keep historical references (e.g., "originally named haex-hive, renamed 2026-09-07") where the context is historical.
- Update `CLAUDE.md` and `AGENTS.md` at repo root.
- Reference to the new package name in `docs/adr/` where relevant. Add ADR 0011 (or next free ADR number) noting the rename decision and pointing at Spec 014.

### Phase 6: release workflow and first PyPI release

- Add `.github/workflows/release.yml` with the skeleton captured in the Release Workflow section below.
- Bump `pyproject.toml` version from `4.0.0.dev0` to `4.0.0`, commit.
- Tag `v4.0.0` and push. Workflow builds sdist plus wheel and publishes to PyPI via OIDC.
- Verify `pipx install spaex` from PyPI succeeds; `spaex --version` reports `4.0.0`.
- Post-release: bump version to `4.0.1.dev0` on `main`, commit.
- Create GitHub Release manually: `gh release create v4.0.0 --generate-notes`.

## Release workflow

**PyPI Trusted Publishing** via GitHub Actions OIDC. Registered by the maintainer on 2026-09-07:
- PyPI project: `spaex`
- GitHub owner: `haexmas`
- Repository: `spaex`
- Workflow filename: `release.yml`
- Environment: `pypi`

**Workflow file** `.github/workflows/release.yml`:

```yaml
name: release
on:
  push:
    tags: ['v*']
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: python -m pip install --upgrade pip build
      - run: python -m build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
  publish:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/spaex
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
```

**Release procedure**:
1. On `main`, bump `pyproject.toml` version from `4.0.0.dev0` to `4.0.0`. Commit.
2. `git tag v4.0.0 && git push origin v4.0.0`.
3. Workflow triggers, builds artifacts, publishes to PyPI via OIDC.
4. On success, bump `main` version to `4.0.1.dev0`. Commit.
5. `gh release create v4.0.0 --generate-notes`.

**Existing CI**: `spec-007-ci.yml` continues to run tests on pull requests. Orthogonal to the release workflow; no changes needed there beyond the mechanical rename inside job steps (paths reference `spaex` not `haex_hive`).

## README rewrite

Applies in Phase 5. Full rewrite, not a patch.

**New header**: `# spaex — reproducible coding harnesses for any repo and development environment`

**Status line**: `4.0.0` (after release). Link to ADR 0011 and Spec 014 for the rename history.

**What it is** (2-3 sentences):
> spaex composes a coding harness for a single repo out of reusable pieces (skills, MCPs, constitutions, slash commands, dev-environment files, collectively "molecules"). You declare which molecules you want in `.spaex.json`. `spaex install` writes them into `.claude/`, `.codex/`, and `.spaex/` deterministically, pinned by SHA.

**What you can do today** (verb list):
- `spaex add`: adopt a molecule from a source URL into your `.spaex.json`.
- `spaex remove`: retract a molecule from `.spaex.json`.
- `spaex install`: publish adopted molecules atomically into their participating roots.
- `spaex migrate`: rewrite legacy `.haex-hive.json` (v1/v2/v3) into `.spaex.json` (v4).
- `spaex constitution show`: print the effective constitution assembled from adopted molecules.

**Dev-environment placement** (one paragraph, no new features):
> Molecules can declare `atoms.dev_environment: ["flake.nix"]` (or a `Dockerfile`, `devcontainer.json`, `.envrc`, `shell.nix`). `spaex install` places the declared files into the repo like any other atom category. Orchestration (entering the shell, starting the container) stays outside the tool for now; see `docs/plans/` for the Slot 015 direction.

**Install**:
```bash
pipx install spaex
```

Development install:
```bash
git clone https://github.com/haexmas/spaex.git
cd spaex
pip install -e '.[dev]'
```

Requires Python 3.10+ and Git 2.30+ on `$PATH`. Only runtime dependency is `jsonschema`.

**Migration from haex-hive v3**: one paragraph. `pipx install spaex`, then `spaex migrate` at the repo root, then adopt every `.migrated` sibling, then `spaex install`. Old `.haex-hive.json` and `.haex-hive/` get deleted after adoption.

**Multi-device vision**: one line pointing at [holzi](https://github.com/haexmas/holzi). No roadmap block for a swarm in this README.

## Success criteria

Verifiable at the end of Phase 6.

- **SC-001**: `pipx install spaex` from PyPI succeeds. `spaex --version` reports `4.0.0`.
- **SC-002**: Every test in the repository passes after Phase 2 lands and stays green through Phase 6.
- **SC-003**: `spaex install` produces byte-identical `.spaex/install.lock` output across two consecutive runs on unchanged inputs. Spec 008 SC-003 preserved under the new vocabulary.
- **SC-004**: `spaex install` against the migrated repo root (Phase 4 self-adoption) succeeds and produces the expected `.spaex/` tree.
- **SC-005**: `spaex migrate` on a v3 fixture repo produces valid v4 proposals per contract. Contract, unit, and integration tests all green.
- **SC-006**: `rg 'haex[_-]hive'` and `rg '\bhaex\b'` find no live references in `src/`, `tests/`, `pyproject.toml`, `README.md`, `CLAUDE.md`, `AGENTS.md`. Historical references in `docs/adr/`, `docs/plans/`, and `specs/` remain by design; that is how history is recorded.
- **SC-007**: GitHub Actions release workflow succeeds on `v4.0.0` tag push. PyPI project page shows `spaex 4.0.0`.
- **SC-008**: Constitution `.specify/memory/constitution.md` has zero `haex-hive` references; title reads `spaex Constitution`; principle text unchanged from the pre-rename version (verified by diff review, not just word count).

## Risks

**Merge conflicts across phases**. Every phase touches many files. Parallel phase work would guarantee conflicts. Mitigation: strict linear phase order. No branching from `main` between phase merges.

**Forgotten constants in test fixtures**. Grep-and-replace tools can miss token-boundary edges (e.g., `haex` inside a longer identifier). Mitigation: a Phase-7-style polish pass after Phase 5 running `rg 'haex[_-]hive'` and `rg '\bhaex\b'` and reviewing every hit.

**PyPI first-publish failure**. If the workflow fails on the first `v4.0.0` push, the tag exists but the release did not happen. Mitigation: the `pypi` GitHub Environment has a required-reviewer gate for the initial publish. Re-run is safe (PyPI does not reuse a version, but `4.0.1` can follow within minutes).

**Schema `$id` URLs**. If the current schemas embed URLs like `https://haex-hive.dev/...`, those URLs need a decision: point at a spaex-owned domain, or drop the domain and rely on relative `$id`s. Phase 1 auditor checks the current values and picks per finding.

**Constitution amendment risk**. The constitution has principle-text discipline: changes to principles need review. Phase 4 only changes prose references and the title, not principle text. Reviewer should diff carefully to confirm.

**GitHub repo rename side effects**. GitHub redirects the old URL, but external links (Slack, docs written by others, old issue templates) may cache the old slug. Mitigation: keep the redirect in place (default GitHub behavior); update repo description immediately after rename.

## Follow-ups

**Slot 015 reservation: dev-environment orchestration**. Reserved but not specified in Spec 014. Concept: new verbs (`spaex enter`, `spaex shell`, `spaex dev up`) that wrap `nix develop`, `docker compose up`, `devcontainer up`. Design work triggered when the maintainer decides to pursue orchestration beyond placement.

**Memory sweep**. The `~/.claude/projects/-home-haex-Projekte-haex-hive/memory/` directory has five files with `haex-hive`/`haex_hive` in name or content (`haex_hive_pre_user`, `haex_hive_context_budget`, `haex_hive_personal_agent_plane`, `haex_hive_constitution_terminology`, `haex_hive_empty_state_valid`). Also `MEMORY.md` uses `haex-hive` in entry text. Rename files and update contents after Phase 6 lands. Directory path itself is a Claude-Code implementation detail; leave that as is (it is keyed by the working directory).

**TestPyPI**. Optional future addition to the release workflow. Add a separate job on `v*rc*` or `v*.dev*` tags that publishes to `test.pypi.org`. Not needed for the first release.

**Multi-platform wheels**. Not needed for a pure-Python package. Revisit only if `spaex` grows a native extension (unlikely in current design).
