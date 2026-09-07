# Feature Specification: Rename to spaex (v4 breaking) and first PyPI release

**Feature Branch**: `014-rename-to-spaex`
**Created**: 2026-09-07
**Status**: Draft
**Input**: User description: "Rename the project from `haex-hive` to `spaex`, ship the v4 breaking manifest vocabulary that accompanies the rename, and publish the first PyPI release under the new name."

**Design source**: [docs/plans/2026-09-07-rename-to-spaex-design.md](../../docs/plans/2026-09-07-rename-to-spaex-design.md) is the authoritative requirements capture. This spec restates that plan in Speckit shape for `/speckit-plan` and `/speckit-tasks` to consume.

## Clarifications

### Session 2026-09-07

- Q: How do we keep `main` coherent given that Phase 2 (foundational rename) alone leaves the repo's own v3 manifests unreadable until Phase 4 (self-adopt) also lands? → A: Bundle Phase 2 and Phase 4 in one PR. Phase 3 (v3→v4 migrate) lands as its own PR beforehand so the self-adopt step in the combined P2+P4 PR can actually invoke `spaex migrate`. Revised PR sequence: **P1 → P3(migrate) → P2+P4 combined → P5(release) → P6(polish)**. `main` never sees a broken state.
- Q: Does the local repo directory `/home/haex/Projekte/haex-hive/` rename to match? → A: Yes, but as the **very last step**, after all five PRs have merged and the local session is deliberately closed. Renaming the cwd out from under a running shell breaks the shell, running watchers, IDE indexers, and the Claude Code session itself. Add a Phase 6 task that is explicitly marked "run after session close": `mv /home/haex/Projekte/haex-hive /home/haex/Projekte/spaex`, plus copying the Claude Code memory directory `~/.claude/projects/-home-haex-Projekte-haex-hive/` to `~/.claude/projects/-home-haex-Projekte-spaex/`. The operator opens a new shell in the new path afterward.
- Q: How does Spec 014 treat the atom-category name for dev-environment files (`flake.nix`, `Dockerfile`, etc.)? → A: **Spec 014 makes no naming commitment.** FR-043 is reduced to a generic "atom categories are open" statement in the README. The multi-environment story (declarable `dev`/`staging`/`prod` environments, consumer-side selection, orchestration verbs) is the scope of Spec 015 (renamed from "dev-environment orchestration" to "multi-environment declaration + orchestration"). A short Slot 015 placeholder design doc is written to `docs/plans/2026-09-07-slot-015-multi-environment-placeholder.md` at Spec 014 session close.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator uses the new brand end to end (Priority: P1) 🎯 MVP

An operator adopting the tool for the first time (or an existing user picking up the new version) sees a single, consistent product name across every surface they touch: the CLI command they type, the config file they edit, the directory the tool writes to, the environment variable they set, the docs they read, and the schema `version` field their manifests declare. Nothing in the daily flow still says `haex-hive`, `haex`, or `haex_hive`.

**Why this priority**: This is the whole point of the feature. Without a clean, complete rebrand, the release is worse than not renaming at all: a schizophrenic tool that looks one way outside and another way inside erodes trust and generates support burden. If we shipped only this and nothing else, we still have a usable, coherent tool.

**Independent Test**: Fresh checkout of the renamed repo. Create a new empty project directory, run `spaex install` there, confirm every user-visible artifact (CLI help text, config filename, output directory, error messages, doc snippets) uses `spaex` and `.spaex.json` / `.spaex/` and `spaex_version: "4"`. Run `rg 'haex[_-]hive'` and `rg '\bhaex\b'` across `src/`, `tests/`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `pyproject.toml` and confirm zero live references (historical references under `docs/adr/`, `docs/plans/`, `specs/` are expected and allowed).

**Acceptance Scenarios**:

1. **Given** a fresh clone of the renamed repo, **When** the operator runs `spaex --help`, **Then** every command, option, and description uses `spaex` and refers to `.spaex.json`, never `haex` or `.haex-hive.json`.
2. **Given** an operator writes a v4 `.spaex.json` with `spaex_version: "4"` and one compound entry, **When** they run `spaex install`, **Then** the tool writes to `.spaex/install.lock` and produces byte-identical output on a second run.
3. **Given** an operator sets `$SPAEX_STATE=/some/path`, **When** they run any `spaex` command that touches state, **Then** the tool honors that env var and never reads `$HAEX_HIVE_STATE`.
4. **Given** the repo's own `.specify/memory/constitution.md`, **When** an operator reads it after this feature lands, **Then** its title reads "spaex Constitution" and every prose reference to the tool uses `spaex`. Principle text is byte-identical to the pre-rename version except for prose references.

