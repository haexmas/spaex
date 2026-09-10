# Behavior Harness & Plugin-Alignment (Design)

**Status**: Design record. Captured 2026-09-10 during a brainstorming session that asked whether spaex is reinventing Claude Code Plugins, and how the constitution layer should evolve. This document fixes direction and decisions, not contracts. Contracts are settled in a follow-up Speckit spec written through `/speckit-specify` per [ADR 0009](../adr/0009-declared-speckit-workflow-adherence.md).

**Author**: brainstorming session 2026-09-10 with operator.

**Target spaex version**: 5.x line. The behavior-harness decisions here refine the ontology already sketched in the 2026-09-08 roadmap; they do not add a new MAJOR beyond that roadmap.

**Related**:
- [Spec 023 Behavior Harness](../../specs/023-behavior-harness/spec.md) and its plan, research, data-model, contracts, quickstart, tasks (11 phases, 69 tasks): the normative spec that this design record fed into.
- [Composition UI & Skills Externalization Roadmap (2026-09-08)](2026-09-08-composition-ui-and-skills-externalization-roadmap.md): fixes the overall phasing (A: skills externalize; B: ontology cleanup + presets; C: `spaex status`; D: GUI; E: Creator flow). This design and spec 023 shift the phasing so behavior-harness lands as an additive 4.2.0 BEFORE the roadmap's Phase A (5.0.0).
- [Spec 016 Molecule Install Hooks (2026-09-08)](2026-09-08-spec-016-molecule-install-hooks-design.md): the install-hook contract carries per-atom side effects at install time. The Composer flow below reuses it.
- [Spec 017 Molecule Store (2026-09-08)](2026-09-08-spec-017-molecule-store-design.md): the materialization pipeline that produces atom content on the consumer's disk. Fragment materialization plugs into that pipeline.
- [Scope Realignment (2026-09-03)](2026-09-03-scope-realignment-design.md): the constraint that spaex stays a meta-composition layer, not a runtime.
- Memory `spaex_constitution_terminology`: one constitution per adopted molecule-set. This design changes how that single constitution is assembled, not how many exist per project.
- Memory `spaex_pre_user`: no external users yet; breaking changes remain fine; PR-70 operator-input validation lesson still applies.

---

## 0. Normative status

Design record. As of 2026-09-10, every requirement here has moved into the numbered spec at `specs/023-behavior-harness/` (spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md, tasks.md), all authored through the speckit workflow and committed on branch `023-behavior-harness`. Wording like "MUST" in this document remains design intent; the binding contracts live in the spec's Functional Requirements. When this document and the spec diverge, the spec wins.

## 1. Problem

The 2026-09-10 session opened with the operator's question: "Are we reinventing Claude Code Plugins? Should spaex become plugins?"

Concrete grounding:
- Claude Code Plugins in 2026 ship skills, hooks, commands, agents, MCP configs, LSP configs, monitors, bin/, and limited settings defaults; they compose via semver dependencies and distribute through marketplaces. They do NOT ship a declarative agent-behavior layer, and they do NOT emit anything readable by non-Claude agents.
- The operator's premise for spaex is truly multi-agent portability: any coding agent (Claude Code, Codex, Gemini CLI, potentially dsh) must respect the same harness. Plugins as a substrate would fork away from this premise.

At the same time, two things about the current spaex model felt unresolved:
- The constitution layer today assumes one constitution per adopted molecule-set, materialized by exactly one atom. That constrains what a molecule can contribute behaviorally.
- The atom ontology has grown organically. There is no single spec that pins which categories exist, what a "behavior atom" would look like, or how project-level customization interacts with atom-authored rules.

## 2. Landscape findings

Compact summary of the 2026-09-10 landscape scan. Full sources in section 10.

