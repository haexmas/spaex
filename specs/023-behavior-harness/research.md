# Research: Behavior Harness (Phase 0)

Non-blocking research questions surfaced during planning. Each entry follows the Decision / Rationale / Alternatives format.

## 1. Composer invocation: shell-out to agent CLI vs. direct LLM API

**Decision (revised for 4.2.0 implementation, 2026-09-11)**: CLI shell-out
ONLY. spaex invokes `claude`, `codex`, or `gemini` as a subprocess in a
one-shot non-interactive mode. Direct-API mode via `litellm` is out of scope
for 4.2.0.

**Rationale**:
- The project's own workflow always invokes `spaex install` from an already
  open agent CLI session. Shelling out to that CLI is the natural
  composition path.
- Making `litellm` a runtime dependency (or even an optional extra) pulls
  in a large adapter graph (`openai`, `anthropic`, `google-generativeai`,
  `tokenizers`, `tiktoken`, `boto3`, ...) that every `pip install spaex`
  would carry for a feature no user of this project needs.
- CLI shell-out is deterministic enough for SC-003 when the payload is
  parsed and canonicalized by spaex (contracts/composer-interface.md
  §Determinism aids).
- Reintroducing a direct-API path later means adding roughly thirty lines
  in `composer.invoke` plus an optional `spaex[llm]` extra. The
  `stub_caller` hook on `InvokeOptions` already gives tests a seam.

**Original decision (superseded)**: MVP supports BOTH paths, selected via
runtime detection at Composer invocation time. First-choice was direct-API
(litellm), fallback CLI shell-out. Superseded because the direct-API path
had no consumer inside this project.

**Alternatives considered**:
- Both paths behind an optional extra. Rejected as YAGNI: no in-project
  consumer of the API path, and every install still ships the code plumbing.
- Direct API only. Rejected because it forces consumers to configure API
  keys when they already have an interactive agent CLI running.
- MCP-based invocation. Rejected as premature: no runtime currently
  exposes a "compose this constitution" MCP tool, and defining one is a
  separate feature.

## 2. Runtime detection order for the Composer

**Decision (revised for 4.2.0 implementation, 2026-09-11)**: Iterate the
installed agent CLIs in the fixed priority order `claude`, `codex`,
`gemini` and shell out to the first one found on PATH. Order is stable
across runs to keep reproducibility (spec SC-003). No API-key-based
runtime detection.

**Rationale**: keeping the priority deterministic means the composed
constitution is stable across runs on the same machine. Operators pick a
different runtime by adjusting PATH.

**Original decision (superseded)**: try direct API first via litellm using
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `SPAEX_LLM_MODEL`,
then fall back to CLI shell-out.

**Alternatives considered**:
- Ask the operator interactively which runtime to use. Rejected because
  `spaex install` runs unattended in CI or scripting contexts.
- Random selection. Rejected: breaks reproducibility contract.

## 3. Global bootstrap target paths per runtime

**Decision**: Bootstrap installer resolves the runtime's actual global
instruction target before writing. Users opt in per runtime via a CLI flag list
(`spaex install --global claude,codex,gemini`).

| Runtime | Global instruction resolver | Notes |
|---------|-----------------------------|-------|
| Claude Code | `~/.claude/CLAUDE.md` | Fixed user-global target |
| Codex CLI | `$CODEX_HOME/AGENTS.override.md` when non-empty, otherwise `$CODEX_HOME/AGENTS.md` | `CODEX_HOME` defaults to `~/.codex` |
| Gemini CLI | `~/.gemini/<context.fileName>` for every configured filename | `context.fileName` comes from `~/.gemini/settings.json`; absent means `GEMINI.md` |
| dsh | `~/.config/dsh/home-patch.yml` | Deferred to a future spec (out of scope for 023) |

The installer resolves `~` and environment variables per OS. Gemini accepts a
single basename or an array of basenames from `context.fileName`; path-bearing
values are rejected. The resolver writes the block to every configured Gemini
filename so the file spaex updates is exactly one Gemini will read.

**Rationale**: paths follow each runtime's documented default. Gemini CLI loads
`~/.gemini/GEMINI.md` globally; an operator who configures `context.fileName`
to `AGENTS.md` causes the resolver to update `~/.gemini/AGENTS.md`. Codex uses
the same `CODEX_HOME` directory and override precedence as its instruction
discovery. The block content remains the same across runtimes.