---

### User Story 2 - Existing v3 project migrates cleanly to v4 (Priority: P1)

An operator who adopted `haex-hive` v3 on their project now upgrades to `spaex`. Their existing `.haex-hive.json`, `manifest.json` files (publisher root and per-molecule), and directory structure are all v3 shape. They need a mechanical, review-gated migration path (matching the `haex migrate` v1→v2→v3 pattern) that produces v4 proposals for every affected file, tells them what to rename, and never mutates their files without their consent.

**Why this priority**: Anyone who tried the tool before this rename lives on v3. Without a migration path they either hand-edit dozens of files or abandon the tool. Since the v1→v2 and v2→v3 chain established the pattern, adding a v3→v4 link keeps the promise the tool already made.

**Independent Test**: Take a v3 fixture repo (publisher root plus consumer plus one molecule). Run `spaex migrate` at the consumer root. Confirm three `.migrated` sibling files are produced. Adopt them per the printed instructions (`mv .spaex.json.migrated .spaex.json && rm .haex-hive.json`, and the equivalent for `manifest.json` sibling files). Run `spaex install`. Confirm the output validates as v4 and is byte-identical across two runs.

**Acceptance Scenarios**:

1. **Given** a v3 consumer `.haex-hive.json`, **When** the operator runs `spaex migrate`, **Then** a `.spaex.json.migrated` sibling is written next to the original file. The original is untouched.
2. **Given** a v3 publisher-root `manifest.json` and per-molecule `manifest.json`, **When** the operator runs `spaex migrate`, **Then** each file gets a `.migrated` sibling with `spaex_version: "4"` in the body and structural fields unchanged (only the version-field and min-version-field names change).
3. **Given** a v3 file with `haex_hive_min_version: "3.2.0"`, **When** it is migrated, **Then** the proposal contains `spaex_min_version: "4.2.0"` (exact-major rewrite). A `>=3.x.y` lower bound rewrites to `>=4.0.0`. Any other major (e.g., `~2.0.0`, `>=1`) refuses with `unsupported-min-version-constraint` naming the offending constraint.
4. **Given** a v4 input already, **When** `spaex migrate` runs, **Then** it is a no-op for that file with exit code 0. Idempotency.
5. **Given** a v1 or v2 input, **When** `spaex migrate` runs, **Then** the full chain (v1→v2→v3→v4) applies and the final proposal is v4. Existing v1→v2 and v2→v3 transformers remain in place, unchanged in behavior.
6. **Given** the operator adopts every proposal and deletes the legacy files, **When** they run `spaex install`, **Then** the tool produces `.spaex/install.lock` and no legacy `.haex-hive/` directory or `.haex-hive.json` is required.

---

### User Story 3 - Public availability via pipx (Priority: P2)

An operator new to the tool wants to install it without cloning a repo. They run `pipx install spaex`, and the CLI is on their `$PATH` as `spaex`. From there they follow the Quickstart in the README.

**Why this priority**: This unlocks adoption beyond the maintainer's local checkout. It is P2 not P1 because everything in P1 works from a source install; the PyPI release layers distribution on top. The rebrand delivers value even before the first PyPI push. But the two ship together for a coherent launch.

**Independent Test**: On a machine with `pipx` installed and Python 3.10+ available, run `pipx install spaex`. Confirm `spaex --version` reports `4.0.0`. Run `spaex --help`. In an empty directory, create a minimal `.spaex.json` and run `spaex install`. Confirm normal end-to-end behavior.

**Acceptance Scenarios**:

1. **Given** the GitHub Actions release workflow triggered by tag push `v4.0.0`, **When** the workflow completes, **Then** PyPI project page shows `spaex 4.0.0` and the sdist plus wheel are published via OIDC (no long-lived tokens involved).
2. **Given** PyPI has `spaex 4.0.0`, **When** an operator runs `pipx install spaex`, **Then** the CLI is installed and `spaex --version` reports `4.0.0`.
3. **Given** the release workflow ran, **When** the maintainer runs `gh release create v4.0.0 --generate-notes`, **Then** a GitHub Release is created for the tag with auto-generated notes summarizing merged pull requests since the last tag.

---

### Edge Cases

