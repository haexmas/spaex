# Spec 011: Speckit Workflow Molecule (Design Preview)

**Status**: Opened as [`specs/011-speckit-workflow-atom/`](../../specs/011-speckit-workflow-atom/) but never implemented (that spec's own status: no code handles `atoms.workflow`). The gap it targeted, which Speckit workflow is binding, is answered today by the declared workflow at `.specify/workflows/speckit/workflow.yml` ([ADR 0009](../adr/0009-declared-speckit-workflow-adherence.md)), delivered through the `speckit` molecule, while [Spec 024](../../specs/024-speckit-integration-installer/) installs the Spec Kit integrations (ADRs 0019, 0020). Captured 2026-09-02 as the requirements source for the eventual `/speckit-specify` invocation that creates `specs/011-speckit-workflow-atom/`.

**Purpose**: define a mechanism for per-project speckit-workflow selection, so that the "which speckit workflow is binding" question is answered by an adopted, versioned molecule rather than by ad-hoc convention. This closes the gap identified during the 2026-09-02 amendment of the haex-hive constitution to 1.4.0 (see [ADR 0009](../adr/0009-declared-speckit-workflow-adherence.md)).

**Related**:
- [Constitution v1.4.0 §Development Workflow](../../.specify/memory/constitution.md): the "Declared speckit workflow adherence" bullet the atom concretises.
- [Spec 007: Unified Manifest v3](../../specs/007-unified-manifest-v2/spec.md): molecule-manifest baseline; the workflow is delivered through `atoms.workflow`.
- [Spec 008: Install Transaction](../../specs/008-install-transaction/): landed; `haex install` merges contributions into `.haex-hive/`. Multi-source constitution merge already exists; this design extends the merge surface with a second contribution type.
- [Spec 010: Compiler & Agent Adapters](2026-08-31-spec-010-compiler-preview.md): future compiler will emit per-tool artifacts; workflow.yml is one such artifact.
- [specifyr catalog pattern](https://github.com/haexhub/specifyr): sibling project defining `catalog/skills/*.md` and `catalog/tools/*.yml` with per-project overrides. This design borrows the catalog + override shape.
- [speckit-community extensions](https://speckit-community.github.io/extensions/): the extension ecosystem this atom-kind lets a project bind to.

---

## What this covers

A **speckit-workflow molecule**: a molecule whose v3 manifest carries:

1. A `workflow.yml` payload compatible with `.specify/workflows/<id>/workflow.yml` today.
2. Optionally, a `constitution.md` fragment stating the MUST rules that the workflow imposes.
3. Optionally, an `extensions.yml` fragment declaring which speckit-community extensions the workflow depends on (with version constraints).
4. Optionally, additional per-skill or per-hook payloads (e.g. custom slash commands, per-stage hook scripts).

Adoption is via `.haex-hive.json.compounds[]`, same as any other molecule. On `haex install`:

- The `atoms.workflow[]` payload lands at `.specify/workflows/<molecule-id>/workflow.yml`.
- Any constitution fragment merges into `.haex-hive/constitution.md` via the existing multi-source merge, so the workflow's MUST rules become part of the assembled constitution automatically.
- Any `atoms.extensions[]` fragment contributes its extension requirements and hook declarations to the canonical top-level `required_extensions`, `optional_extensions`, and `hooks` keys in `.specify/extensions.yml`. Requirements remain separate from hook declarations; molecule hooks are merged into the same `hooks.<stage>` lists as local hooks, with molecule entries first and local entries last.

## What this does NOT cover (deliberately)

- **Runtime enforcement of workflow adherence**: mechanical refusal on non-workflow task landings. This stays advisory-to-the-agent for now; a future ADR under Phase 7 may add a pre-commit hook, but that is orthogonal to atom distribution.
- **A registry of "approved" workflows**: every publisher is free to publish workflow molecules; there is no central curation. The operator picks their workflow the same way they pick any other molecule (by pinning a specific source+revision).
- **Live workflow updates without pinning**: an atom-adopted workflow uses the same `revision` pin as every other atom (Principle IV, NON-NEGOTIABLE). Workflow drift on the operator's device is intentional (it happens when the operator bumps the pin) and not detectable as concurrent replay.
- **Automatic installation of speckit-community extensions** the workflow declares as required. The atom declares which extensions and version constraints are needed; installation of extensions themselves is delegated to specifyr's extension-install mechanism (or a manual `speckit extensions install <name>@<version>` step). Preventing workflow use when required extensions are missing or incompatible is a validator concern, not a distribution one.

## Terminology

- **Workflow**: the ordered set of steps + review gates + hook wiring that `/speckit-implement` (and its stage siblings) executes. Concrete on-disk shape: `workflow.yml` (existing).
- **Workflow molecule**: a Spec-007 molecule whose `atoms` map includes a non-empty `workflow` list pointing at a `workflow.yml` in the molecule's directory.
- **Extension**: a speckit-community-published bundle (e.g. `V-Model Extension Pack@0.7.2`) providing skills, hooks, or workflows. Referenced by a workflow molecule but installed separately.

## Architecture

### Molecule-manifest addition

The v3 molecule manifest uses the category map defined by Spec 007. Shape:

```yaml
haex_hive_version: "3"
id: com.example.publisher.strict-tdd-workflow
version: "1.0.0"
priority: 5
atoms:
  workflow: ["workflow.yml"]
  constitution: ["constitution.md"]
  extensions: ["extensions.yml"]
  hooks: ["hooks/pre-implement.sh", "hooks/post-tasks.sh"]
```

`atoms.workflow`, `atoms.constitution`, `atoms.extensions`, and `atoms.hooks`
are molecule-directory-relative source paths. Every source path is
validated with `RepoRelativePath.validate`. The resolver then performs a
canonical containment check: the resolved source must remain below the atom
root, and the destination must remain below the consumer repository root.
Absolute paths, backslash or drive-qualified paths, `.`/`..` traversal, and
symlink or reparse-point targets that escape either root are refused. The
validator applies the same checks to every discovered file copied from the
`speckit_hooks` directory. Valid relative paths remain supported. Output paths
are never state-root-relative in committed configuration; the device-local
state root is reserved for caches and transaction internals.

The `constitution.md` fragment is contributed alongside `atoms.workflow`: same multi-source merge as any other constitution fragment. Difference: its content is scoped to workflow discipline (e.g. "every failing test MUST be reported before implementation continues"), not general system principles.

### Adoption flow

Consumer's `.haex-hive.json`:

```json
{
  "compounds": [
    {
      "source": "https://github.com/example/speckit-workflows",
      "revision": "<full 40-char SHA>",
      "molecules": ["com.example.publisher.strict-tdd-workflow"]
    }
  ]
}
```

On `haex install`:

1. The publisher's molecule is resolved via the existing publisher-clone + pinned-revision machinery.
2. The `atoms.workflow[]` payload publishes to `.specify/workflows/<molecule-id>/workflow.yml`. A non-empty workflow category makes that molecule binding; multiple workflow molecules refuse before publication.
3. The `atoms.constitution[]` fragment participates in the existing multi-source constitution merge; the constitution's declared speckit workflow bullet (v1.4.0) now applies to the adopted workflow's declared steps.
4. The `atoms.extensions[]` fragment is parsed using the `extensions.yml` contract below. Its requirements merge into the canonical `required_extensions` and `optional_extensions` lists, while its hook declarations merge into the canonical `hooks.<stage>` lists. Required declarations determine the effective requirement when an ID is also optional; a valid conflicting optional declaration is omitted with a stderr warning, while unsupported syntax refuses the install. Molecule hooks run before local hooks; a local declaration for the same hook identity (`stage`, `extension`, `command`, and `script`) replaces the molecule declaration.
5. `atoms.hooks[]` scripts land under the reserved molecule-owned namespace `.specify/extensions/workflow-molecules/<molecule-id>/` for reuse by the canonical `hooks` declarations. Community extensions remain direct child directories of `.specify/extensions/`; the installer refuses namespace or destination collisions before publication. Every molecule-contributed hook has a required repository-relative `script` destination that resolves exactly to one copied regular source file beneath the molecule's `atoms.hooks[]` paths. Missing, non-regular, duplicate, unrelated, or escaping source/destination mappings refuse before publication with `key=workflow-hook-mapping-invalid`; no unrelated repository file may satisfy a hook mapping. The copied files and the declarations that reference them are included in the same transaction.
6. All outputs from steps 2–5 and the assembled `.haex-hive/constitution.md` are prepared and validated by one repository-wide install transaction. No output is published until every output is valid and any required constitution review has been accepted. A failed review or later validation discards the staged candidate; if publication has already begun, existing in-flight recovery restores the previous marker-consistent generation and all output roots before the install reports failure. The existing `.haex-hive/` generation and rename-swap behavior remains unchanged.

### Binding selection

There is no registry or selector file. Readers inspect the resolved molecules in
`.haex-hive.json.compounds[]`: exactly one molecule with a non-empty
`atoms.workflow[]` category is binding, while no such molecule selects the
bundled `.specify/workflows/speckit/workflow.yml`. A second adopted workflow
molecule is refused deterministically with
`key=multiple-workflow-molecules-refused`. The generated extension file carries
`origin: molecule | local` on each hook entry; no persisted provenance cache is
required.

### Extension declaration format

The contributed `extensions.yml` fragment uses the same vocabulary as the
consumer file, omitting consumer-owned `installed` and `settings` keys. This
is the one canonical extension contract; no alternate molecule-specific hook key
is defined. The manifest contribution names identify source payloads, while
the destination configuration always uses the canonical keys below.

```yaml
required_extensions:
  - id: v-model-extension-pack
    version_constraint: ">=0.7.2"
    homepage: https://speckit-community.github.io/extensions/v-model-extension-pack
  - id: bugfix-workflow
    version_constraint: "1.0.0"
    homepage: https://speckit-community.github.io/extensions/bugfix-workflow

optional_extensions:
  - id: speckit-companion
    version_constraint: ">=0.21.0"

hooks:
  before_implement:
    - extension: v-model-extension-pack
      command: v_model.prepare
      script: ".specify/extensions/workflow-molecules/com.example.publisher.strict-tdd-workflow/hooks/v_model/prepare.py"
      enabled: true
      optional: false
      prompt: Run the V-Model preparation hook?
      description: Prepare the implementation stage
      condition: null
```

The local `.specify/extensions.yml` retains its consumer-owned `installed` and
`settings` keys and uses the same `required_extensions`,
`optional_extensions`, and `hooks` keys shown above. The `script` field is a
repository-relative path in the canonical output; it is required for an
molecule-contributed hook and MUST resolve to the copied file described in step 5.
Requirement entries are merged by extension ID. The effective constraint is
the logical intersection of all declarations for that ID, normalized to Spec
007's supported `X.Y.Z` exact or `>=X.Y.Z` lower-bound grammar: exact
constraints must agree, lower bounds retain the strongest lower bound, and an
exact constraint combined with a lower bound remains exact only when it
satisfies that bound. An empty intersection refuses the install with
`key=conflicting-constraint`, a non-zero exit code, and stderr naming the
extension id and both conflicting constraints; an unsupported constraint refuses with
`key=invalid-constraint`; no comma-separated, tilde, caret, or wildcard
constraint is serialized. If an ID is both required and
optional, it appears only in `required_extensions`; required status wins. A
valid optional constraint that conflicts with the required constraint is omitted
and emits `key=optional-workflow-extension-conflict` as a stderr warning.
Conflicting non-constraint metadata for the same extension id (for example,
different `homepage` values) refuses before publication with
`key=conflicting-extension-metadata`, a non-zero exit code, and stderr naming
the extension id, metadata field, and both conflicting values. The resulting
lists are sorted by extension ID, and hook entries use
the stable molecule-before-local ordering described above.

The generated canonical file carries `origin: molecule | local` on each hook
entry for diagnostics. It is regenerated from the adopted molecule's
`atoms.extensions` content plus local declarations on every install; no
`extension_contributions` map, registry file, or persisted provenance cache is
needed. Removing a molecule therefore removes its generated entries naturally,
while local entries are preserved.

Validator behaviour: on install, every `required_extensions` entry must name a
community package installed as a direct child of `.specify/extensions/` whose
authoritative semantic version is `extension.version` in `extension.yml`. A missing package
refuses with `key=required-workflow-extension-missing`; an incompatible
installed version refuses with `key=required-workflow-extension-incompatible`
(new exit-code slots). Optional extensions may be absent. Version constraints
follow Spec 007's existing `VersionConstraint` grammar; every unsupported
declaration refuses with `key=invalid-constraint` rather than being dropped.

## Constraints (constitution alignment)

- **Principle I**: the workflow molecule carries no secrets. `workflow.yml`, contributed `constitution.md` fragments, and `extensions.yml` fragments MUST NOT reference credentials.
- **Principle II**: no absolute paths. All workflow and contribution paths in committed configuration are repository-relative and pass `RepoRelativePath.validate` plus canonical containment checks. Device-local state-root paths never enter the committed configuration.
- **Principle IV**: the molecule is pinned by full 40-char SHA, same as every other molecule. No branch/HEAD adoption.
- **Principle VI**: the assembled `.haex-hive/constitution.md` still lands through the `--accept-merged` two-phase flow (or the PR-review gate for haex-hive itself). This includes exactly one workflow constitution contribution: `haex install` MUST NOT take the `assemble_single_source` shortcut for it. Without accepted merged input, the install refuses before publishing workflow outputs or changing the assembled constitution; a regression test covers this case.
- **Principle VIII**: a workflow molecule's constitution fragment MUST NOT contain concealment instructions (`--haex-confirm` and the safety validators from Spec 007 already enforce this on the merged assembly).

## Decisions for `/speckit-specify`

1. **Single active workflow**: exactly one adopted molecule may have a non-empty `atoms.workflow` category. Multi-active selection is refused.
2. **Hook precedence and order**: molecule hooks run first in declaration order; local hooks run last in canonical local order. An exact local hook identity (`stage`, `extension`, `command`, `script`) replaces the molecule entry.
3. **Extension installation**: `haex install` refuses missing required extensions; the operator installs external packages separately.
4. **Constitution-fragment merging**: append a new `## Workflow-Contributed Rules` section sourced by workflow molecule ID through the existing multi-source merge.
5. **Bundled workflow status**: the bundled `speckit` workflow is the fallback whenever no adopted molecule has a non-empty `atoms.workflow` category.
6. **Downgrade/removal**: removed workflow molecules are delete-orphaned in the same transaction. Their extension requirements and hooks are removed and the canonical extension configuration is recomputed from the remaining molecule fragment plus local declarations.

## Success criteria (measurable outcomes)

- **SC-011.1**: Adopting a workflow molecule via `.haex-hive.json.compounds[]` publishes `.specify/workflows/<molecule-id>/workflow.yml` byte-for-byte matching the molecule's contribution.
- **SC-011.2**: The molecule's `constitution.md` fragment appears in the assembled `.haex-hive/constitution.md` after `haex install --accept-merged`.
- **SC-011.3**: Adopting exactly one molecule with a non-empty `atoms.workflow` category makes the constitution's declared-speckit-workflow bullet resolve to that workflow's steps; with none adopted, the bundled workflow is selected.
- **SC-011.4**: Removing a workflow molecule from `.haex-hive.json.compounds[]` and re-installing removes the corresponding `.specify/workflows/<molecule-id>/` and `.specify/extensions/workflow-molecules/<molecule-id>/` directories and that molecule's requirements and hooks from `.specify/extensions.yml` in the same transaction, while preserving local entries.
- **SC-011.5**: A workflow molecule declaring a required extension causes `haex install` to refuse with `required-workflow-extension-missing` when the extension is absent and with `required-workflow-extension-incompatible` when the installed version fails its declared `version_constraint`. The conformance suite includes both cases.

## Required conformance scenarios

- A single workflow molecule with a constitution contribution and no accepted
  merged input is refused before publication; the previous constitution,
  workflow files, hooks, and extension configuration remain
  byte-for-byte unchanged.
- Every contribution path and every copied hook file rejects absolute paths,
  `.`/`..` traversal, and symlink or reparse-point escapes, while a valid
  relative path is accepted.
- A transaction that fails after staging or during publication restores all
  previous output roots and leaves no partially published workflow, hook,
  extension, or constitution output.
- Molecule hooks are serialized and executed in declaration order, followed by
  local hooks; molecule hooks still precede local hooks.
- Compatible requirements for one extension ID serialize to the normalized
  constraint intersection; required-versus-optional resolves to required, and
  an empty intersection refuses with `key=conflicting-constraint` while naming
  the ID and both constraints. The test asserts the exact canonical YAML bytes
  for all three cases.
- Removing the adopted molecule and reinstalling removes its workflow, copied
  hooks, requirements, and hook declarations while preserving local entries;
  with no workflow molecule remaining, readers use the bundled default.
- Every molecule hook's `script` resolves to one copied regular file under its
  molecule-owned extension directory; missing or mismatched mappings refuse before
  publication.

## Deferred to later specs

- **Runtime enforcement** of workflow adherence (pre-commit hook, GitHub Action). Advisory-to-agent for now; mechanical enforcement is a Phase 7 concern per constitution §Governance.
- **Automatic extension installation**. The atom declares what it needs; the operator installs. A future specifyr-integration spec may add auto-install.
- **Workflow versioning across satellites**: when two satellites use different workflow molecule revisions, how does `/speckit-analyze` reconcile? Deferred to a Spec-011-followup.

## Follow-up notes

- Once landed, retire the "planned Spec 011" forward-reference in constitution v1.4.0's Development Workflow bullet in a v1.4.1 (PATCH) amendment.
- The specifyr project has a `catalog/skills/` + `catalog/tools/` pattern with per-project overrides at `<project>/.specify/org/catalog/`. This spec deliberately does not adopt that catalog shape for workflows; each project pins one workflow molecule directly. If per-role, per-agent workflows are ever needed, the catalog pattern can be layered on top later.