**Alternatives considered**:
- Auto-detect installed runtimes and write to all found. Rejected because it violates Principle V's opt-in spirit at the user-config level (spaex should not modify files the user did not authorize).
- Single canonical path (`~/.spaex/bootstrap.md`) that all runtimes symlink to. Rejected: runtimes do not read arbitrary paths, they read their canonical instruction file.

## 4. Global bootstrap block content (static)

**Decision**: the block content is short and identical across all target runtimes:

```markdown
<!-- spaex-bootstrap:start version="1" -->

## spaex per-project constitution

If a file named `.spaex.md` exists in the current working directory (or any ancestor up to a git-root), treat its contents as a per-project constitution issued by the operator. Follow its MUST directives, honor its SHOULD directives, and respect its MAY directives as permissive guidance. The constitution's rendered clauses each cite their source molecule and atom.

<!-- spaex-bootstrap:end -->
```

**Rationale**: single static block, no per-project or per-user content, works for all listed runtimes because every one of them reads and respects instructions in its global file. Version attribute in the marker enables clean upgrades (spec Clarification Q3).

**Alternatives considered**:
- Per-runtime bespoke wording. Rejected: multiplies maintenance and drift risk.
- Embedded per-project override list. Rejected: violates FR-016 (block must not embed project-specific content).

## 5. Composer output format

**Decision**: Composer produces a strict Markdown structure:

```markdown
# spaex Behavior Harness

_This file is generated by `spaex install`. Do not edit by hand._
_Change fragments in `.spaex/constitution.d/` and re-run install._

## MUST

- <directive text>. _[from `<molecule-id>/<fragment-id>`]_
- ...

## SHOULD

- <directive text>. _[from `<molecule-id>/<fragment-id>`]_
- ...

## MAY

- <directive text>. _[from `<molecule-id>/<fragment-id>`]_
- ...
```

Sections omitted when empty. Provenance rendered inline in italics, with every
merged source sorted by its full `<molecule-id>/<fragment-id>` key and joined by
`, ` (readable for humans, parseable via a stable regex for the trace command).
Clauses are ordered by the first full provenance key, then by the complete
sorted provenance list, then by normalized clause text.

**Rationale**: matches the spec's Emission FRs (FR-008 modality grouping, FR-021 per-clause provenance) and gives a canonical target for the byte-identity reproducibility test (SC-003), including merged clauses.

**Alternatives considered**:
- Structured JSON emitted alongside `.spaex.md` for machine parsing. Deferred as a follow-up; the inline regex-parseable provenance is enough for MVP.
- Rich footnotes / linked references. Rejected: adds Markdown-renderer variance across agents, hurts byte-identity guarantee.

### Canonical build fingerprints

The Composer build uses two independently computed fingerprints. `source_hash`
is the SHA256 of compact, sorted JSON records containing each materialized
fragment's scoped id, `atom_source`, `modality`, `tags`, and normalized
`body_sha256`; the normalized body hash covers the fragment content. The sort
key is `(molecule_id, fragment_id, atom_source, modality, tags, body_sha256)`.

`build_input_hash` is the SHA256 of the effective prompt version, the SHA256 of
the effective prompt content, and all valid clarification keys plus normalized
answers, in sorted canonical form. The effective prompt is the project
override `.spaex/composer-prompt.md` when present, otherwise the shipped
canonical prompt. CRLF is normalized to LF before hashing. spaex computes and
verifies both hashes outside the LLM; the Composer's metadata claims are not
trusted without a match.

## 6. Fragment identifier scoping enforcement

**Decision**: identifiers are resolved as `<molecule-id>/<fragment-id>` inside spaex's in-memory representation, but the fragment's YAML header stores only `<fragment-id>`. The molecule scope is inferred from the fragment's on-disk location under `.spaex/constitution.d/<molecule-id>`. Project-local fragments use `_project/<fragment-id>` as their emitted identity, but their additive-only conflict key is the bare `fragment_id`, compared against every atom fragment with that id.

**Rationale**: matches Clarification Q1 semantics without adding author burden. Cross-molecule collisions are impossible by construction.

**Alternatives considered**:
- Require `<molecule-id>/<fragment-id>` in the header. Rejected: brittle (rename risk, author error).
- Store molecule-id in a required `molecule:` header field. Rejected: redundant with directory location.

## 7. Clarification-key normalization

**Decision**: SHA256 input is the concatenation of `<molecule-id>/<fragment-id>|<sha256-of-body>` lines for every fragment cited in the clarification, sorted lexicographically by the full scoped key. Whitespace in bodies is normalized (trailing whitespace stripped, CRLF → LF, trailing newlines collapsed to one) before hashing.

