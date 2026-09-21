# haex-hive Scope Realignment (Design)

**Status**: Design. Captured 2026-09-03 from a brainstorming session that re-examined the project's premise rather than a single feature. Supersedes the scope framing of the main design doc; does not yet supersede any landed spec.

**Implementation status (2026-09-21)**: Partly executed. Decision 9 (drop the multi-source LLM constitution merge) is recorded as [ADR 0010](../adr/0010-drop-multi-source-llm-constitution-merge.md), and Decision 11 (recalibrated hook trust model) is reflected by [Spec 016](2026-09-08-spec-016-molecule-install-hooks-design.md), which runs hooks as plain subprocesses under the operator's permissions and does not depend on Spec 009. The other decisions have not been re-checked against the shipped code in this update. Note that the project has since been renamed to spaex (4.0.0), and that the constitution assembly now runs through the behavior harness ([Spec 023](../../specs/023-behavior-harness/)).

**Purpose**: The operator asked two questions in sequence. First, whether "model everything as a skill" would simplify the harness model. Second, and more fundamentally, whether haex-hive still solves a problem that is not already solved elsewhere. This document records the ecosystem findings, the resulting scope decisions, and what they mean for the specs in flight.

**Related**:
- [Main haex-hive design](2026-08-26-haex-hive-design.md): its Phase 3/4 vision is retired by Decision 1.
- [Spec 007: Unified Manifest v2/v3](../../specs/007-unified-manifest-v2/spec.md): the `contributes`/`atoms` category map is restructured by Decision 6; multi-source assembly changes under Decision 9.
- [Spec 008: Install Transaction](2026-08-29-spec-008-install-transaction-requirements.md): transaction primitives landed; its install CLI contract is amended by Decisions 9 and 10.
- [Spec 009: Hook Boundary](2026-08-29-spec-009-hook-boundary-requirements.md): recalibrated by Decision 11.
- [Spec 010: Compiler & Agent Adapters](2026-08-31-spec-010-compiler-preview.md): adapter surface shrinks under Decision 3; `contributes.*` extension list replaced by Decision 6; degradation reporting added by Decision 7.
- [Spec 013: `haex add` and molecule rename](2026-09-02-spec-013-add-cli-and-molecule-rename-design.md): gains the manifest-optional adoption path from Decision 4.
- [ADR 0010](../adr/0010-drop-multi-source-llm-constitution-merge.md): records Decision 9 against landed behaviour.

---

## 0. Normative status

This is a design record. It fixes *direction*, not contracts. The normative home
for every requirement below is a numbered spec under `specs/`, written through
`/speckit-specify` per [ADR 0009](../adr/0009-declared-speckit-workflow-adherence.md)
and the constitution's Development Workflow clause.

Three blocks in this document were written in normative language during PR 59
review and are marked inline as **design input**: the manifestless adoption
algorithm (Decision 4), the `haex-install-result-v1` shape and exit-code table
(Decision 10), and the handoff manifest (Decision 1). They are worked-out
proposals for the spec phase, not settled contracts, and their field names,
identity derivations and code assignments are expected to change there.

## 1. Findings

The externally verifiable claims in this section have claim-level sources and
verification dates. “No tool found” statements are bounded assessments of the
listed sources, not proofs about every product in the ecosystem.

### Agent Skills is a format standard, not a package manager