- **Bridle** (`neiii/bridle`): Rust TUI/CLI that translates one profile (skills, agents, commands, MCPs) into the native configs of Amp, Claude Code, OpenCode, Goose, Copilot CLI, Crush, Droid. Active. Closest neighbor to spaex on the multi-harness emission axis. Does NOT have behavior atoms, conflict algebra, molecule/preset composition, or Speckit-enforcement.
- **Compound Engineering Plugin** (`EveryInc/compound-engineering-plugin`): standardized skill bundle published as native plugin across 14 agent hosts. Proves the alternative emission pattern (publish per host as a native plugin, not runtime translation).
- **Archon** (`coleam00/Archon`): YAML-pipeline workflow harness. Adjacent to speckit-enforcement in spirit (procedural workflow determinism), not in shape.
- **ECC** (`affaan-m/ECC`): extracts skills and rule files from local git history. Bottom-up rule extraction, opposite direction from spaex's top-down composition.
- **Deep Agents** (`langchain-ai/deepagents`), **DeerFlow 2.0** (`bytedance/deer-flow`): LangGraph-based runtimes, not composers. Off-topic.

Verdict: the declarative multi-agent Behavior-Composition layer (atom-provided modal rules, composed to a coherent constitution across many harnesses) is unoccupied in the scanned OSS field.

## 3. Non-goals

- **spaex does not become a runtime.** The scope realignment holds; the harness we compose runs inside whatever agent the consumer chooses.
- **spaex does not become a plugin registry.** Plugins remain one emission target for the Claude Code stack; they are not the substrate.
- **spaex does not compete with skills.sh or agentskills.io.** Skills continue to externalize per the 2026-09-08 roadmap (Phase A).
- **The constitution is not authored in the GUI.** The composer produces a committed artifact from atom-provided fragments; the artifact is browsed in the GUI (Phase D), not edited WYSIWYG.
- **No LLM composition at every install.** The composer runs at explicit build time and its output is committed to the repo, so downstream `spaex install` runs are deterministic.

## 4. Decisions

Decisions are numbered so downstream specs can cite them (`Design 2026-09-10 §4.N`).

### Decision 1: Framing is "portable, plugin-shaped bundle system with modal constitution"

The mental model of spaex is:
- Bundles that mirror Claude-Plugin-style ontology (`atoms.skills`, `atoms.hooks`, `atoms.commands`, `atoms.agents`, `atoms.mcp`), so anyone familiar with Claude Plugins reads a molecule immediately.
- A spaex-native Behavior layer (`atoms.behavior`) on top, because no existing plugin format supports declarative modal rules.
- Agent-neutral emission (AGENTS.md, CLAUDE.md, mcp.json, and per-harness variants) as the default output surface. A Claude-Plugin emitter is an optional convenience, not the mandatory pathway.

**Why:** the plugin-shape is a proven form for grouping the heterogeneous atoms a coding-agent bundle carries. Adopting the shape without adopting the format keeps multi-agent portability intact.

### Decision 2: Behavior atoms are an atom type of their own; typed atoms may also carry behavior blocks

- `atoms.behavior` is a first-class atom type. Its content is a constitution fragment with a small metadata header and prose body.
- Typed atoms (`atoms.speckit_workflow`, `atoms.mcp`, others where it applies) MAY carry a `constitution_fragments:` block in their manifest that produces the same kind of fragments. A skill-invoked-only directive does not need a behavior atom; a session-wide directive does.
- Hook atoms and command atoms typically DO NOT carry behavior fragments; they enforce or expose functionality rather than declare it.

**Why:** the operator explicitly wanted "many small atoms, freely composable, project-level override on top", dsh-style. A dedicated type gives that granularity. Allowing typed atoms to also carry fragments avoids splitting a semantically-coupled unit (a speckit-workflow atom that says "MUST follow spec-first" should not have to ship a separate paired behavior atom).

### Decision 3: Constitution fragments are the raw material; the constitution.md is a build artifact

- Each atom contributes zero or more constitution fragments as separate Markdown files with a small YAML header (Format C, section 5).
- `spaex install` materializes fragments to `.spaex/constitution.d/` and runs a mechanical pre-check for hard conflicts (same fragment id, incompatible modality) that aborts the install with both provenances shown.
- `spaex constitution build` (auto-invoked at install time when fragments have changed since the last build) runs an LLM-based Composer that reads all fragments and synthesizes `.spaex/constitution.md`.
- `.spaex/constitution.md` is committed to the consumer's repo. Downstream installs on other machines reuse the committed artifact; the Composer only re-runs when fragments actually change.
- The composed constitution is referenced or inlined by the emitters into `CLAUDE.md`, `AGENTS.md`, and other harness-native instruction files.

