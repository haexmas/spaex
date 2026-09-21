# Spec 012: Speckit Session Hopper Molecule (Design Preview)

**Status**: Design preview; parked (2026-09-21: no `specs/012-*` exists). Its skill-file delivery shape is what Phase A of the [roadmap](2026-09-08-composition-ui-and-skills-externalization-roadmap.md) moves to external skill references. Captured 2026-09-02 as the requirements source for a subsequent `/speckit-specify` invocation that creates `specs/012-speckit-session-hopper-atom/`.

**Purpose**: define a first concrete `speckit-workflow` molecule (Spec 011 v3 `atoms` map) that prompts the operator, before every `command:` step of a speckit workflow, to run that step in a new agent session (fresh context) rather than inline in the current session. The prompt is advisory: the operator picks new-session or inline for each step. The molecule is fully declarative and portable across every LLM host, because the mechanism is Constitution rule plus a text-printing hook, with no client-specific subagent API.

**Related**:
- [Spec 011: Speckit Workflow Molecule](2026-09-02-spec-011-speckit-workflow-atom-design.md): defines the v3 workflow molecule (`atoms.workflow`, `atoms.hooks`, `atoms.constitution`, hook publication under `.specify/extensions/workflow-molecules/<molecule-id>/`) whose adoption is automatically binding. This molecule is an instance of that contract.
- [Spec 007: Unified Manifest v3](../../specs/007-unified-manifest-v2/spec.md): molecule-manifest baseline; publisher-manifest shape.
- [Spec 008: Install Transaction](../../specs/008-install-transaction/): single-source constitution publication (ADR 0010 retired the multi-source merge); delete-orphans on removal.
- Constitution v1.4.0, "Declared speckit workflow adherence": the bullet this molecule becomes binding under when adopted in a compound.
- [speckit-community workflows catalog](https://speckit-community.github.io/extensions/search?q=workflows): other workflow families (V-Model, bugfix-first, strict-TDD, ...). Motivation for keeping this atom workflow-agnostic in its hook script.

---

## What this covers

A single molecule, published from a new sibling repo `haexmas/atoms`, that:

1. Ships a `workflow.yml` mirroring the bundled `speckit` "Full SDD Cycle" steps (`specify`, `clarify`, `plan`, `tasks`, `analyze`, `implement`) with the same review gates between them.
2. Wires every `command:` step's `hooks.before` to one shared shell script that prints an English prompt block on stdout, telling the operator how to run the next step in a new session (which worktree to cd into, which branch is expected, which `/speckit-<step>` slash-command to invoke).
3. Ships a small `constitution.md` fragment that turns the printed prompt into a binding pre-step protocol: agents whose adopted workflow molecule is this molecule MUST display the block verbatim, wait for the operator's answer, and only continue the step inline if the operator replies `inline`.

Adoption is via `.haex-hive.json.compounds[]`, same as any other molecule. Adoption itself makes this workflow binding; no registry or activation edit is required.

## What this does NOT cover (deliberately)

- **Client-specific subagent APIs**: no adapter that spawns a Claude Code Task, a Codex agent, or a Cursor background agent. The mechanism is prompt-and-wait; the operator opens the new session by hand. A later spec MAY add native-subagent auto-start when available; not needed for the MVP the operator asked for.
- **Runtime enforcement**: no CI check, no pre-commit hook, no mechanical refusal when a step is run inline instead of in a new session. The rule is stated in the Constitution fragment and enforced by agent compliance, same as every other Constitution rule.
- **Hard-coded per-step context lists**: the hook does NOT enumerate `spec.md`, `plan.md`, `tasks.md`, or any other file names, because different community workflows (V-Model, bugfix-first, ...) produce different artefacts. The new session discovers relevant context itself through the normal speckit slash-command entry path plus the user-global CLAUDE.md, which loads `.haex-hive.json` and the constitution on session start.
- **Extension dependencies**: this atom declares no `required_extensions` and no `optional_extensions`. Isolation behaviour needs no speckit-community extension.
- **Deviation from the bundled step list**: the workflow.yml is a session-hopping mirror of the bundled `speckit` cycle, not a new step design. Different step topologies are out of scope; a downstream atom can fork this one for a bugfix-first or V-Model variant.

## Terminology

- **Isolated step**: a `command:` step the operator runs in a fresh agent session (a new conversation with cleared context) that lives in the same git worktree and on the same branch as the main session.
- **Main session**: the operator's ongoing conversation, where reviews, gates, clarifications, and coordination happen.
- **Prompt block**: the multi-line English text the `before` hook prints on stdout; the agent MUST show it to the operator verbatim and MUST NOT run the step until the operator answers.
- **`inline` reply**: the sentinel word the operator types to override the recommendation and let the current agent run the step in the main session anyway.

## Architecture

### Atom identity

- Publisher repo: `haexmas/atoms` (a new sibling to `haexmas/haex-hive`), holding multiple atoms over time. First atom is this one.
- Publisher-manifest id: `com.github.haexmas.atoms`.
- Atom id: `com.github.haexmas.atoms.speckit-session-hopper`.
- Workflow id inside `workflow.yml`: `speckit-session-hopper`. The molecule id is used for the published workflow directory and the byline; the short workflow id remains internal to the workflow payload. Spec 011 FR-002 publishes the workflow at `.specify/workflows/<molecule-id>/`.

### Repo layout

```text
haexmas/atoms/                                # git repo root
├── manifest.json                             # publisher-manifest
├── README.md                                 # adoption instructions per atom
└── speckit-session-hopper/
    ├── manifest.json                         # atom-manifest
    ├── workflow.yml
    ├── constitution.md                       # fragment
    └── hooks/
        └── before-step.sh
```

### Publisher-manifest

`haexmas/atoms/manifest.json`:

```json
{
  "haex_hive_version": "3",
  "publisher": "com.github.haexmas.atoms",
  "molecules": {
    "com.github.haexmas.atoms.speckit-session-hopper": {
      "path": "speckit-session-hopper",
      "version": "0.1.0"
    }
  }
}
```

### Molecule-manifest

`haexmas/atoms/speckit-session-hopper/manifest.json`:

```json
{
  "haex_hive_version": "3",
  "id": "com.github.haexmas.atoms.speckit-session-hopper",
  "version": "0.1.0",
  "priority": 30,
  "atoms": {
    "workflow": ["workflow.yml"],
    "constitution": ["constitution.md"],
    "hooks": ["hooks/before-step.sh"]
  }
}
```

### workflow.yml

Mirrors the bundled `speckit` cycle. Every `command:` step gains one `hooks.before` entry pointing at the shared script. The script destination path uses the reserved molecule-owned namespace from Spec 011 FR-003.

```yaml
schema_version: "1.0"
workflow:
  id: "speckit-session-hopper"
  name: "SDD cycle with per-step session isolation"
  version: "0.1.0"
  author: "haexmas"
  description: "Same steps as bundled speckit, but prompts the operator to run each command step in a fresh agent session."

requires:
  speckit_version: ">=0.7.2"

inputs:
  spec:
    type: string
    required: true

steps:
  - id: specify
    command: speckit.specify
    hooks:
      before:
        - script: .specify/extensions/workflow-molecules/com.github.haexmas.atoms.speckit-session-hopper/before-step.sh
          args: ["specify"]
    input:
      args: "{{ inputs.spec }}"

  - id: review-spec
    type: gate
    message: "Review the generated spec before planning."
    options: [approve, reject]
    on_reject: abort

  - id: clarify
    command: speckit.clarify
    hooks:
      before:
        - script: .specify/extensions/workflow-molecules/com.github.haexmas.atoms.speckit-session-hopper/before-step.sh
          args: ["clarify"]

  - id: plan
    command: speckit.plan
    hooks:
      before:
        - script: .specify/extensions/workflow-molecules/com.github.haexmas.atoms.speckit-session-hopper/before-step.sh
          args: ["plan"]

  - id: review-plan
    type: gate
    message: "Review the plan before generating tasks."
    options: [approve, reject]
    on_reject: abort

  - id: tasks
    command: speckit.tasks
    hooks:
      before:
        - script: .specify/extensions/workflow-molecules/com.github.haexmas.atoms.speckit-session-hopper/before-step.sh
          args: ["tasks"]

  - id: analyze
    command: speckit.analyze
    hooks:
      before:
        - script: .specify/extensions/workflow-molecules/com.github.haexmas.atoms.speckit-session-hopper/before-step.sh
          args: ["analyze"]

  - id: implement
    command: speckit.implement
    hooks:
      before:
        - script: .specify/extensions/workflow-molecules/com.github.haexmas.atoms.speckit-session-hopper/before-step.sh
          args: ["implement"]
```

Whether the review gates additionally recommend a new session for the review itself is an open question (see below). Baseline: gates stay in the main session, because their reason for existing is the operator's decision.

### hooks/before-step.sh

One script for every step. It reads the step name from `$1`, discovers the worktree root, branch, and checked-out commit from `git`, generates a fresh handoff nonce, and prints the English prompt block on stdout. No repository file lookup, no network, no jq.

```sh
#!/usr/bin/env sh
set -eu

STEP="${1:-<step>}"
BRANCH="$(git branch --show-current 2>/dev/null || echo '<unknown>')"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
COMMIT="$(git rev-parse HEAD 2>/dev/null || echo '<unknown>')"
NEWLINE='
'
case "$ROOT$BRANCH$STEP" in
    *"$NEWLINE"*)
        echo "cannot emit handoff marker with a newline in root, branch, or step" >&2
        exit 1
        ;;
esac
ROOT_ESCAPED="$(printf '%s' "$ROOT" | sed "s/'/'\"'\"'/g")"
ROOT_ESCAPED="'${ROOT_ESCAPED}'"
BRANCH_ESCAPED="$(printf '%s' "$BRANCH" | sed "s/'/'\"'\"'/g")"
BRANCH_ESCAPED="'${BRANCH_ESCAPED}'"
HANDOFF_NONCE="$(od -An -N16 -tx1 /dev/urandom 2>/dev/null | tr -d '[:space:]')"
if [ -z "$HANDOFF_NONCE" ]; then
    HANDOFF_NONCE="$(date +%s)-$$-${COMMIT}"
fi

cat <<EOF
======================================================
Next step: /speckit-${STEP}
Recommendation: run this in a NEW session (isolated context).

Open a new session in the same worktree:
    cd ${ROOT_ESCAPED}
Expected branch: ${BRANCH}
Paste this exact one-shot marker as the first message in that session:
HAEX-HIVE-HANDOFF: com.github.haexmas.atoms.speckit-session-hopper ${STEP}
root: ${ROOT_ESCAPED}
branch: ${BRANCH_ESCAPED}
commit: ${COMMIT}
nonce: ${HANDOFF_NONCE}
Then run:
    /speckit-${STEP}

Or reply "inline" to keep this agent running the step here.
======================================================
EOF
```

Notes:

- The script uses POSIX `sh` (not bash) for portability across the operator's environment. `ROOT_ESCAPED` is a single-quoted POSIX-shell literal, so spaces, command substitutions, backticks, quotes, and shell metacharacters in the worktree path remain data when the printed command is pasted.
- It does NOT reference the constitution or any spec artefacts. The new session finds those itself: the user-global CLAUDE.md loads `.haex-hive.json` and the constitution automatically on session start (haex-hive detection); the `/speckit-<step>` slash-command reads whatever `specs/<slug>/` files are relevant for that step; the adopted molecule is resolved by the reader helper.
- The five-line `HAEX-HIVE-HANDOFF` block is a one-shot protocol marker, not a shell command; every marker line is emitted at column 1 so the copied block has its exact protocol form. The hook rejects newline-containing root, branch, or step values before emission, so each field remains one marker line. Its `root` and `branch` values are single-quoted POSIX-shell literals containing the originating session's exact values. `commit` is the exact output of `git rev-parse HEAD`, and `nonce` is fresh for this emission (random bytes when available, with the timestamp/process/commit fallback). A new session consumes the marker only when the atom, step, root (`git rev-parse --show-toplevel`), branch (`git branch --show-current`), and commit (`git rev-parse HEAD`) all match its current context and the nonce has not already been consumed in this checkout; otherwise it rejects the marker and follows the normal prompt-and-wait rule. A valid marker skips this atom's `hooks.before` prompt once and executes exactly `/speckit-<step>`; it MUST NOT be forwarded or reused for a later step or checkout.
- Before executing a valid marker's step, the session atomically claims the nonce in the device-local haex state root under `session-handoffs/consumed/<nonce>/`. Exclusive directory creation is the consumption event; an existing nonce is rejected, so copied markers cannot rerun a non-idempotent step in the same checkout. The claim record contains the atom, step, root, branch, commit, and nonce and is written before execution; this state is never committed to the repository. A crash after the claim is treated as consumed (at-most-once semantics).
- It falls back gracefully outside a git worktree (`<unknown>` branch, current directory as root). The atom is not intended for non-git use; that fallback exists only to avoid a shell error if someone accidentally invokes the script by hand.
- Executable bit: Spec 011 FR-003 states hook payloads are copied byte-identically. Before activation, the hook check uses the exact invocation semantics of the runner: a direct-execution runner requires the published regular file to have its executable mode and to run successfully; an interpreter-mediated runner requires the corresponding interpreter invocation to run successfully. If a manual `chmod +x` is needed for a direct runner, it MUST happen before the activation check; the atom MUST NOT be activated with an unexecutable hook.

### constitution.md (fragment)

Kept short. English. States one MUST rule.

```markdown
## Per-step session isolation

Sessions whose adopted workflow molecule resolves to
`com.github.haexmas.atoms.speckit-session-hopper` MUST, before every
`command:` step of that workflow:

1. If the session's first message is the exact five-line one-shot marker
   consisting of
   `HAEX-HIVE-HANDOFF: com.github.haexmas.atoms.speckit-session-hopper <step>`,
   `root: <single-quoted-originating-repository-root>`,
   `branch: <single-quoted-originating-branch>`, `commit: <originating-HEAD>`,
   and `nonce: <fresh-nonce>`, validate that the atom, `<step>`, decoded root,
   decoded branch, and commit match the current session and repository, and
   that `<step>` equals the runner's current `command:` step ID (the step that
   invoked `hooks.before`). If any value differs, reject the marker and
   continue with the normal hook below; never execute the marker's requested
   step when it differs from the active step. Before constructing the claim
   path, require `<nonce>` to match
   `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`; reject empty, separator-containing,
   traversal, or otherwise invalid values. If all values match, atomically
   create the device-local `session-handoffs/consumed/<nonce>/` claim directory
   and atomically rename its bound record into place before executing the step.
   An existing claim rejects the marker; there is no retry after a crash
   following a successful claim. Only after a successful claim, skip the prompt
   exactly once and execute the current step. The marker MUST NOT be forwarded
   to another step or session.
2. Otherwise, execute the step's `hooks.before` script and capture its stdout.
3. Display the captured block to the operator verbatim.
4. Wait for the operator's answer.
5. Continue the step in the current session only if the operator's
   answer is exactly `inline`. On any other answer, stop and defer
   the step to the new session the operator opens; the current
   session resumes at the next review gate once the new session's
   output is on disk.
```

**Superseded 2026-09-04 (ADR 0010), pending Spec 011 redesign**: the
multi-source merge this paragraph relied on (Spec 011 FR-004) was retired.
The fragment is expected to instead become `binding: recommended` prose
compiled into `CLAUDE.md`/`AGENTS.md` under a `## Workflow-Contributed Rules`
section, but that compilation mechanism (Spec 010, compiler + adapters) does
not exist yet as of this writing. The byline/subsection structure described
below may or may not survive that redesign unchanged; do not implement
against this paragraph until Spec 011 is rewritten.

~~The multi-source merge (Spec 011 FR-004) appends this fragment under
`## Workflow-Contributed Rules` with the molecule-id byline; the header
above becomes an `### Per-step session isolation` subsection under the
byline heading, so no header conflict occurs.~~

## Adoption flow (superseded; pending Spec 011 redesign)

The following flow is retained as historical design context only. It is
superseded by ADR 0010 and the pending Spec 011 redesign: Spec 010's compiler
and adapters do not exist yet, so these steps are not operational guidance and
must not guide implementation or an operator-run adoption.

1. Adopt the molecule in `.haex-hive.json.compounds[]`:

   ```json
   {
     "haex_hive_version": "3",
     "compounds": [{
       "source": "https://github.com/haexmas/atoms",
       "revision": "<full-40-char-sha>",
       "molecules": ["com.github.haexmas.atoms.speckit-session-hopper"]
     }]
   }
   ```
2. **Superseded; do not run.** The former flow would have run `haex install` for this design's single constitution contribution and selected `assemble_single_source(...)`. Its publication and refusal behavior are pending the Spec 011 redesign; the command is not an operational adoption instruction.
3. **Superseded; do not run.** The former flow would have verified the v3 workflow and hook outputs directly. Their paths, publication mechanism, and hook-runner integration remain pending the Spec 010 compiler/adapters and Spec 011 redesign; no current adoption may be treated as successful from these assertions.

Post-adoption state (superseded; pending redesign; not current behavior):

- `.specify/workflows/com.github.haexmas.atoms.speckit-session-hopper/workflow.yml` published.
- `.specify/extensions/workflow-molecules/com.github.haexmas.atoms.speckit-session-hopper/before-step.sh` published.
- `.haex-hive/constitution.md` contains the "Per-step session isolation" subsection under `## Workflow-Contributed Rules`.
- Every subsequent agent session opened in this repo, reading its user-global CLAUDE.md, loads the constitution, sees the MUST rule, and consequently prompts before every command step unless it receives the valid one-shot handoff marker for that step.

## Removal (downgrade)

Removing the molecule entry from `.haex-hive.json.compounds[]` and rerunning `haex install`
triggers Spec 011 US3 (delete-orphans): the workflow directory, the hook
directory, and the constitution fragment are removed by their respective
per-tree rename-swap publications; no cross-tree atomicity is claimed. If
There is no activation state to reset. The reader falls back to the bundled
workflow once the molecule is removed. No molecule-specific removal logic is
needed.

## Assumptions

- **Same-worktree new sessions**: the operator opens the new session in the same git worktree and on the same branch as the main session. The atom does NOT recommend or automate worktree-per-step. Rationale: worktree-per-step multiplies filesystem state without buying isolation the operator asked for, and speckit artefacts live inside `specs/<slug>/` on the current worktree either way.
- **Advisory-only enforcement**: compliance rests on the Constitution rule, which agents are already required to obey under Principle II family (haex-hive constitution NON-NEGOTIABLEs). No mechanical guard.
- **Bundled `speckit` remains available**: adopting this molecule does not remove the bundled workflow. Removing it from `compounds[]` makes the bundled workflow binding again, per Spec 011 FR-006/FR-008.
- **English text**: all operator-facing text shipped by the atom is English. The atom is meant to be publisher-neutral and locale-agnostic.

## Open questions

1. **Review gates and isolation**: should the workflow additionally recommend a new session for review-gate steps? Default: no, because gates are the operator's decision moment and belong in the main session. If a future variant wants to isolate long "analyze" or "review-plan" reads, a fork of this atom can add `hooks.before` to gate steps too.
2. **Executable bit on published hook script**: Spec 011 FR-003 says byte-identical copy. The activation flow now resolves the ambiguity using the actual runner semantics: direct runners require executable mode, while interpreter-mediated runners require a successful interpreter invocation. Spec 011 may later formalize mode preservation for `speckit_hooks/**`; a manual `chmod +x` is only a pre-activation remediation for direct runners.
3. **`inline` as the sentinel word**: any risk of collision with an operator who genuinely wants to say "inline" as text? Extremely unlikely inside a "new-session-or-inline" prompt, but the constitution rule could be tightened to "exactly the single token `inline`, case-insensitive" if collisions ever surface.
4. **Second `haexmas/atoms` occupant**: this design leaves publisher-manifest room for future atoms in the same repo. Adding a second atom is a follow-up PR against `haexmas/atoms` that appends to `manifest.json.atoms`. No design change here.

## Deferred to later specs

- **Native-subagent auto-start** on hosts that support it (Claude Code Task, Codex, ...). Would need a per-host adapter and a workflow.yml field like `hooks.before.mode: subagent`. Reasonable for a Spec-012-successor once at least two host adapters exist.
- **Verify-only mode reporting isolation status** (relies on Spec 008 US2 `--verify-only`, still deferred).
- **Different step topologies**: bugfix-first, V-Model, strict-TDD. Each becomes its own atom in `haexmas/atoms/` or a separate publisher repo; they can share the same `before-step.sh` pattern.
