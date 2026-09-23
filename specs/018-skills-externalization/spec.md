# Feature Specification: External Skill References

**Feature Branch**: `018-skills-externalization`
**Created**: 2026-09-14
**Status**: Implemented (reviewed and accepted via PR #125; molecule-side contract in PR #172; consumer-controlled policy and commands in the follow-on change)
**Input**: Phase A of the composition UI and skills externalization roadmap

## Clarifications

### Session 2026-09-14

- Q: Wie wird ein externer Skill beim Nutzer installiert und woher kommt der
  Installer? → A: `external_skills` wird strukturiert modelliert und enthält
  nur Quelle, Revision und Pfad. Der Nutzer/Consumer entscheidet über den
  Installer, den Ziel-Agenten, den Scope und den Ausführungszeitpunkt. Weder
  Provider noch spaex erzwingen `skillsmd`, die Vercel-CLI oder einen anderen
  Installer. `agentskills.io` ist nur die Format-Spezifikation.
- Q: Wie erhält der Consumer-Adapter die strukturierten Referenzen? → A: Es liest
  das bereits gepinnte Molekül-`manifest.json` direkt. spaex erzeugt keine
  temporäre JSON-Kopie und dupliziert die Referenzen nicht in einer zweiten
  Übergabedatei. Für robuste Pfadauflösung stellt spaex dem Adapter den Pfad des
  Originalmanifests über `SPAEX_MOLECULE_MANIFEST` zur Verfügung.
- Q: Gehört der Installer in jede einzelne Skill-Referenz? → A: Nein. Eine
  Referenz enthält nur Quelle, Revision und Pfad. Die Installationsentscheidung
  gehört zur Consumer-Konfiguration beziehungsweise zum konkreten Aufruf.
- Q: Wann wird die Installationsentscheidung abgefragt? → A: `spaex install`
  installiert externe Skills nie automatisch und fragt nicht implizit nach. Es
  materialisiert Atome und zeigt verfügbare externe Skills als ausstehend an.
  Ein expliziter Aufruf `spaex skills install` startet beim ersten Mal die
  Konfiguration und speichert sie in der Consumer-`.spaex/manifest.json`.
  Änderungen erfolgen später explizit über `spaex skills configure`; bereits
  installierte externe Skills werden dabei nicht automatisch gelöscht.

## User Scenarios & Testing

### User Story 1 - Declare an external skill without copying it (Priority: P1)

As a molecule publisher, I can keep a standard Agent Skill in the same
publisher repository (or another repository) and declare its source reference
separately from delivered file atoms, so spaex records the dependency without
materializing the skill itself.

**Independent Test**: Parse a molecule manifest containing `external_skills`
and verify that the references are exposed as immutable values while no skill
file is added to the atom map.

**Acceptance Scenarios**:

1. **Given** a valid external skill reference, **when** a v4 molecule manifest
   is parsed, **then** the reference is preserved in declaration order.
2. **Given** a molecule with external skills but no `install_hook`, **when**
   the manifest is validated, **then** validation accepts it; installation
   is a separate consumer action.
3. **Given** a skill stored under `haexmas/atoms/skills/`, **when** a molecule
   references its revision-specific repository/tree source, **then** the skill
   remains owned by the publisher repository and is installed only through
   the explicitly selected consumer adapter, outside atom materialization.

### User Story 2 - Prevent the retired skill atom category (Priority: P1)

As a spaex maintainer, I want old `skill`/`skills` atom declarations to fail
clearly, so publishers cannot silently continue shipping registry-owned skill
files through spaex.

**Independent Test**: Validate manifests using either retired category and
assert a schema refusal before any install resolution occurs.

**Acceptance Scenarios**:

1. **Given** `atoms.skill` or `atoms.skills`, **when** the manifest is
   validated, **then** schema validation rejects the manifest.
2. **Given** an unrelated open atom category, **when** the manifest is
   validated, **then** it remains accepted.

### User Story 3 - Let the consumer choose the installation mechanism (Priority: P2)

As a consumer, I can choose how and where declared external Agent Skills are
installed, so a provider cannot silently select an installer, target agent, or
installation scope for me.

**Independent Test**: Adopt a fixture molecule with `external_skills`, verify
that normal `spaex install` only reports the pending references, then invoke
the explicit skill-install command and verify that the selected consumer-side
installer receives the structured source reference.

## Edge Cases

- Empty or whitespace-only references are invalid.
- References containing control characters are invalid.
- Duplicate references are invalid.
- A molecule without `external_skills` remains backwards-compatible.
- `install_hook` failure behavior remains governed by Spec 016 for unrelated
  provider hooks. Explicit adapter failures return a non-zero exit status and
  leave atom files and `install.lock` unchanged; external side effects cannot
  be rolled back by spaex.

## Requirements

### Functional Requirements

- **FR-001**: A molecule manifest MUST accept an optional top-level
  `external_skills` array of unique, structured skill references. Each
  reference MUST declare a repository, a full immutable revision SHA, and a
  repository-relative skill path. The reference MUST NOT declare an installer.
- **FR-002**: `external_skills` objects MUST be preserved in declaration order
  and MUST be exposed immutably by `MoleculeManifest`.
- **FR-003**: A molecule declaring external skills MUST NOT be required to
  declare an `install_hook` solely for skill installation. An unrelated
  provider hook remains governed by Spec 016.
- **FR-004**: The schema MUST reject `atoms.skill` and `atoms.skills`.
- **FR-005**: Other atom category names MUST remain open and unchanged.
- **FR-006**: spaex MUST NOT silently select an installer, target agent, scope,
  or installation time on behalf of the provider. External skill installation
  MUST use an explicit consumer/user choice. The referenced skill MAY live
  under the same publisher repository as the molecule.
- **FR-007**: Existing molecules without `external_skills` MUST remain valid.
- **FR-008**: Documentation MUST describe that the consumer-selected installer
  and its version are outside spaex's lockfile; the installed skill content
  remains outside spaex's materialized atom paths.
- **FR-009**: Phase A MUST NOT require moving skills out of the publisher
  repository. A publisher MAY keep molecule files and standard `SKILL.md`
  directories in `haexmas/atoms`.
- **FR-010**: Any consumer-selected installer integration MUST read the
  structured skill references from the pinned molecule manifest, using
  `SPAEX_MOLECULE_MANIFEST` when resolving the manifest path. spaex MUST NOT
  create a second serialized copy solely to pass `external_skills` to an
  installer.
- **FR-011**: Normal `spaex install` MUST NOT invoke an external skill
  installer. It MUST leave the declared references unmaterialized and MAY
  report them as pending for an explicit skill-install operation.
- **FR-012**: An explicit `spaex skills install` operation MUST use the
  consumer's persisted `skill_installation` policy. If no policy exists, the
  operation MUST prompt in an interactive session and persist the accepted
  choice in the consumer `.spaex/manifest.json`.
- **FR-013**: `spaex skills configure` MUST allow the consumer to change the
  persisted mode, installer, target-agent, and scope choices. Changing the policy
  MUST NOT implicitly remove already installed external skills.

- **FR-014**: Policy modes and non-interactive behavior MUST follow the
  [consumer policy contract](contracts/consumer-manifest-skill-installation.v1.md).
  Missing consent or an incomplete managed policy MUST NOT execute an adapter
  or write configuration. Configuration must be persisted successfully before
  executing the selected adapter.

### Key Entities

- **External skill reference**: A structured source declaration that
  identifies a repository, immutable revision, and repository-relative
  skill path. The source content remains external to spaex.
- **Molecule**: A pinned spaex bundle that may deliver files and may declare
  external references installed through an explicit consumer-selected adapter.

### Scope boundary: ownership versus delivery

The publisher repository owns the source tree for both molecules and any
co-located Agent Skills. The distinction is the delivery mechanism:

- `atoms.<category>` lists files that spaex materializes and records in
  `install.lock`.
- `external_skills` lists structured skill sources that spaex records as
  metadata.
- A consumer-selected installer delegates the actual skill installation and
  owns the agent-specific target and lifecycle.
- The selected installer reads the original pinned molecule manifest through
  `SPAEX_MOLECULE_MANIFEST`; no generated external-skills payload is created.
- The consumer's `skill_installation` policy belongs to
  `.spaex/manifest.json`, not to the provider molecule manifest.
- `spaex install` and external skill installation are separate operations;
  provider-controlled hooks are not the default skill-installation mechanism.

Therefore Phase A does not delete or relocate skills from `haexmas/atoms`; it
removes only the old spaex-delivered `skill`/`skills` atom contract.

## Success Criteria

- **SC-001**: Valid external-skill manifests parse and expose references
  without materializing a skill file.
- **SC-002**: 100% of manifests using the retired skill categories fail schema
  validation before install resolution.
- **SC-003**: Existing non-skill molecule fixtures continue to pass the full
  contract and integration test suite.
- **SC-004**: The feature adds no mandatory runtime dependency on Node, uv,
  skills.sh, agentskills.io, or a particular installer.
- **SC-005**: A normal `spaex install` produces no external skill side effect;
  installation occurs only after an explicit consumer action and a persisted
  or newly confirmed consumer policy.

## Assumptions

- The existing v4 manifest envelope remains the schema envelope; the spaex
  package major version records the intentional publisher-facing break.
- Consumers MAY select `skillsmd` through `uvx`, the Vercel `skills` npm CLI,
  or another compatible installer. Provider manifests MUST NOT force one
  choice, and spaex does not synthesize or execute an installer command
  without an explicit consumer choice.
- The consumer policy is stored under `skill_installation` in the consumer's
  `.spaex/manifest.json`; the exact adapter implementation remains a consumer
  concern.
- A skill MAY remain in `haexmas/atoms`; migration changes the molecule's
  delivery contract, not necessarily the skill repository layout.