**Why:** determinism is load-bearing for a harness (two installs from the same lock must produce the same constitution). Committing the artifact separates "LLM-clever composition" from "reproducible install". Speckit itself follows this pattern: spec.md is authored, plan.md is generated, both are committed.

### Decision 4: Composer is Hybrid (mechanical pre-check + LLM synthesis)

- The mechanical pre-check runs first and cheaply. It reads the YAML headers of every fragment, detects id collisions with incompatible modality declarations, and aborts on hard conflicts with a diagnostic that names both source atoms and both molecules.
- The LLM Composer runs second, only if the pre-check passes and fragments have changed. It reads all fragment bodies, groups semantically overlapping rules, and produces a single coherent constitution.md.
- The Composer follows the `/speckit-analyze` and `/speckit-clarify` patterns: when it detects genuine ambiguity that cannot be resolved from the fragments alone, it asks the operator one round of targeted questions and records the answers in `.spaex.json` under `constitution.clarifications` so subsequent builds do not re-ask.
- The Composer's system prompt lives canonically inside spaex. Consumers MAY override it per project via `.spaex/composer-prompt.md`, but the default carries the semantics defined in this design.

**Why:** pure LLM synthesis loses reproducibility; pure algebra loses semantic overlap handling and prose quality. The hybrid pays a small cost at build time (one LLM round) for both properties.

### Decision 5: Conflict algebra is Strict

- Two fragments declaring `MUST X` and `MUST NOT X` with the same conceptual referent produce a hard conflict. `spaex install` aborts, prints both provenances, and requires the operator to resolve (disable one fragment, or add a project-level clarification that names which wins).
- `SHOULD` vs `SHOULD NOT` produces a soft conflict. Both clauses remain in the fragment set; the Composer surfaces the tension in the built constitution or asks a clarification.
- `MAY` and its negation never conflict; both remain as permissive text.
- Modality inference from prose (used when a fragment does not declare a modality in its metadata) is best-effort by the Composer and does not participate in the mechanical pre-check.

**Why:** an operator who accepts two contradictory MUSTs on the same topic is a bug, not a feature. Strict wins because the alternative regimes (priority, layered, explicit-resolution) all move authority away from the atoms, which contradicts the design premise that atoms are authoritative.

### Decision 6: Project overrides are additive only

- The `.spaex.json` composition file MAY declare project-local constitution fragments alongside molecule pins.
- Project-local fragments run through the same mechanical pre-check and the same Composer flow as atom-provided fragments.
- The project MAY NOT modify, disable, downgrade, or shadow an atom-provided fragment. If an atom's rule is unfit for the project, the correct move is to swap the atom (remove the molecule that ships it) or add a compensating project-local fragment that the operator accepts as a soft conflict.

**Why:** atoms are contracts. A molecule author who declares `MUST X` for their atom should be able to trust that consumers do not silently rewrite `MUST` to `SHOULD` in installed harnesses. The purest model is that project-level and atom-level fragments are peers, running through identical rules.

### Decision 7: Language stays Python; Bridle is a reference, not a dependency

- spaex remains a Python project. The existing infrastructure (install.lock from Spec 017, install-hook machinery from Spec 016, litellm-based context-budget checks, molecule schema) carries forward.
- Bridle's per-harness config knowledge (paths, schemas, naming quirks) is documented in `docs/emitters/*.md` as a reference note, not adopted as a runtime dependency. Bridle is Rust; embedding it in a Python-native toolchain adds distribution complexity that a pre-user project cannot justify.
- Emitters are small Python modules (`spaex/emit/claude_code.py`, `spaex/emit/codex.py`, `spaex/emit/gemini.py`, potentially `spaex/emit/dsh.py`). Each is expected to be a few hundred LOC.
- The Compound-Engineering-style "publish as native plugin per host" pattern is a Phase-E follow-up, not the primary emission model.