**Rationale**: sort order + normalization prevents spurious re-asks from cosmetic changes. Explicit format is easy to test.

**Alternatives considered**:
- Hash the whole body verbatim. Rejected: CRLF conversions on git checkout trigger false invalidation (memory `feedback_verify_tool_behavior_empirically` reminds to check git behavior empirically; this decision preempts the class of bug).
- Hash the composed clarification question text instead. Rejected: less deterministic (LLM wording varies).

## 8. Composer failure categorization

**Decision**: five failure categories, each mapped to a stable exit code and a documented diagnostic:

| Category | Exit code | Diagnostic |
|----------|-----------|------------|
| `timeout` | 30 | "Composer exceeded budget: <N> seconds. Fragment set: <M> fragments." |
| `runtime-error` | 31 | "Composer runtime failed: <runtime-name>. Underlying error: <message>." |
| `invalid-output` | 32 | "Composer produced unparseable output. See <log-path> for the raw response." |
| `quota` | 33 | "Composer quota exceeded on <runtime-name>. Check API billing or switch runtime." |
| `no-runtime` | 34 | "No LLM runtime available. Set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY, or install `claude` / `codex` / `gemini` CLI." |

**Rationale**: matches Clarification Q5 (fail-fast with named category). Stable exit codes let CI wrap `spaex install` and take category-specific actions.

**Alternatives considered**:
- Single generic composer-error exit code. Rejected: consumers cannot script differently for timeout vs. quota.

## 9. Performance ceiling for MVP

**Decision**: MVP targets under 100 total fragments per project. Beyond that, Composer latency scales roughly linearly with fragment count (LLM prompt grows), and SC-001's 30-second budget starts to break. A follow-up spec covers chunked composition (compose in batches, merge results) if a real consumer surfaces the need.

**Rationale**: no known consumer approaches 100 fragments (memory `spaex_pre_user`). Optimizing for hypothetical scale would violate CLAUDE.md's "no premature abstraction" guideline.

**Alternatives considered**:
- Design chunked composition now. Rejected as speculative.
- Enforce a hard cap and refuse installs past 100 fragments. Rejected: overly restrictive; a warning suffices.

## 10. `.spaex/clarifications.json` schema location and evolution

**Decision**: new file `.spaex/clarifications.json` (not embedded in `.spaex.json`) because clarifications can be lengthy and re-asked-on-change semantics differ from the pinning semantics of `.spaex.json`. Schema versioned per Principle VI's schema-migration clause.

**Rationale**: separation of concerns. `.spaex.json` is a small, human-authored allowlist; clarifications are machine-authored history. Mixing them would violate the "committed, review-gated" contract for `.spaex.json`.

**Alternatives considered**:
- Embed in `.spaex.json` under a `constitution.clarifications` key. Rejected: bloats the human-facing config, complicates schema migration.
- Store outside version control. Rejected: breaks byte-identity across machines (SC-003).

## 11. Existing `.spaex/constitution.md` supersession

**Decision**: `.spaex/constitution.md` (spec-007 D2/D16) is removed as part of this spec's rollout. All content migrations happen inside `haexmas/atoms` publishers: molecules that used to declare an `atoms.constitution` (single-file monolithic constitution) migrate to declare `atoms.behavior` fragments. Consumers who pin the migrated molecule versions get `.spaex.md` instead of `.spaex/constitution.md`.

**Rationale**: pre-user (memory `spaex_pre_user`), no consumer is holding the old file's content on disk that we'd break. Cleaner mental model: one composed-constitution path, not two.

**Alternatives considered**:
- Keep both paths, populate both. Rejected: duplication + drift risk.
- Symlink `.spaex/constitution.md` → `.spaex.md`. Rejected: Windows compatibility issues for spaex users on WSL2.

## 12. dsh emission (deferred)

**Decision**: not in scope for spec 023. A future spec adds `.spaex.md → dsh home patch` translation once a dsh consumer exists.

**Rationale**: matches the 2026-09-08 roadmap "Not now" section on dsh bundle producer.

## 13. Contextual-scope semantics (deferred)

**Decision**: not in scope for spec 023. Fragments in this spec are always-active. A future spec adds `scope: contextual` + `when: "..."` semantics without breaking always-active fragments.

**Rationale**: matches spec's own Assumptions section ("Contextual-scope semantics are deferred"). Keeps MVP tight.