The [Agent Skills specification](https://github.com/agentskills/agentskills/tree/main/docs/specification) (originally Anthropic, released as an open standard) defines a directory containing `SKILL.md` with YAML frontmatter. Required: `name`, `description`. Optional: `license`, `compatibility`, `metadata`, `allowed-tools` (experimental). `metadata` is an explicit third-party extension namespace, constrained to a flat string-to-string map. A reference validator exists (`skills-ref validate`). **Verified 2026-09-03.**

Adoption covers effectively the whole "perspective set" Spec 010 targeted: the [Agent Skills client showcase](https://agentskills.io) lists Claude Code, Codex, Gemini CLI, Cursor, GitHub Copilot, VS Code, opencode, Amp, Goose, Kiro, Factory, pi, Trae, Roo Code, Junie, Tabnine, OpenHands, Letta, Hermes and others. **Verified 2026-09-03.**

The specification covers skill structure, discovery and activation, but does not define a registry, distribution package, dependency graph, or hook contract; those omissions are visible in the [official specification](https://github.com/agentskills/agentskills/tree/main/docs/specification). **Verified 2026-09-03.**

### Neighbouring distribution mechanisms lack immutable pinning

- `skills.sh` installs via [`npx skills add <owner/repo>`](https://github.com/vercel-labs/skills#install-a-skill). Its documented CLI accepts repository, skill, agent and scope selections, but no commit-SHA lockfile input. **Verified 2026-09-03.**
- Spec Kit community extensions use `extension.yml` and catalog/release metadata through [`specify extension add`](https://github.com/github/spec-kit/blob/main/docs/reference/extensions.md). The documented installer accepts a name, catalog or archive URL, not a commit-SHA pin; that is insufficient for Principle IV. **Verified 2026-09-03.**

### The delegation problem has been solved by others

- **Claude Code Remote Control** ([official documentation](https://code.claude.com/docs/en/remote-control), verified 2026-09-03) makes a browser or the Claude mobile app a viewport into a local session. The session keeps its filesystem, MCP servers, tools and project configuration on the host machine; the remote surface is not a harness synchronizer.
- **OpenHands** ([official repository](https://github.com/All-Hands-AI/OpenHands), verified 2026-09-03) provides an open-source coding-agent platform with local and hosted deployment options; this design treats it as an execution plane, not a cross-device harness composition layer.
- **Buzz** ([official repository](https://github.com/block/buzz), verified 2026-09-03) provides a self-hosted, Nostr-oriented collaboration and agent-execution surface. This design treats it as an execution plane and integration target, not as a replacement for pinned harness composition.
- **ACP (Agent Client Protocol)** ([official introduction](https://agentclientprotocol.com/get-started/introduction), verified 2026-09-03) standardises editor-to-agent communication over JSON-RPC, with stdio locally and HTTP/WebSocket for remote scenarios; its documentation explicitly says full remote-agent support is still a work in progress.

### The consistency problem has been solved by nobody

Within the capabilities described by those primary sources, none addresses whether an agent reached on a second device *behaves* the same as on the first. Remote Control is explicitly a viewport into that machine's own configuration; ACP defines session communication; Buzz and OpenHands provide execution surfaces. This is the bounded product finding behind haex-hive's scope, verified by reviewing those sources on 2026-09-03, rather than a claim that no other tool could exist.

## 2. The three planes

The project has been conflating three separable concerns.

| Plane | Question it answers | State of the art |
|---|---|---|
| **Harness** | Does the agent behave the same everywhere? | Unsolved. This is haex-hive. |
| **Environment** | Does the build work the same everywhere? | Solved by Nix, devcontainers, mise, devbox, podman. |
| **Execution** | Can I reach the device? | Solved by ACP, Buzz, OpenHands, Remote Control. |

## 3. Decisions

### Decision 1: haex-hive builds no execution plane; it defines a handoff contract instead

Phase 3 and Phase 4 of the main design doc (the Nostr liveness plane, cross-device delegation, mobile control) are retired as haex-hive deliverables. haex-hive ships no daemon, no transport, no device identity plane, no session protocol and no mobile client. This is an internal scope decision, recorded here on 2026-09-03.

**On the ACP-over-Nostr architecture specifically.** The operator's original plan was Nostr-based, and it is sound on its merits: the [Nostr protocol](https://github.com/nostr-protocol/nips) supplies keypair-based event identity and relay-based transport, while [ACP](https://agentclientprotocol.com/get-started/introduction) supplies editor-to-agent session semantics. The combination is a real architecture and much smaller than building from scratch. **Verified 2026-09-03.**

It is nonetheless rejected as a haex-hive deliverable for two reasons that are about timing and duplication, not merit:

1. ACP's remote transport is explicitly work in progress ([ACP introduction](https://agentclientprotocol.com/get-started/introduction), verified 2026-09-03). Bridging against it now is bridging a moving target at its most expensive moment.
2. [Buzz](https://github.com/block/buzz) already occupies the self-hosted, Nostr-oriented execution space (repository reviewed 2026-09-03). Building a second one requires an explicit answer to "why not Buzz", and that answer must be stated rather than assumed.

**What haex-hive does own is the handoff.** When a task is delegated to another device, the harness pin travels with it, and the receiving side runs `haex install` at that pin before starting the agent. That is the actual guarantee behind "the same thing runs everywhere", it is small, and it is implementable against any execution plane: against Buzz, against Remote Control via a session hook, against a future bridge.

**Design input for the spec phase**, not a settled contract. The handoff
payload is a versioned, repository-relative manifest. Its minimum shape is:

```json
{
  "schema": "haex-handoff-v1",
  "harness": {
    "source": "https://github.com/acme/harness",
    "revision": "0123456789abcdef0123456789abcdef01234567",
    "lockfile": {
      "path": ".haex-hive/install.lock",
      "content_integrity": "sha256-<base64>"
    }
  },
  "target_install_path": ".haex-hive/"
}
```

`source` is the canonical repository URL and `revision` is a full immutable
40-hex commit SHA. `lockfile.path` and `target_install_path` are POSIX,
repository-relative paths; neither may contain a local absolute path. The
lockfile hash is the SHA-256 of the exact lockfile bytes, while any
`constitution.content_integrity` inside that lockfile remains the content
hash for the generated constitution. The receiver validates the manifest,
materializes the publisher clone locally at the pinned SHA before invoking
`haex install`, installs into the target path, and verifies the lockfile hash
before starting the execution-plane session. If the pinned source or its
selected local content is unavailable, `haex install` refuses with exit 3;
the execution plane must report that failure and must not start the agent.

Validation, resolution, installation, or hash failure aborts the handoff and
must not start the agent or claim that the task was accepted. The receiver
leaves existing published output untouched on a pre-publication failure and
reports the failure to the execution plane. A successful handoff reports the
installed revision and any compiler degradations. This is the complete
interoperability boundary; Buzz, Remote Control, and future execution planes
may transport the manifest however they choose.

If a minimal ACP-over-Nostr bridge is built later, it belongs in a separate repository with a separate release cycle (working name `haex-relay`) and consumes this contract. It is not a precondition for anything here. Revisit no earlier than: the harness plane is complete, and [ACP remote transport](https://agentclientprotocol.com/get-started/introduction) is no longer marked work in progress. **Status verified 2026-09-03.**

### Decision 2: the environment plane is declared, never installed

A project's toolchain (Rust, Tauri, Android SDK, Node) is not haex-hive's to resolve. Nix's [`flake.lock`](https://nix.dev/manual/nix/latest/command-ref/new-cli/nix3-flake) already pins a package graph, while [Docker Compose](https://docs.docker.com/compose/), [devcontainers](https://containers.dev/), [mise](https://mise.jdx.dev/) and [devbox](https://www.jetify.com/devbox/docs/) provide their own environment mechanisms. **Verified 2026-09-03.**

There is nonetheless a real gap on the harness plane: **Nix tells the machine which toolchain applies; it tells the agent nothing.** An agent cloning a project onto a fresh server does not know it must run `nix develop` first, calls `cargo`, gets "command not found", and improvises with a system package manager. That is precisely the class of damage the harness exists to prevent.

The manifest therefore gains a small declarative `environment` block:

```json
{
  "environment": {
    "provider": "docker-compose",
    "requires": [
      { "check": "docker compose version",
        "hint": "Docker Engine + Compose plugin: https://docs.docker.com/engine/install/" }
    ],
    "exec_prefix": ["docker", "compose", "exec", "-T", "dev"],
    "verify": "cargo tauri --version"
  }
}
```

Field semantics:

- **`requires`** checks that the provider itself is present, from outside. Each entry is a command plus an operator-facing hint. Failure means "the provider is missing, install it yourself".
- **`exec_prefix`** is the command prefix every build command must carry. Its presence *is* the mode: present means the agent runs outside the environment and must wrap; absent means commands run directly, which covers both a correct host toolchain and an agent already running inside a container. No mode enum is needed, and none is introduced.
- **`verify`** checks the toolchain from inside, after wrapping. Failure means "you are not in the dev environment".

The prefix form covers every mainstream provider: `["nix","develop","-c"]`, `["mise","exec","--"]`, `["devbox","run","--"]`, `["docker","compose","exec","-T","dev"]`. Environments that cannot be expressed as a command prefix are out of scope; in practice a prefix equivalent always exists.

haex-hive compiles this into a prose instruction in the per-tool prose file
stating how to run build commands and that system-level package installation is
forbidden. It generates the `SessionStart` hook only for a target that supports
hooks. If `exec_prefix` is present, the hook runs `requires` outside the
provider, then runs `verify` through the active environment prefix. If
`exec_prefix` is absent, it skips the outside-provider checks and runs
`verify` directly in the current environment. A failed `verify` check is a
system refusal with exit 5 and an explicit diagnostic; that behaviour is
settled here because `verify` means the operator is inside the wrong
environment. A failed `requires` check is a policy question: it may refuse
the install or warn while letting the compiled prose carry the instruction.
Open Question 4 records this and neither the action nor the exit code is
settled by this document. A target without hooks gets the prose instruction and an explicit
degradation report instead of a silently implied check.

**haex-hive never installs a provider.** Installing Docker or podman means root, a daemon, groups and kernel modules. That is categorically different from writing files into a repository and would break the project's own model (Principle II, and the sidecar/review-gate philosophy). Every package manager has this boundary: npm needs node, cargo needs rustup, nix needs the Nix installer. haex-hive's boundary is `requires`.

The recommended layering resolves the bootstrap regress with one global prerequisite:

```
nix (the only global prerequisite)
  └─ nix develop      → provides the docker/podman CLI, mise, just
       └─ <container> → provides Android SDK, NDK, Rust, Tauri
```

Exactly one environment per project. Multiple named environments are not built on suspicion; a project that genuinely needs two is the occasion to extend the schema.

### Decision 3: consume foreign formats natively

Three formats are the inputs considered here: the [Agent Skills directory](https://github.com/agentskills/agentskills), Spec Kit's [`extension.yml`](https://github.com/github/spec-kit/blob/main/docs/reference/extensions.md), and [MCP server declarations](https://modelcontextprotocol.io/docs/concepts/architecture). haex-hive invents no competing format for any of them. **Sources verified 2026-09-03.**

What haex-hive owns is what none of them provide: composition across publishers, SHA pinning, transactional install with a lockfile and orphan deletion, cross-tool compilation, and deterministic activation.

A direct consequence for Spec 010: the adapter problem shrinks substantially. For the skill category, the client showcase already lists a large set of compatible tools, so an adapter needs to know the destination path, not a translation. Hooks and structured config remain genuinely per-tool. **Verified 2026-09-03.**

### Decision 4: the molecule manifest becomes optional

Requiring a publisher-authored `manifest.json` is the decisive adoption barrier for an open-source project: an arbitrary skills repository cannot be adopted even though its content is exactly right. This is a scope judgment, informed by the [Agent Skills repository format](https://github.com/agentskills/agentskills), verified 2026-09-03.

Adoption therefore detects by shape. A directory containing `SKILL.md` is a prose contribution with `activation: on-demand`, with no haex manifest. A directory containing `extension.yml` is a Spec Kit extension. `haex add <url>` works against any such repository, at a resolved full SHA, with a lockfile. The foreign formats and their documented entry files are verified against the [Agent Skills specification](https://github.com/agentskills/agentskills) and [Spec Kit extension reference](https://github.com/github/spec-kit/blob/main/docs/reference/extensions.md), both on 2026-09-03.

**Design input for the spec phase**, not a settled contract. The manifestless
adoption algorithm is deliberately narrow and reproducible:

1. Canonicalize the supplied repository URL with the existing D3 rules. A
   caller may supply a full SHA; otherwise `haex add` resolves the repository's
   default revision once and records the resulting full 40-hex SHA. Later
   installs never resolve a branch or tag again.
2. Discover only the repository root. Exactly one root `SKILL.md` or exactly
   one root `extension.yml` must exist; nested files are not implicitly
   adopted. A subdirectory can be selected explicitly in a later `haex add`
   extension, but it then becomes part of the selected path and is recorded in
   the lockfile. Both root files, neither file, or multiple explicit matches
   are deterministic refusals.
3. Set `selected_path` to the POSIX path of the discovered entry and preserve
   it in the lockfile. Set `kind` to `prose` for `SKILL.md` and `extension` for
   `extension.yml`. `extension` is an ingress-only foreign-format discriminator;
   it is normalized before compilation and is never a fifth internal payload
   kind.
4. Derive `molecule_id` as
   `com.haex.adopted.<lowercase-sha256(canonical-source)[:24]>` and
   `atom_id` as
   `molecule_id.<kind>.<lowercase-sha256(selected-path)[:16]>`. These IDs use
   only the AtomId grammar and therefore do not depend on a display name or a
   mutable repository branch.
5. Record `source`, the resolved `revision`, `selected_path`, `kind`,
   `molecule_id`, and `atom_id` in the lockfile. The same canonical URL,
   commit SHA, and selected path therefore produce the same identity and
   provenance on every device. Publisher authenticity remains an operator
   trust decision as described under Decision 11.

A manifest is required only for what the foreign formats cannot express: composition, hooks, activation policy other than the format's default, and binding strength.

This inverts the value proposition. Instead of "write a haex-hive manifest to participate", it becomes "everything that already exists is adoptable, pinned and reproducible, which `npx skills add` cannot do".

### Decision 5: haex-hive's own molecules are valid Agent Skills directories

Because the Agent Skills spec reserves `metadata` for third-party keys, a haex-hive molecule can be a valid `SKILL.md` directory carrying a sibling `haex.json` for the structured parts a flat string map cannot hold.

Consequence: haex-hive molecules function in all skills-compatible tools without haex-hive installed. Operators who have haex-hive additionally get pinning, composition and deterministic activation. There is no lock-in, which for an open-source project is the strongest available adoption argument.

### Decision 6: collapse the category map to four payload kinds plus an activation policy

The current categories (`constitution`, `spec`, `rules`, `hooks`, `skills`, `workflow`, and the planned `instructions`) differ along only two axes: what the payload is, and when it activates. Five of the seven are prose.

```json
{
  "haex_molecule_version": "1",
  "atoms": {
    "prose": [
      { "path": "constitution.md", "activation": "always",     "binding": "non-negotiable" },
      { "path": "style.md",        "activation": "glob",       "globs": ["**/*.rs"] },
      { "path": "skills/tdd/",     "activation": "on-demand" }
    ],
    "agent": [ { "path": "agents/implementer.md" } ],
    "hooks": [ { "path": "hooks/verify_env.py", "event": "SessionStart", "timeout": 5 } ],
    "mcp":   [ { "name": "playwright", "command": "npx", "args": ["..."] } ]
  }
}
```

This object is a molecule-local `haex.json` v1 example; it is not the
consumer `.haex-hive.json` and it does not replace any Spec-007 v2 contract.
The publisher root `manifest.json` remains the Spec-007 boundary for declared
atoms. In the planned compiler, `haex.json` is an optional input beside a
foreign-format payload: each `prose` entry becomes an internal prose payload
record, each `agent` entry an agent record, each `hooks` entry a hook record,
and each `mcp` entry an MCP record. `activation`, `binding`, `event`,
`timeout`, and command arguments are carried through unchanged. The compiler
then maps those internal records to target-specific files; it does not pretend
that the four kinds are existing `contributes.*` fields in the Spec-007 v2
schema. The next schema revision must define the publisher-side representation
and a migration from this molecule-local v1 before implementation.

Manifestless Spec Kit adoption performs the same normalization before the
compiler: the `extension.yml` record is an ingress record with `kind: extension`,
its instruction and documentation entries become internal `prose` records, and
each explicitly declared lifecycle hook becomes an internal `hooks` record.
The compiler consumes only those normalized records; an extension field with no
defined mapping is a deterministic refusal rather than an unconsumable lock
record.

The constitution stops being a magic category name and becomes what it actually is: prose that always applies with non-negotiable binding. The review gate attaches to `binding: non-negotiable`, which states the reason it exists.

`agent` is a subagent definition and is structurally close to a skill: frontmatter carrying name, description, tools and model, with the body as system prompt. Claude Code materialises these at `.claude/agents/*.md`.

Whether "workflow" survives as a payload kind or becomes an attribute on a prose contribution is left to the spec phase; Spec 011's one-per-repository rule needs some marker either way.

### Decision 7: activation is declared intent; the compiler picks the strongest available mechanism and reports degradation

This answers the question the session opened with. Skills and hooks are not alternatives. **Hooks are what make skills deterministic, and that is exactly the gap the Agent Skills standard leaves open.** The standard has no way to express "this always applies"; activation there is implicitly and always model-discretionary. haex-hive can supply it, because it compiles per tool.

| Declared activation | Claude Code | Cursor | Tool without hooks | Tool without skills |
|---|---|---|---|---|
| `always` | `CLAUDE.md` | `alwaysApply` rule | `AGENTS.md` | `AGENTS.md` |
| `glob` | PreToolUse hook | native glob rule | prose (degraded) | prose |
| `on-demand` | `.claude/skills/` | Cursor skills | skill directory | prose section |
| `on-event` | `settings.json` hooks | degraded | degraded | degraded |
| `agent` payload | `.claude/agents/` | native equivalent | prose, sequential (degraded) | prose |

Two rules keep this honest rather than overstated:

1. **Degradation must be reported.** `haex install` emits, for example, `hook verify_env (SessionStart): unsupported by codex, degraded to prose note in AGENTS.md`. Agent-agnostic does not mean equally strong everywhere; it means the strongest available mechanism, with the operator told where the guarantee weakens. Silent degradation would also conflict with Principle VIII.
2. **`activation: always` on a skill-format payload has a bounded guarantee.** Where the target supports `SessionStart`, compilation produces the skill directory and a hook whose output contains the same canonical reference block on every session start: atom ID, source URL, pinned revision, and selected path in the defined field order. This guarantees deterministic context injection; it does not claim that the target loads, follows, or enforces the referenced skill. On a target without hooks, compilation produces only the documented prose note and reports the degradation; the deterministic session-start guarantee does not apply there.

### Decision 8: subagent delegation is opt-in per workflow step, never automatic

The `agent` payload kind declares *availability*. Whether a given workflow step delegates to a subagent is declared by that step, and the default is sequential execution in the running session.

Rationale: delegation is not uniformly beneficial. It pays when the task is independent, the result is small relative to the work performed, and the exploration would otherwise pollute the orchestrator's context: search, research, independent implementation tasks, reviews. It costs when a step builds directly on the previous step's reasoning, because a fresh subagent re-reads the artifacts but not the deliberation that produced them. In a Spec Kit loop that makes `implement` the strong case and `specify → plan → tasks` the weak one.

A separate, more ambitious option is recorded but not adopted: an MCP server that spawns and drives ACP agents would give any MCP-capable orchestrator agent-agnostic subagents, so that a Claude Code orchestrator could delegate to Gemini CLI or Codex. It is local-only, needs no transport or identity plane, and would ship as an `mcp` payload in a molecule. If built, it belongs in a separate repository (working name `haex-acp-bridge`), not in the haex-hive core, and the token-cost caveat above applies more strongly, not less.

### Decision 9: drop the multi-source LLM constitution merge

A repository adopts exactly one prose atom with `binding: non-negotiable`, mirroring Spec 011's one-workflow-per-repository rule. `.haex-hive/constitution.md` is a byte-for-byte copy of that atom's source; two non-negotiable prose atoms are a refusal. Any number of `binding: recommended` prose atoms are permitted; they land in `CLAUDE.md` / `AGENTS.md`, not in the constitution. An operator who wants a reconciled document produces it themselves and adopts the result as a single-source molecule. See [ADR 0010](../adr/0010-drop-multi-source-llm-constitution-merge.md).

The decisive argument is not code volume but reachability: **an install that can prompt is not automatable.** Interactive assembly requires a device with model access and an operator at a terminal, which contradicts both the offline goal (Decision 2's motivation) and ecosystem integration (Decision 10). See [ADR 0010](../adr/0010-drop-multi-source-llm-constitution-merge.md).

### Decision 10: integration readiness is a deliverable, in both directions

The operator's goal is that haex-hive both integrates the existing ecosystem and can be integrated by it. Decisions 3, 4 and 5 cover the inbound direction. The outbound direction needs four things, three of them small:

| Item | Why |
|---|---|
| `haex install --json` | machine-readable result including the Decision 7 degradation report, so an orchestrator knows what it actually got |
| exit codes as contract | `util/exit_codes.py` exists; it needs to become a documented, stable surface |
| non-interactive install | delivered by Decision 9 |
| handoff manifest | delivered by Decision 1, so a delegating side can send the pin |

Concretely, integration with Buzz then reduces to: a Buzz workflow trigger runs `haex install` at the handed-off pin on the target device before `buzz-acp` starts the agent. No haex-hive-side transport code.

**Design input for the spec phase**, not a settled contract; the authoritative
version belongs in the Spec 008 install CLI contract.

The machine-readable result is a versioned `haex-install-result-v1` JSON
document written as one LF-terminated UTF-8 object to stdout when
`--json` is supplied. Its stable shape is:

```json
{
  "schema": "haex-install-result-v1",
  "status": "installed",
  "exit_code": 0,
  "generation": "<generation-id-or-null>",
  "degradations": [
    {
      "kind": "hook",
      "id": "verify_env",
      "event": "SessionStart",
      "target": "codex",
      "fallback": "prose",
      "reason": "target does not support hooks"
    }
  ],
  "error": null
}
```

`status` is one of `installed`, `no_changes`, or `refused`; `generation` is
the published generation ID for the first two and `null` for `refused`.
`degradations` is always present, sorted by `(target, kind, id, event)`, and
contains only observable capability losses. Each degradation entry is an
object with exactly these non-empty string fields: `target`, `kind`, `id`,
`event`, `fallback`, and `reason`. `fallback` names the weaker mechanism that
was installed, and `reason` explains the unsupported capability; neither may
contain secret values. `error` is `null` on success and
is `{ "key": <diagnostic-key>, "message": <safe-message> }` on refusal;
messages never contain secret values. Unknown fields are rejected by the
versioned result schema, so a future incompatible shape requires a new schema
name. Human-readable output remains the default when `--json` is absent.

The exit-code contract is: 0 for `installed` or `no_changes` (including
reported degradations), 2 for manifest/input or resolution refusal, 3 for
unavailable local content, 4 for validation refusal, 5 for system or declared
environment-requirement refusal, 6 for post-write integrity failure, 7 for
an unrecoverable/incomplete transaction, 8 for a Principle-VIII refusal, 9
for a busy writer, and 10 for a Principle-I plaintext-secret refusal. Usage
errors use 64. A missing `requires` provider is a refusal with exit 5; it is
not a warning. An unsupported optional hook is a successful install with a
degradation entry. The same table, including precedence, is normative in the
[Spec 008 install CLI contract](../../specs/008-install-transaction/contracts/haex-install.cli.md).

Integration readiness is not complete until both contracts and their golden
JSON/exit-code acceptance cases are implemented and tested.

Publication follows from Decision 5: haex-hive's own molecules are valid Agent Skills directories and can be listed on `agentskills.io`; workflow molecules can be submitted to the Spec Kit community catalog.

### Decision 11: recalibrate Spec 009 to the actual trust model

Spec 009's current requirements (cgroup v2 subtrees, Windows Job Objects, `openat2`-based TOCTOU closure, descendant reaping with session-leader tests) are multi-tenant hardening against hostile publishers. The document already concedes that containment is advisory, because hooks run under the operator's own account with no OS-level sandbox.

The actual trust model is explicit: the operator deliberately trusts the
selected publisher and the exact source at the selected SHA, just as they
would trust a dependency or workflow they choose to run. A full SHA provides
immutability and reproducibility, not publisher authenticity and not runtime
safety. A malicious or compromised trusted publisher is therefore out of
scope for this phase; operators needing protection from one must add external
signing, review, sandboxing, or a separate containment layer. **This trust
boundary was reviewed 2026-09-03.**

Recommendation: retain subprocess isolation, the timeout contract and the environment allow-list. Defer platform-specific containment and no-follow TOCTOU machinery until a concrete hostile-publisher scenario exists, and state the trust model plainly in the README instead.

## 4. Consequences for specs in flight

| Spec | Effect |
|---|---|
| 007 | The `contributes`/`atoms` category map is restructured per Decision 6. Multi-source assembly changes per Decision 9. The v3 rename in Spec 013 should carry the new shape rather than the seven-category one. |
| 008 | Transaction primitives landed and support Decisions 3, 4 and 10. Its install CLI contract is amended by Decision 9 (removal of `--llm` and `--accept-merged`). Decision 10's `--json` output and exit-code table are design input for the spec revision, not a settled amendment. |
| 009 | Recalibrate per Decision 11 before drafting. |
| 010 | Adapter surface shrinks for skills, stays per-tool for hooks and structured config. Add degradation reporting (Decision 7), the `agent` payload kind (Decision 6) and `--json` output (Decision 10). Replace the proposed `contributes.*` extension list with the collapsed model. |
| 011 | **Affected.** FR-004 mandates the review-gated `--llm=file` / `--accept-merged` flow and its User Story 1 test invokes both; Decision 9 retires them, so FR-004 and that test need rewriting. Under the one-non-negotiable-prose rule the workflow constitution fragment becomes `binding: recommended` prose and lands in `CLAUDE.md` / `AGENTS.md`, not in `.haex-hive/constitution.md`; the `## Workflow-Contributed Rules` section moves with it. Also gains per-step delegation declaration (Decision 8). Whether "workflow" survives as a payload kind is a Decision 6 follow-up. |
| 013 | Gains the manifest-optional adoption path from Decision 4: `haex add` must accept a plain skills repository and a Spec Kit extension repository, not only a haex-hive publisher. |

## 5. Explicitly rejected alternatives

- **Model everything as a skill, including hooks.** Rejected. It conflates packaging with activation. The skill directory is a good container; skill *loading* is model-discretionary and cannot express deterministic activation, which is the thing haex-hive uniquely provides.
- **Build an agent-agnostic Remote Control inside haex-hive.** Rejected per Decision 1. The ACP-over-Nostr architecture is sound but is a second product, is duplicated by Buzz, and would bridge an unfinished remote transport.
- **Fork Buzz.** Not rejected on merit, but out of scope: Buzz is an execution plane, and haex-hive composes with it rather than becoming it.
- **Resolve or install toolchains inside haex-hive.** Rejected per Decision 2. Duplicating `flake.lock` is strictly worse than delegating to it, and installing providers requires privileges that contradict the project's own write model.
- **A `mode` enum on the `environment` block.** Rejected as vocabulary that must be learned without explaining anything. The presence of `exec_prefix` carries the same information.
- **Adopt `npx skills add` semantics.** Rejected: no pinning, violating Principle IV. haex-hive consumes the same repositories at a full SHA instead.
- **Automatic subagent delegation for every workflow step.** Rejected per Decision 8.
- **Percent-encoded, length-framed provenance blocks in the assembled constitution.** Introduced during PR 59 review, reverted here. Nothing reads the framing back, so it was a wire format for a parser that does not exist, and it contradicted Spec 011's landed `### From molecule` byline. See ADR 0010.
- **Multiple named environments per project.** Deferred until a real case demands it.

## 6. Open questions

1. Does "workflow" remain a payload kind after Decision 6, or become an attribute on a prose contribution?
2. Where does the Spec Kit extension format sit: a fifth payload kind, or a foreign format the installer translates into the four existing ones?
3. What is the minimum viable adapter set, given that skills are portable by format and only hooks, structured config and `agent` payloads remain per-tool?
4. Should `requires` failures refuse the install outright, or warn and let the compiled prose carry the instruction? Refusal is safer; warning keeps `haex install` usable on a machine that only edits configuration. PR 59 review answered this as an unconditional exit-5 refusal in Decision 2 and Decision 10; that answer is recorded but not adopted, because it is the operator's call and was reopened in this follow-up.
5. Does the handoff manifest (Decision 1) warrant its own spec slot, or does it belong inside Spec 010's compiler output?
