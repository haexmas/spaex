# Phase 0 Research: Composition Status and Provenance Query

## R1: Where does "what did spaex do with this molecule's atoms" come from?

**Decision**: Derive the per-molecule atom grouping (FR-005) entirely from artifacts already committed to the repository — never from a molecule's own manifest or the local molecule cache:

1. **Behavior fragments**: enumerate `.spaex/constitution.d/<molecule-id>/*.md` (excluding the `_project` scope), parsed with the existing `BehaviorFragment.from_file`.
2. **Composed generated artifact contributions**: from `InstallLock.molecules[].paths`, any path that appears in more than one molecule's `paths` list, **excluding** `COMPOSED_CONSTITUTION_RELATIVE_PATH` (`.spaex/constitution.md`), which is bucket 1's territory and already summarized separately (FR-006). Today the only such path is `.spaex/generated/nix-packages.json` (Spec 027), but the rule is generic over any future composable category, since it keys off "more than one owner in the lock," not a category name.
3. **Plain files**: the remaining `InstallLock.molecules[].paths` entries (single owner, not the composed constitution) — already required by FR-004, reused here as the third bucket.

**Rationale**: resolved during 2026-09-22 clarification (see spec.md Clarifications). A molecule manifest's category name is a validated install-time dispatch key (`spaex.model.atom_category.is_exclusive`), not trustworthy metadata to echo back, and reading it requires the molecule's manifest, which needs the local molecule cache (network-capable) and is not guaranteed present in a fresh clone. Grouping by observed effect instead needs only data already on disk and git-tracked (`.spaex/constitution.d/` is explicitly carved out of `.gitignore` as versioned content, so this holds for every spaex consumer, not just this dogfooding repo).

**Alternatives considered**:
- Read each molecule's manifest from the local cache (spec's original framing, before clarification): rejected — fails in a fresh clone, and the category name it would surface is not a reliable description of behavior (R1 above).
- Have `spaex install` additionally persist atom-category names into `install.lock`: rejected — changes the install pipeline and lock schema, which the feature request explicitly excludes.

## R2: Where does "which molecule wrote this file" come from?