**Why:** rewriting an existing Python codebase for a pre-user tool is almost always a mistake. The workload (I/O, YAML/Markdown parsing, LLM coordination) does not benefit from Rust. Language re-evaluation is reversible later, once the ontology stabilizes and if a real distribution pressure appears.

## 5. Fragment format

Per Decision 3, atoms contribute Markdown files with a small YAML header. Format C, illustrated:

```markdown
---
id: tests-before-commit
kind: constitution_fragment
atom_source: hooks.test-runner       # or the id of a standalone behavior atom
modality: MUST                        # optional metadata; body is authoritative
tags: [testing, git]
---
**MUST** run the project's test suite before creating any commit. If tests
fail, address the failures before writing the commit. This is enforced at
runtime by the pre-commit hook shipped by `atoms.hooks.test-runner`.

**Rationale:** mocked test runs have historically masked broken migrations
(see incident log entry Q1-2026).
```

Rules of the format:
- `id` is unique across the composed fragment set. Two atoms declaring the same `id` with incompatible `modality` produce a hard conflict at the mechanical pre-check.
- `kind` is always `constitution_fragment`.
- `atom_source` names the atom that produced the fragment. For standalone behavior atoms this is the atom's own id; for typed atoms with `constitution_fragments:` blocks this is the atom that carries the block.
- `modality` is optional metadata that the pre-check uses. The body remains authoritative; if body and header disagree, the pre-check emits a warning and the body wins.
- `tags` are free-form; the Composer MAY use them to group related fragments.
- The body is Markdown with RFC-2119 keywords used as convention. A `**Rationale:**` section is optional but recommended; it helps the Composer decide whether two similar clauses should merge or coexist.

## 6. Composer flow

```
+-----------------------------+
| spaex install               |
+--------------+--------------+
               |
               v
+-----------------------------+
| Materialize fragments to    |
| .spaex/constitution.d/      |
+--------------+--------------+
               |
               v
+-----------------------------+
| Mechanical pre-check:       |
|  - id-collision detection   |
|  - modality-conflict detect |
|  - fragment schema validation|
+--------------+--------------+
               |
       pass    |    fail
      +--------+--------+
      |                 |
      v                 v
+------------+   +-------------+
| Composer   |   | Abort with  |
| needs to   |   | both        |
| run?       |   | provenances |
+-----+------+   +-------------+
      |
   yes|no
      +---+---+
      |       |
      v       v
+----------+  reuse committed
| LLM      |  .spaex/constitution.md
| Composer |
+----+-----+
     |
     v
+-----------------------------+
| Clarifications needed?      |
+--------------+--------------+
      |
   yes|no
      +---+---+
      |       |
      v       v
+----------+  emit constitution.md
| Ask op   |
| once,    |
| record   |
| in .json |
+----------+
      |
      v
   emit constitution.md
```

The Composer's decision to run is a content hash over all fragment bodies plus the `constitution.clarifications` block plus the Composer system prompt version. Any change re-runs.

## 7. Emitter matrix

Composed output landing per harness:

| Harness       | Primary artifact              | Constitution placement                             | Skills                        | Hooks             | MCP                            |
|---------------|-------------------------------|----------------------------------------------------|-------------------------------|-------------------|--------------------------------|
| Agent-neutral | `AGENTS.md`                   | Inline at top under `## Behavior harness`          | via `agentskills.io` install  | shell scripts     | `mcp.json` at repo root        |
| Claude Code   | `CLAUDE.md` + `.claude/`      | Inline at top of `CLAUDE.md`                       | via `agentskills.io` install  | `.claude/hooks/`  | `.mcp.json` merged             |
| Codex CLI     | `AGENTS.md` + Codex config    | Inline at top of `AGENTS.md`                       | via `agentskills.io` install  | shell scripts     | Codex MCP config               |
| Gemini CLI    | Gemini config + `AGENTS.md`   | Inline at top of `AGENTS.md`                       | via `agentskills.io` install  | shell scripts     | Gemini MCP config              |
| dsh           | dsh Cordis-patch bundle       | Emitted as Cordis behavior row (Phase E follow-up) | Cordis plugin adapter         | Cordis event rows | Cordis MCP plugin adapter      |

