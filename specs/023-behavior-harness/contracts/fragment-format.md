# Contract: Fragment File Format

Format C from the design record (docs/plans/2026-09-10-behavior-harness-and-plugin-alignment-design.md §5). Applies to both standalone `atoms.behavior` fragment files and inline `constitution_fragments:` blocks in typed atoms.

## On-disk layout

Materialized fragments live at:

```text
<repo-root>/.spaex/constitution.d/<molecule-id>/<fragment-id>.md
```

- `<molecule-id>`: kebab-case molecule identifier (existing spaex convention).
- `<fragment-id>`: kebab-case, matches `[a-z0-9][a-z0-9-]*`, unique within `<molecule-id>`.
- Filename extension is `.md`.

Project-local fragments materialize under the synthetic scope `_project`:

```text
<repo-root>/.spaex/constitution.d/_project/<fragment-id>.md
```

## File structure

Every fragment file has two parts: a YAML front-matter header enclosed in `---` fences, and a Markdown body.

```markdown
---
id: tests-before-commit
kind: constitution_fragment
atom_source: hooks.test-runner
modality: MUST
tags: [testing, git]
---
**MUST** run the project's test suite before creating any commit. If tests fail,
address the failures before writing the commit. This is enforced at runtime by
the pre-commit hook shipped by `atoms.hooks.test-runner`.

**Rationale:** mocked test runs have historically masked broken setup paths.
```

## Header schema

Header is YAML. Fields:

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `id` | yes | string | Must match `[a-z0-9][a-z0-9-]*`; unique within molecule scope |
| `kind` | yes | literal `constitution_fragment` | Reserved for future header polymorphism |
| `atom_source` | yes | string | Dot-separated atom path within the molecule; used in provenance |
| `modality` | no | enum `MUST`\|`MUST_NOT`\|`SHOULD`\|`SHOULD_NOT`\|`MAY`\|`MAY_NOT` | Body wins if the body's leading directive contradicts; header used by mechanical pre-check |
| `tags` | no | list<string> | Composer MAY use for grouping; free-form otherwise |

Fields not listed above are rejected with a "malformed fragment" diagnostic (FR-007).

## Body conventions

- Markdown text.
- SHOULD open with an RFC-2119 keyword (`MUST`, `SHOULD`, `MAY`, or a negation) in bold: `**MUST** run …`. This is a strong convention that helps both human readers and the Composer.
- MAY include a `**Rationale:**` paragraph. The Composer uses rationale to decide whether two similarly-worded directives should merge.
- MUST NOT contain HTML comments starting with `spaex-` (reserved for spaex's own markers, prevents fragment content from imitating an emission-target marker).
- MUST NOT be empty.
- Encoding is UTF-8. Line endings normalized to LF at hash time (research.md §7).

## Inline behavior blocks in typed atoms

A typed atom (`atoms.speckit_workflow`, `atoms.mcp`, `atoms.hooks`, and others) MAY declare inline fragments in its own manifest. Example inside an atom's `manifest.json`:

```json
{
  "type": "speckit_workflow",
  "id": "speckit-strict",
  "constitution_fragments": [
    {
      "id": "spec-first",
      "modality": "MUST",
      "tags": ["speckit", "workflow"],
      "body": "**MUST** run /speckit-specify before any implementation work on a non-trivial feature."
    },
    {
      "id": "plan-before-code",
      "modality": "SHOULD",
      "body": "**SHOULD** run /speckit-plan before writing implementation code once a spec exists."
    }
  ]
}
```

At materialization time, each inline entry is written to `.spaex/constitution.d/<molecule-id>/<id>.md` with `atom_source` set to the enclosing atom's id (in the example, `speckit-strict`).

Field constraints are identical to standalone fragments.

## Validation errors (mechanical pre-check surface)

| Error | Trigger | Diagnostic template |
|-------|---------|--------------------|
| `missing-header` | File lacks `---` fences | `<path>: missing YAML header` |
| `malformed-header` | YAML parse fails | `<path>: header YAML parse error: <details>` |
| `missing-field:<name>` | Required field absent | `<path>: missing required field '<name>'` |
| `invalid-id` | `id` fails regex | `<path>: id '<value>' does not match [a-z0-9][a-z0-9-]*` |
| `invalid-kind` | `kind` != `constitution_fragment` | `<path>: kind must be 'constitution_fragment', got '<value>'` |
| `invalid-modality` | `modality` outside enum | `<path>: modality '<value>' not in MUST\|MUST_NOT\|SHOULD\|SHOULD_NOT\|MAY\|MAY_NOT` |
| `empty-body` | Body has no non-whitespace content | `<path>: body must not be empty` |
| `duplicate-id` | Two fragments same molecule same id, different modality | `<path> and <path>: duplicate id '<id>' with modalities '<m1>' vs '<m2>'` |
| `duplicate-id-same-modality` | Two fragments same molecule same id, matching modality and identical normalized body | Silent dedupe; second occurrence contributes only to provenance |
| `duplicate-id-body-mismatch` | Two fragments same molecule same id and modality, but different normalized bodies | Reject the conflict; do not discard either body or producer |
| `reserved-comment` | Body contains `<!-- spaex-...` comment | `<path>: body contains reserved 'spaex-' HTML comment` |

## Scope boundary

- `.spaex/constitution.d/` is the canonical materialized fragment tree.
- Existing `atoms.constitution` contributions are published to the same
  `.spaex/constitution.md` artifact; no alias or migration path is maintained.