**Decision**: Build one `path -> tuple[molecule_id, ...]` map by iterating every `MoleculeEntry.paths` in `InstallLock.molecules` (repo.git already has this shape: multiple molecules can list the same path, as `.spaex/constitution.md` already does today for every behavior-contributing molecule, and `.spaex/generated/nix-packages.json` does for Spec 027's composable category). `spaex trace <path>` looks up the normalized repo-relative path in this map. A directory query filters the map by path prefix.

**Rationale**: this is the same install-lock reuse as R1, needs no new lock field, and treats the constitution's already-multi-owner shape as the general case rather than a special one. FR-009's pointer to `spaex constitution trace` for `.spaex/constitution.md` is a presentation rule (a hint line/field), not a different lookup mechanism.

**Alternatives considered**: recording the same information in a new dedicated index file — rejected; the install lock is already the single source of truth for "which molecule owns which path" (Spec 008/027), and a second index would need its own reproducibility and rollback guarantees for no benefit.

**Addendum, found during task breakdown**: R1's "composed artifact vs. plain file" split and R2's own lookup both start from the identical `path -> [molecule_id, ...]` map. Build it once as a public `path_owners(lock: InstallLock) -> dict[str, tuple[str, ...]]` in `spaex/model/install_lock.py` (natural home, alongside `InstallLock`/`MoleculeEntry`), and have both `report/compose.py` (R1) and `report/trace.py` (R2) call it — this makes it a genuinely foundational function serving both User Story 1 and User Story 2, not a per-story implementation detail.

## R3: How to detect drift between the manifest and the install lock (FR-007, first half)

**Decision**: Load `ConsumerManifest` (`.spaex/manifest.json`) and `InstallLock` (`.spaex/install.lock`) independently — both cheap, local, schema-validated reads that the codebase already performs elsewhere (`_load_consumer_manifest`, `InstallLock.from_json`). Expand the manifest's `compounds[].molecules[]` into a flat `molecule_id -> (source, revision)` map exactly as `behavior_commands._load_molecule_pins` already does for `constitution trace`, and compare it against the lock's flat `molecule_id -> (source, revision)` map:

- id in manifest map, absent from lock map → **pinned but not installed**.
- id in lock map, absent from manifest map → **installed but no longer pinned**.
- id in both, `revision` differs → **revision mismatch** (both values reported).

**Rationale**: purely a comparison of two already-local, already-parsed structures; no molecule resolution, no network, no cache access. Reuses the existing pin-flattening logic instead of re-deriving it.

**Alternatives considered**: also diffing `source` independently of `revision` — rejected as a separate finding; a source change without a revision pin update is not a state spaex's manifest schema treats specially, and folding it into "revision mismatch" (which already reports both full pin tuples) is sufficient to show the operator what differs.

## R4: How to detect a stale composed constitution (FR-007, second half) — without network or cache access

**Decision**: Do **not** reuse `run_constitution_build`'s `--check` path (`_check_build`) as-is. That path calls `resolve_install_inputs()` → `resolve_constitution_contributions`/molecule resolution, which goes through `spaex.git.molecule_store`/`clone_dir` and can fetch and materialize a molecule that is not yet cached — a real network/cache side effect, which FR-002 forbids for `spaex status`.

Instead, recompute both header fingerprints **only from already-materialized, git-tracked local files**, reusing the existing pure functions with locally-sourced input:

1. Enumerate `.spaex/constitution.d/<molecule-id>/*.md` (all molecule scopes, including `_project`), parse each with `BehaviorFragment.from_file` — the same files `_lookup_atom_source` already reads back for `constitution trace`.
2. `source_hash = compute_source_hash(fragments)` (`spaex.behavior.emit`, already pure/local).
3. `prompt_hash = effective_prompt_sha256(load_effective_prompt(repo_root))` (`spaex.behavior.composer.prompt`; reads `.spaex/composer-prompt.md` if present, else the canonical constant — no network).
4. Load `.spaex/clarifications.json` (`spaex.behavior.composer.clarifications.load`), invalidate against the current fragment hashes, and compute `build_input_hash = compute_build_input_hash(...)` (`spaex.behavior.orchestrate`) — same as `compute_fingerprints` does, just without the resolve/materialize step that needs cache access.
5. Compare against `read_header_hashes(repo_root)` (`spaex.behavior.emit`).

If there are no fragments and no `.spaex/constitution.md`, there is no composed constitution (not "stale" — the edge case "No behavior molecules"). If fragments exist but the header hashes do not match (or the file is absent), the constitution is stale.

**Rationale**: gives the exact same fingerprint values `constitution build --check` would compute in the common case (the last successful install left `.spaex/constitution.d/` and the composed constitution consistent with what was resolved), while depending only on inputs that are already local and git-tracked. It detects a hand-edited or corrupted `.spaex/constitution.d/` tree and a partial/interrupted install, in addition to a manifest that changed since the last install (via R3's separate, already-reported drift findings pointing at the same underlying cause). It does **not** detect "a pinned molecule's upstream content changed at the same pinned revision" — not possible in general, since revisions are full-SHA pins (immutable per the `cross-repo-refs-pin-immutable-revisions` constitution rule), so this is not a real gap.

**Alternatives considered**:
- Reuse `_check_build` outright and accept the network/cache dependency: rejected — violates FR-002 (`spaex status` MUST NOT access the network or the local molecule cache).
- Skip constitution staleness entirely: rejected — spec.md's User Story 4 Acceptance Scenario 4 requires it, and R3's manifest/lock drift alone cannot detect an interrupted install that left the constitution artifacts inconsistent with each other.

This requires a small correction to spec.md's Assumptions section, whose current wording ("reuses the offline fingerprint comparison that Spec 023 already defines for `spaex constitution build --check`") could be read as reusing `_check_build` wholesale, including its resolve step. The assumption is corrected in this plan's spec.md update to name the actual local-only recomputation.

## R5: Composed-clause parsing reuse for the constitution summary (FR-006)

**Decision**: Extract `constitution trace`'s existing composed-clause parser (`_TracedClause`, `_parse_clauses`, `_SECTION_HEADER_RE`, `_CLAUSE_RE`, `_PROVENANCE_ID_RE` in `spaex/cli/behavior_commands.py`) into a small shared module, `spaex/behavior/clauses.py`, with a public `parse_clauses(body: str) -> list[TracedClause]`. `behavior_commands.py` imports it instead of defining it locally; `spaex status`'s constitution summary (clause counts per modality, contributing molecule ids derived from each clause's provenance) imports the same function.

**Rationale**: per the graphify-first-authoring rule, this is exactly the "third similar parser" red flag to avoid — a second, independent regex-based parser for the same composed-clause grammar would drift from the first. Reuse is behavior-preserving (pure move, same regexes, same dataclass shape); `constitution trace`'s existing tests keep passing unchanged (SC-007).

**Alternatives considered**: reimplementing a second, narrower parser in the new module that only counts clauses per modality without extracting provenance — rejected as unnecessary duplication of `_parse_clauses`, which already does this and more.

**Addendum, found during task breakdown**: the same file also defines `_load_molecule_pins`, a private helper that flattens `ConsumerManifest.compounds[].molecules[]` into a `molecule_id -> (source, revision)` map — exactly `MoleculeRecord.pinned`'s source (data-model.md) and a direct input to the revision-mismatch drift check (R3). Promote it alongside the clause parser: a public `flatten_compound_pins(manifest: ConsumerManifest) -> dict[str, tuple[str, str]]` in `spaex/model/consumer_manifest.py` (natural home — pure manifest-shape flattening, no behavior-domain logic), imported by both `behavior_commands.py` (existing caller, unchanged behavior) and `report/compose.py` (new caller). Same rationale as the clause-parser extraction: avoids a second, independently-drifting implementation of "flatten compound pins."



## R6: Command surface and dispatch

**Decision**: Add two new top-level subcommands, sibling to `constitution`/`install`/`add`/`remove` in `spaex/cli/main.py`'s `_build_parser()`: `spaex status` (no positional argument) and `spaex trace <path>`. Both take `--format text|json` (default `text`), matching `spaex constitution trace`'s existing option shape, and both honor the existing top-level `--repo-root`. Implementation lives in a new module, `spaex/cli/status.py` (`run_status`, `run_trace`), backed by a new read-only domain package `spaex/report/` (`compose.py` for the composition report, `trace.py` for the file-attribution lookup, `staleness.py` for R4's offline fingerprint recomputation), mirroring the existing `spaex/constitution/`, `spaex/behavior/`, `spaex/install/` domain-package split.

**Rationale**: `spaex trace <path>` (file-level) and `spaex constitution trace <query>` (clause-level) are deliberately separate commands per spec.md's Assumptions ("Two trace commands, two granularities"), so `trace` is not nested under `constitution`. A new `report/` package keeps this read-only, cross-cutting logic (spans manifest, lock, constitution, generated artifacts) out of the single-purpose `constitution/`, `behavior/`, and `install/` packages, none of which own "summarize everything" today (evaluated and rejected as extension points below).

**Candidates evaluated and rejected** (graphify-first-authoring):
- `spaex/constitution/show.py`: renders the constitution body only; no molecule/drift summary, wrong responsibility.
- `spaex/behavior/bootstrap.py`'s `install()`: the install orchestrator — writes, not a read-only report.
- `spaex/install/delta.py`: computes the orphan-path deletion delta during a real install (write-path cleanup), not a read-only manifest-vs-lock comparison; same word "delta," different purpose.

## R7: Exit codes

**Decision**: Reuse the existing shared registry (`spaex.util.exit_codes`) and, where one already exists, the existing typed error and loader function — rather than inventing feature-specific codes or re-deriving how a given failure is classified:

| Outcome | Code | Notes |
|---|---|---|
| Report/answer produced (including drift shown) | `SUCCESS` (0) | |
| `spaex trace`: no molecule recorded for the path | `1` (bare literal, matching `constitution trace`'s existing "no match" convention — not currently a named constant) | |
| Missing/invalid `.spaex/manifest.json` | `INCOMPLETE_TRANSACTION` (7) | Reuse `spaex.cli.install._load_consumer_manifest(repo_root)` directly — it already raises `HaexError(exit_code=exit_codes.INCOMPLETE_TRANSACTION, diagnostic_key="spaex-json-missing"\|"spaex-manifest-invalid")` for both cases, and is already reused across `install`/`add`/`remove`/`behavior_commands.py`. **Correction**: `exit_codes.py`'s own comment for `SYSTEM_REFUSE` (5) claims "missing `.spaex/manifest.json` or version mismatch," but the only code that actually raises `SYSTEM_REFUSE` today is `VersionBelowMinError` (the `spaex_min_version` gate) and `SpeckitCliMissingError`; no manifest-loading path uses it. The comment is stale against current usage — this plan follows the code, not the comment. |
| `.spaex/install.lock` present but fails schema validation | `VALIDATION_REFUSE` (4) | `InstallLock.from_json` already raises `InstallLockSchemaInvalidError(exit_code=exit_codes.VALIDATION_REFUSE)` on a malformed lock; propagate it unchanged. |
| `spaex trace`: path outside the repository | `USAGE` (64) | Matches its existing "usage error" bucket. |

A missing `install.lock` (manifest present, never installed) is **not** an error for either command and MUST NOT raise `InstallLockMissingError` (which `constitution show` uses for a different, write-adjacent context): treat it as an empty `InstallLock` (zero molecules). `spaex status` then reports every pinned molecule as `pinned_not_installed` (User Story 4 territory, not a failure), and `spaex trace` reports "no molecule recorded" (exit 1) for every path.

**Rationale**: keeps FR-014's three-outcome distinction (success / no match / operational error) consistent with every existing spaex command's exit-code surface instead of adding a parallel one, matching the exit_codes module's own stated goal ("a caller never has to disambiguate divergent values for the same numeric result"), and reuses the two typed errors that already exist for exactly these failures instead of re-deriving new ones.

## R9: Consistent snapshot during a concurrent install (FR-015)

**Decision**: `.spaex/` is published as one unit — `transaction.publish_generation` renames the whole `<root>.next/` into place, and `.spaex/manifest.json` is itself one of the `preserved_files` carried through that same swap (`cli/install.py`'s `preserved["manifest.json"]`), so a concurrent `spaex install` can complete its atomic rename between any two of `spaex status`'s/`spaex trace`'s several separate reads (manifest, lock, constitution fragments, constitution body) — reading them independently is not inherently torn-safe.

Bracket the read with `.spaex/install.lock`'s `generation_id` instead of building real snapshot-read machinery: read `install.lock` first (its `generation_id` and `molecules` drive every other read — which fragment directories to enumerate, which generated-artifact paths to expect), perform the rest of the read (manifest, constitution fragments, constitution body, staleness inputs), then re-read `install.lock` once more and compare `generation_id`. If they match, the read is consistent (a completed swap always installs a freshly allocated `generation_id`, `constitution/publish.py`'s `allocate_generation_id`). If they differ, retry the whole read once (bounded — a second swap completing inside the same narrow re-read window is not a case worth defending against per the ponytail principle of proportionate effort); if it still differs, surface this honestly as a report that could not observe a consistent snapshot rather than silently returning a torn one.

**Rationale**: needs no new transaction primitive and does not touch the install pipeline (FR-017), reuses data (`generation_id`) that already exists for exactly this purpose (distinguishing generations), and directly implements FR-015's "either the complete previous or the complete new generation" in the common case. A true dirfd-based snapshot read would be more airtight but is platform-specific (POSIX `openat`, no Windows equivalent) and disproportionate for a read-only reporting command with no correctness-critical consumer downstream (contrast Spec 009's rejected multi-tenant hardening machinery, reasoned about the same way in `docs/plans/2026-09-03-scope-realignment-design.md` Decision 11).

**Alternatives considered**:
- Ignore the race (read each file independently, no bracketing): rejected — a torn read (new manifest paired with an old lock, or vice versa) could report a molecule as installed with the wrong revision, or omit a molecule's atoms entirely, silently. FR-015 is explicit that this MUST NOT happen.
- Acquire the real install lock (`.spaex/manifest.json.lock`) for the duration of the read, the way a writer would: rejected — that would make a read-only reporting command block on, or be blocked by, a real install, and FR-002/the commands' whole premise is that they never contend with a running install.

## R8: JSON output shape and reproducibility (FR-012, FR-013)

**Decision**: Follow `constitution trace --format json`'s existing pattern exactly: build one plain-data record (dict of dicts/lists, no dataclass leakage) independent of format, then either `json.dumps(record, indent=2, sort_keys=True)` or a text renderer. Add a top-level `"format_version": 1` field to both commands' JSON output (not present in `constitution trace`'s output today — a gap this feature does not need to fix there, since FR-016 keeps that command unchanged). All paths are rendered repo-relative with `Path.as_posix()` (already the codebase convention, e.g. `_manifest_display_path`). No timestamps, host names, or absolute paths appear in either report, so byte-identical output follows from byte-identical repository content plus `sort_keys=True` and a fixed key ordering — no new determinism mechanism is needed beyond what `constitution trace` already relies on.

**Rationale**: consistency with the one existing structured-output command in this codebase; minimizes new surface for the future GUI (roadmap Phase D) to learn.