- **Legacy `.haex-hive/` output directory after migration**: `spaex migrate` does not touch runtime output directories. The operator deletes `.haex-hive/` manually after adopting the proposals; the next `spaex install` produces `.spaex/`.
- **Old GitHub repository URLs**: GitHub redirects `haexmas/haex-hive` to `haexmas/spaex` automatically after rename. External docs and Slack messages continue to work via redirect; the repo description is updated to name the current identity.
- **Users with private forks on v3**: The chained migrate transform means their `spaex migrate` still works.
- **`pipx install spaex` failure due to Python version**: The tool declares `requires-python = ">=3.10"`. `pipx` reports the version mismatch clearly; no in-tool workaround is needed.
- **Concurrent `spaex install` runs during migration**: The manifest-lock and install-mutex from Spec 008 apply unchanged under the new filenames (`.spaex.json.lock`, `.spaex/install.lock`).
- **Two operators trying to rename `haex-hive` GitHub repo simultaneously**: Not a tool concern; GitHub UI serializes.
- **Schema `$id` URLs in the JSON schema files**: If the current v3 schemas embed absolute URLs like `https://haex-hive.dev/...`, Phase 1 auditor decides between renaming to `https://spaex.dev/...` (if that domain is or will be controlled) or making the `$id` relative. Neither choice affects consumer behavior since the schemas are loaded from `src/spaex/schema/data/`, not fetched.
- **Historical references in `docs/adr/`, `docs/plans/`, `specs/`**: Deliberately kept. These are historical records; rewriting them would falsify the history.

## Requirements *(mandatory)*

### Functional Requirements

**Naming and layout (US1)**

- **FR-001**: System MUST distribute under PyPI project name `spaex`. The name in `pyproject.toml` MUST be `spaex`.
- **FR-002**: System MUST expose the CLI binary as `spaex`. The `[project.scripts]` entry in `pyproject.toml` MUST bind `spaex` to `spaex.cli.main:main`.
- **FR-003**: System MUST host the Python package at `src/spaex/`. No `haex_hive` module SHALL remain importable in the source tree after Phase 2.
- **FR-004**: System MUST read its per-project config from `.spaex.json` and MUST NOT read `.haex-hive.json` outside the migrate module.
- **FR-005**: System MUST write its runtime output under `.spaex/` (including `.spaex/install.lock`, `.spaex/pending/`) and MUST NOT write to `.haex-hive/`.
- **FR-006**: System MUST use `.spaex.json.lock` as the config-file advisory lock name (Spec 008 manifest-lock semantics unchanged).
- **FR-007**: System MUST read the state-directory location from the environment variable `SPAEX_STATE` (previously `HAEX_HIVE_STATE`). If unset, fall back to the existing default path convention.

**Manifest schema vocabulary (US1)**

- **FR-010**: System MUST recognize `spaex_version: "4"` as the version marker for v4 manifests (consumer, publisher, molecule, install-lock). Any other value at the read gate MUST refuse with a diagnostic that names `spaex migrate` as the next step.
- **FR-011**: System MUST recognize `spaex_min_version` in place of `haex_hive_min_version`. Semantics unchanged (exact-version and lower-bound constraints).
- **FR-012**: System MUST leave the structural shape of every v4 manifest identical to its v3 counterpart. Only the version-field name and value, and the min-version-field name, change. `atoms{}`, `molecules[]`, `compounds[]` names and semantics stay.
- **FR-013**: System MUST publish v4 schema payloads under `src/spaex/schema/data/`: `consumer-manifest.v4.schema.json`, `molecule-manifest.v4.schema.json`, `publisher-manifest.v4.schema.json`, `install-lock.v4.schema.json`.

**Migration (US2)**

- **FR-020**: System MUST extend the migrate chain in `src/spaex/migrate/transform.py` with a `v3_to_v4` transform. The chain order becomes v1→v2→v3→v4. Existing v1→v2 and v2→v3 transforms MUST remain in place unchanged.
- **FR-021**: System MUST produce local proposals as `.migrated` siblings of the input files. For a v3 consumer at `.haex-hive.json`, the proposal is `.spaex.json.migrated`. For a `manifest.json`, the proposal is `manifest.json.migrated` with `spaex_version: "4"` in the body.
- **FR-022**: System MUST print adoption instructions in the diff output that reference the target filenames (`mv .spaex.json.migrated .spaex.json && rm .haex-hive.json`).
- **FR-023**: System MUST NOT touch runtime output directories (`.haex-hive/`, `.spaex/`) during migration. The operator is responsible for removing legacy runtime dirs before the next install.
- **FR-024**: System MUST be idempotent on v4 inputs (exit 0, no proposals).
- **FR-025**: System MUST honor existing `--dry-run` and `--check` semantics from Spec 013 without change under the new chain link.
- **FR-026**: System MUST refuse with `unsupported-min-version-constraint` for any `spaex_min_version` migration where the input constraint is not exact (`3.x.y`) or lower-bound-only (`>=3.x.y`), matching the v2→v3 pattern.
- **FR-027**: System MUST preserve exit-code precedence from Spec 013: 2 for hard refusal without any proposal, 1 for mixed proposal-plus-refusal, 0 for success or all-v4 no-op.