Skills are external per the 2026-09-08 roadmap Phase A; the emitters call out to `npx skillsadd <owner/repo>` or the equivalent as an install-hook side effect.

Claude Code has an optional secondary emission path: a plugin bundle under `.claude/plugins/spaex-generated/` that carries commands, hooks, agents, and MCP config in Claude-Plugin format. This is a convenience for Claude-native discovery, NOT the constitution transport (Claude Plugins cannot carry behavior directives; see the plugin overview in section 2).

## 8. Impact on the 2026-09-08 roadmap

- **Phase A (Skills externalization, spec 018)**: unchanged. Skills continue to leave spaex/atoms and route through skills.sh / agentskills.io.
- **Phase B (Ontology cleanup + presets, spec 019)**: grows to include the behavior-fragment machinery from this design. Concretely, Phase B now covers:
  - The `atoms.behavior` atom type.
  - The `constitution_fragments:` block on typed atoms.
  - The fragment format (section 5).
  - The mechanical pre-check and its diagnostics.
  - The Composer system prompt (canonical version, override slot).
  - The `constitution.clarifications` block in `.spaex.json`.
  - Named presets remain part of this phase.
- **Phase C (spaex status + provenance, spec 020)**: extended so `spaex status` shows the composed constitution's provenance: which fragment came from which atom, which molecule pulled the atom in, which preset activated the molecule. `spaex constitution trace <clause>` becomes a first-class command.
- **Phase D (GUI MVP, spec 021)**: Constitution sidebar section (Decision 9 of the 2026-09-08 roadmap) renders the composed constitution with per-clause provenance overlays that use the Phase C data.
- **Phase E (Creator flow, spec 022)**: unchanged in scope, but gains a natural companion: an agent-drafted constitution-fragment authoring flow, invoked when the operator wants a project-local fragment.

## 9. Open points settled downstream

Deferred to the follow-up spec that formalizes this design (proposed slot 023):

- Exact CLI shape: `spaex constitution build` vs. auto-invoke inside `spaex install`, flags for force-rebuild, dry-run, and clarification-only.
- Contextual-scope semantics for behavior fragments (`scope: contextual`, `when: "..."`): how the `when` predicate is evaluated (pattern match on session context, another atom's presence, Composer-decides), and how the emitter surfaces contextual clauses versus always-active ones.
- Composer system-prompt version pinning: how the Composer's own prompt is versioned, and how a version bump interacts with `constitution.clarifications` (invalidate all, or attempt to migrate).
- Exact Emitter modules for Codex CLI and Gemini CLI: config-file paths, schema versions, how AGENTS.md merges with any existing operator-authored content in the target repo.
- Interaction with Spec 016 install-hooks: whether the mechanical pre-check runs as an install-hook or as a native `spaex install` phase.
- Interaction with Spec 017 molecule-store: whether fragments materialize via `molecule_store.get_or_extract` or via `git_show.show_bytes`, per memory `spaex_git_content_access_architecture`.

## 10. References

- [Composition UI & Skills Externalization Roadmap (2026-09-08)](2026-09-08-composition-ui-and-skills-externalization-roadmap.md)
- [Spec 016 Molecule Install Hooks (2026-09-08)](2026-09-08-spec-016-molecule-install-hooks-design.md)
- [Spec 017 Molecule Store (2026-09-08)](2026-09-08-spec-017-molecule-store-design.md)
- [Scope Realignment (2026-09-03)](2026-09-03-scope-realignment-design.md)
- Bridle: https://github.com/neiii/bridle
- Compound Engineering Plugin: https://github.com/EveryInc/compound-engineering-plugin
- Archon: https://github.com/coleam00/archon
- ECC: https://github.com/affaan-m/ecc
- Deep Agents: https://github.com/langchain-ai/deepagents
- DeerFlow: https://github.com/bytedance/deer-flow
- RFC 2119 keywords: https://www.rfc-editor.org/rfc/rfc2119
- RFC 8174 (updated keyword semantics): https://www.rfc-editor.org/rfc/rfc8174