**Self-adoption and constitution (US1)**

- **FR-030**: System MUST self-adopt in the same feature: the repo's own `.haex-hive.json`, `manifest.json` (publisher root), and `.specify/memory/manifest.json` (constitution molecule) MUST be v4 shape after the feature lands.
- **FR-031**: System MUST rename `.specify/memory/constitution.md` prose references and its title from `haex-hive Constitution` to `spaex Constitution`. Principle text (the invariants themselves) MUST be byte-identical to the pre-rename version except for prose references to the tool name.
- **FR-032**: System MUST produce byte-identical `.spaex/install.lock` output across two consecutive `spaex install` runs on the self-adopted repo. (Spec 008 SC-003 in the new vocabulary.)

**Documentation (US1)**

- **FR-040**: Documentation (README, quickstart files, `CLAUDE.md`, `AGENTS.md`, ADRs) MUST refer to `spaex` and the new filenames as the current identity. Historical references in `docs/adr/`, `docs/plans/`, and `specs/` are exempted where they capture the pre-rename state as history.
- **FR-041**: README MUST use the tagline `# spaex — reproducible coding harnesses for any repo and development environment`.
- **FR-042**: README MUST reference `pipx install spaex` as the primary install command. Development-install `pip install -e '.[dev]'` remains as a secondary path.
- **FR-043**: README MUST mention that molecule authors can declare any atom category name they like (the schema treats category keys as open) and that `spaex install` places declared files under participating roots by convention. Common categories today are `constitution`, `slash_commands`, `agents`, `mcps`; new categories are added by convention without a schema change. Spec 014 makes **no** naming commitment for environment-config files (`flake.nix`, `Dockerfile`, `devcontainer.json`, `.envrc`, `shell.nix`, etc.); the multi-environment vocabulary and orchestration are the scope of Spec 015. README MAY note that Spec 015 is planned and link the placeholder design doc.
- **FR-044**: README MUST NOT promise multi-device swarm functionality. That vision moves to a linked separate project (`holzi`).
- **FR-045**: A new ADR MUST be added (next free ADR number, likely 0011) recording the rename decision and pointing at Spec 014.

**Release (US3)**

- **FR-050**: A GitHub Actions workflow at `.github/workflows/release.yml` MUST build sdist plus wheel and publish to PyPI on `v*` tag pushes.
- **FR-051**: The release workflow MUST use PyPI Trusted Publishing (OIDC) via `pypa/gh-action-pypi-publish@release/v1`. No long-lived PyPI tokens are stored in GitHub Secrets.
- **FR-052**: The workflow MUST run inside a GitHub Environment named `pypi`. That environment MAY be configured with a required-reviewer gate at the maintainer's discretion.
- **FR-053**: On the first release tag `v4.0.0`, the `pyproject.toml` version MUST be `4.0.0` (not `4.0.0.dev0`). Post-release, the version on `main` MUST be bumped to the next dev version (e.g., `4.0.1.dev0`).
- **FR-054**: A GitHub Release MUST be created for the tag using `gh release create v4.0.0 --generate-notes` as a manual post-workflow step. The workflow itself does not create the GitHub Release.

### Key Entities *(include if feature involves data)*

- **`.spaex.json` (consumer manifest v4)**: Same shape as `.haex-hive.json` v3. Contains `spaex_version: "4"`, `compounds[]` with per-compound `source`, `revision`, and `molecules[]`. The one filename change and the two field-name changes are the entire v4 delta.
- **`manifest.json` v4 (publisher root and per-molecule)**: Same shape as v3 counterparts. `spaex_version: "4"`. Publisher root maps `molecules{}`; molecule manifest declares `atoms{}` category map plus metadata.
- **`.spaex/install.lock` (v4 publication record)**: Same shape as v3 `.haex-hive/install.lock`. `spaex_version: "4"`. Records `molecules[]` with `id`, `revision`, `source`, and `paths[]`.
- **`v3_to_v4` transform**: Reads a parsed v3 JSON blob, returns the parsed v4 JSON blob. One entry point per manifest shape (consumer, publisher, molecule, install-lock). Dispatches by input shape.
- **Release artifact**: The sdist plus wheel produced by `python -m build` from the tagged `main` commit and published to PyPI project `spaex`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can install the tool from PyPI in one command: `pipx install spaex` succeeds and `spaex --version` reports `4.0.0`.
- **SC-002**: The test suite is fully green after every phase. No test in the repository fails from Phase 2 landing through the end of Phase 6.
- **SC-003**: `spaex install` produces byte-identical `.spaex/install.lock` output across two consecutive runs on the self-adopted repo. (Spec 008 SC-003 preserved.)
- **SC-004**: `spaex install` against the migrated repo root succeeds and produces the expected `.spaex/` tree.
- **SC-005**: `spaex migrate` on a v3 fixture repo produces valid v4 proposals for every affected file, with exit code 0, and adopting the proposals plus running `spaex install` succeeds.
- **SC-006**: Running `rg 'haex[_-]hive'` and `rg '\bhaex\b'` finds zero live references in `src/`, `tests/`, `pyproject.toml`, `README.md`, `CLAUDE.md`, `AGENTS.md`. Historical references in `docs/adr/`, `docs/plans/`, `specs/` remain by design.
- **SC-007**: The GitHub Actions release workflow succeeds on `v4.0.0` tag push. The PyPI project page shows `spaex 4.0.0` with sdist plus wheel artifacts.
- **SC-008**: `.specify/memory/constitution.md` has zero `haex-hive` prose references, title reads `spaex Constitution`, and principle text is byte-identical to the pre-rename version except for prose references (verified by diff review).
- **SC-009**: An operator on a v3 project can complete the full migration path (`spaex migrate` → adopt proposals → delete legacy files → `spaex install`) in under 5 minutes on a small fixture project (single publisher, single molecule). Time-bounded to prove the migration is one-shot and mechanical, not exploratory.
- **SC-010**: After Phase 6, `pipx list` on a fresh machine shows `spaex 4.0.0`, and running `spaex add`, `spaex remove`, `spaex install`, `spaex migrate`, `spaex constitution show` all work on a scratch project.

## Assumptions

- **PyPI Trusted Publisher already registered**: The maintainer confirmed on 2026-09-07 that the PyPI project `spaex` is configured with a pending trusted publisher pointing at `haexmas/spaex`, workflow `release.yml`, environment `pypi`.
- **GitHub repo can be renamed by the maintainer**: `haexmas/haex-hive` → `haexmas/spaex`. GitHub auto-configures a redirect from the old URL.
- **Pre-user status is factual**: No third-party users are running haex-hive today, per `~/.claude/projects/-home-haex-Projekte-haex-hive/memory/haex_hive_pre_user.md`. Migration is defensive but not user-facing-critical.
- **Existing `spec-007-ci.yml`**: Continues to run tests on pull requests. Paths inside its job steps that reference the source tree get the mechanical `haex_hive` → `spaex` rewrite. No structural workflow changes needed there.
- **Python 3.10+ is the minimum**: Unchanged from current `pyproject.toml`. `pipx` handles version-mismatch reporting itself.
- **`jsonschema` remains the sole runtime dependency**: The rename does not add or remove dependencies.
- **Domain vocabulary is stable**: `atoms{}`, `molecules[]`, `compounds[]` names survive Spec 013 and are not up for rename in this feature.
- **Constitution principle text is not being reworded**: This feature is a naming amendment to the constitution, not a principle amendment. If a principle rewording surfaces during Phase 4 review, it becomes a separate follow-up under a new ADR.
- **Environments and orchestration are out of scope**: Spec 014 makes no commitment to any category name for environment-config files, no multi-environment vocabulary (dev/staging/prod), no consumer-side environment selection, and no orchestration verbs (`spaex enter`, `spaex shell`, `spaex dev up`, etc.). All of that is Spec 015 (multi-environment declaration + orchestration). A placeholder design doc for 015 is written at Spec 014 session close.
- **PR sequence keeps `main` coherent**: Per Clarification 2026-09-07 Q1, the atomic rename (Phase 2 + Phase 4) lands in one PR, with Phase 3 (migrate) as a predecessor PR. `main` is never in a state where the repo's own manifests cannot be read by the current loader.
