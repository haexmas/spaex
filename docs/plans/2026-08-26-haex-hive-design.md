# haex-hive — Design

Date: 2026-08-26
Status: Historical (2026-09-21). Brainstormed 2026-08-26, not maintained as a live plan. The daemon, Nostr and mobile-control vision was retired by Decision 1 of the [Scope Realignment (2026-09-03)](2026-09-03-scope-realignment-design.md), and the project was renamed to spaex ([Spec 014](2026-09-07-rename-to-spaex-design.md), 4.0.0). Phases 0 and 1 shipped as Specs 001-005; Phase 2 (harness registry and multi-tool compiler) was reshaped and is realized by Specs 007, 008, 013 and 023. The current sequence lives in the [Composition UI & Skills Externalization Roadmap](2026-09-08-composition-ui-and-skills-externalization-roadmap.md).

## Problem

A personal, cross-device AI-assisted development setup:

- Work on multiple satellite machines (laptop, PC, different OSes) with familiar tools
  (VSCode, GitHub/GitLab CLI, terminal, Claude Code / Codex / Gemini CLI).
- From mobile: see the current status of projects/agent sessions, and give a running or
  new agent session instructions ("fix the pipeline", "build feature X").
- Work spans multiple git accounts/orgs simultaneously (private + professional,
  multiple GitHub/GitLab identities) — existing tools (OpenHands) force a single
  account/repo, which doesn't fit.
- Need layered, reusable behavioral/permission configs ("harnesses") — a thin global
  layer that always applies, plus flexible groupings (not necessarily git- or
  account-bound), plus per-project overrides.
- Harnesses must be usable across multiple agent CLIs (Claude Code, Codex, Gemini,
  Qwen, ...), not locked to one tool.
- Each satellite must be able to work fully autonomously (including with local AI
  models) — no hard dependency on any central server for actual work.
- Want a "hive mind": session continuity and recall across devices, not limited to
  code/git projects (e.g. resuming a pure research/brainstorm session on another
  device).

## Prior art considered

- **OpenHands** — closest existing fit, but single git account/repo only. Doesn't
  support the multi-account, multi-repo workflow this needs.
- **Buzz** (block/buzz) — self-hosted Slack/Discord-like workspace on a Nostr relay,
  humans + agents in shared channels, git-patches-as-events (NIP-34), agent harnesses
  via ACP (Goose/Codex/Claude Code), mobile clients still early. Chat-and-approval
  centric rather than IDE/session centric. **Adopted idea: Nostr as the relay
  protocol** (see below).
- **Hermes Agent** (NousResearch) — single always-on gateway process fronting
  Telegram/Discord/Slack/WhatsApp/Signal/CLI, pluggable execution backends
  (local/Docker/SSH/Modal/Daytona), works with local models, cron scheduler, MCP,
  persistent memory with FTS5 search, autonomous skill creation from experience.
  One central gateway + one memory store — doesn't fit the "autonomous peer
  satellites" requirement. **Adopted idea: post-session reflection that distills
  lessons into reusable skills** (see Self-Learning below).
- **secana-specs** (itemis, internal) — the team's existing dev harness: a git repo
  with a `devenv.sh`/`devenv.ps1` bootstrap that clones an allow-listed set of repos
  into one working directory, `CLAUDE.md` importing `.specify/memory/constitution.md`
  (spec-kit), deny-listed sub-repos requiring a separately-rooted session, and a
  `harness-evaluator`/`evals` setup that tests the harness itself. Confirms the
  registry/manifest approach for group membership. Claude-Code-specific (not
  multi-tool). **Decision: referenced as an external, unmodified harness group — not
  ported or rewritten.**
- **Plan v3** (`LLM_AGNOSTIC_SPECKIT_MULTI_REPO_PLAN_v3.md`, an earlier
  planning document by the same author, dated 2026-08-19) — spec-kit-driven,
  git-only, one always-on remote
  VM for mobile access (OpenHands as pure execution trigger, not source of truth).
  Solves the original multi-repo/multi-account problem with a much simpler
  architecture than haex-hive (no relay, no daemon, no capability routing). Its
  cross-repo reference mechanism (`spec-ref.yaml` + `spec-resolve` tool) is more
  mature than what was drafted here initially. **Decision: adopt Plan v3's
  cross-repo reference mechanism, revision pinning, per-repo opt-in allowlist, and
  incremental phasing discipline** (see "Adopted from Plan v3" below). Explicitly
  **not adopted**: Plan v3's "conversation state is disposable, git is the only sync"
  stance (haex-hive deliberately keeps cross-device session continuity as a goal),
  its OpenHands-as-single-remote-VM model (haex-hive requires autonomous multi-
  satellite execution incl. local AI), and its Impact-Map/Contracts/Workstreams
  layer (only applies to enterprise multi-service systems where one feature spans
  many repos — the personal use case here is multiple unrelated repos sharing
  conventions, not contracts).
- **earendil-works/pi** — a replacement agent runtime (own multi-provider LLM API,
  own agent core, own CLI), not a compatibility shim over Claude Code/Codex/Gemini.
  No built-in permission system. Would mean replacing the daily-driver tools rather
  than harnessing them. **Decision: not adopted.**
- **haex-vault / haex-sync-server / haex-ucan / haex-claude-proxy** (own existing
  ecosystem) — local-first, E2E-encrypted, CRDT-synced multi-device platform with
  capability-based auth, already has a Claude-CLI-wrapping proxy. Structurally the
  same problem as the hive-memory sync and secrets-sync pieces here.
  **Decision: haex-hive is built as an independent project, not a Haex Space module.
  Secrets and hive-memory sync are built fresh rather than reusing haex-vault,
  despite the overlap** (explicit trade-off, see Secrets and Hive Memory sections).
- **Claude Code's own Remote Control / cloud sessions / push notifications / cron
  routines** — Anthropic already ships cross-device session control and always-on
  cloud execution, but only for Claude Code. **Decision: mobile control in haex-hive
  must be agent-agnostic (Claude Code, Codex, Gemini, ...), so this is not relied on
  as the control plane, even though it overlaps.**

## Architecture

Two independent planes:

1. **Config plane** (harness definitions, credentials-by-reference, permissions) —
   pure git, pull-based, works fully offline. No relay dependency.
2. **Liveness plane** (status, commands, session continuity) — a self-hosted Nostr
   relay. Requires the relay to be reachable by both ends, but its unavailability
   never blocks local work — only mobile visibility/control pauses.

```
┌─────────────┐   git push/pull    ┌──────────────────────┐
│harness repo │◄──────────────────►│ satellite (laptop A)  │
│(registry,   │                    │  - harness-daemon      │
│ groups,     │                    │  - compiles config →   │
│ global)     │                    │    CLAUDE.md/AGENTS.md/│
└─────────────┘                    │    GEMINI.md/settings  │
      ▲                            │  - runs agent CLIs     │
      │ references (unmodified)    │    locally, autonomous │
┌─────┴──────┐                     └──────────┬─────────────┘
│secana-specs │                               │ nostr events
│(external,   │                               │ (status, session
│ read-only)  │                               │  refs, commands)
└─────────────┘                               ▼
      ┌─────────────┐              ┌──────────────────────┐
      │ satellite B  │◄──nostr─────┤ self-hosted Nostr relay│
      │ (same daemon)│   events    │  (strfry/nostr-rs-relay)│
      └──────────────┘             │  + Blossom blob store  │
                                    └──────────┬─────────────┘
                                               ▼
                                    ┌──────────────────────┐
                                    │ mobile app — status,  │
                                    │ instruct, recall hive │
                                    │ memory                │
                                    └──────────────────────┘
```

Commands are not mobile-specific: any authorized identity (mobile, or another
satellite) can address any registered satellite over the relay. This is what lets
device A trigger heavy work on device B's hardware (e.g. GPU) for free, without a
separate mechanism.

## Harness / Config Layer

Repo shape:

```
harness-registry/              (private root git repo)
  registry.yaml                 # project-identity → group(s) mapping
  global/
    instructions.md             # thin, always applies
    permissions.base.yaml
  groups/
    private-oss/
      instructions.md
      permissions.yaml
      mcp-servers.yaml
      identity: personal-github  (alias, not a secret)
      external_sources:
        allowed: []              # this group inherits no external spec sources
    experiments/
      ...
  external-groups.yaml
    - name: itemis-secana
      repo: gitlab.com/itemis/solutions/secana-specs
      identity: work-gitlab
      mode: unmodified            # cloned/updated, never compiled/rewritten
```

Each consuming project may carry a `.specify/system.yaml` opt-in file whose
`external_sources.allowed` allowlist names the external harness repos it is
permitted to resolve — **without such a file, or with an empty allowlist, no
external harness is loaded, ever**, regardless of what the registry says. The
registry describes availability; the per-project file grants use. This is a
security/trust boundary, not just convention: a private repo dropped anywhere on
disk stays isolated by default.

**Project identity is device-independent, and never carries a raw filesystem path:**
- Git-backed project → identity = git remote URL. Identical on Windows and Linux
  regardless of local clone path.
- Non-git, folder-only project → a small opaque id (`.harness-id`) dropped in the
  folder once, carried along when copied. Only carries identity, not group
  membership (that stays entirely in `registry.yaml`).

`registry.yaml` maps `project-identity → group(s)` and is identical on every
device. Each satellite daemon keeps its own **local, unsynced** table of
`project-identity → local path on this machine`. Raw paths never cross a device
boundary; where a specific device's copy needs to be addressed (routing, resuming),
the unit is `(device-pubkey, project-identity)`, never a path.

**Compiler**: for own groups, resolves `global + group(s) + project override`
(later layers win, arrays merge) into an effective spec, then produces per-tool
output:
- Pure-instruction files (CLAUDE.md/AGENTS.md/GEMINI.md) are **symlinked** to the
  compiled canonical file — filesystem-level pointer, no per-tool import-syntax
  dependency, zero drift risk. (Needs Developer Mode/admin for symlinks on Windows.)
- Permissions/MCP-server config (`settings.json`, `config.toml`, ...) are
  structurally incompatible formats between tools, so these are genuinely
  **compiled**, not symlinked — but always generated from the one canonical YAML,
  never hand-edited per tool.

External groups (e.g. secana-specs) are cloned and used exactly as their owning
team maintains them; only the *identity* used to clone them comes from this system.

### Cross-repo spec references (adopted from Plan v3)

Where a project's harness pulls in a specific document from an external harness
repo (e.g. a group instruction file, a specific spec), the reference format is:

```yaml
# specs/<feature>/spec-ref.yaml
repository: itemis/solutions/pltf/secana-specs
revision: 7ae4c218e140       # full commit SHA — immutable, mandatory
path: .specify/memory/constitution.md
```

**Revision pinning is non-negotiable**, part of the constitution (see below).
Branches are not the normal case — a satellite resolving a spec on Monday and
another satellite resolving on Wednesday must see byte-identical content.

A small `spec-resolve` tool handles resolution and works directly against git
objects (`git show <sha>:<path>`), so a full working clone of the external repo
is not required. Default is a managed cache under the OS's standard cache
directory; developers actively working on the external repo may opt into a
local-clone mapping that is never versioned.

This replaces the earlier symlink-only + per-device-path-table approach for
external references — it's more reproducible (SHA-pinned), cleaner across OSes
(no Windows symlink permission dance for cross-repo references), and works
without a full clone. Symlinks remain the mechanism only for the daemon's own
compiled outputs (per-tool CLAUDE.md/AGENTS.md/GEMINI.md) inside a *single* repo.

### Delivery model: three orthogonal instruction layers (as implemented, spec 003+)

The delivery model that actually landed via spec 003 has three orthogonal
layers, each with its own scope, load mechanism, and enforceability. This
subsection describes what a session working in an opted-in repo actually
sees — a refinement of the registry/groups design above, not a replacement.

#### Layer 1 — Repo constitution (NON-NEGOTIABLE)

- **Where**: `.specify/memory/constitution.md` in the opted-in repo.
- **Reference**: pinned by `.haex-hive.json`'s `constitution` block with
  `repository + revision + path` per Principle IV.
- **Loaded by**: session start, via the operator's global detection snippet
  (see `specs/003-config-file-based-delivery/contracts/global-snippet.contract.md`).
- **Scope**: universal to any session working in the opted-in repo.
- **Enforceability**: NON-NEGOTIABLE. Session refuses on violation per
  Snippet Step 5. Conflict-pass in Snippet Step 4 raises any repo-local
  rule that contradicts a constitutional principle to the operator with
  both sides quoted verbatim.
- **Sharing**: everyone who clones the opted-in repo gets the constitution.

#### Layer 2 — Repo-local instructions (SHOULD, additive)

- **Where**: `CLAUDE.md` / `AGENTS.md` at the repo root, plus any other
  convention paths the specific CLI reads natively.
- **Reference**: no explicit `.haex-hive.json` entry needed — the layer is
  discovered by file presence.
- **Loaded by**: session start, per Snippet Step 3. Applied additively,
  never as a replacement for the constitution.
- **Scope**: the specific repo — the repo owner's project-specific rules
  for anyone contributing to that repo.
- **Enforceability**: SHOULD-level. Direct contradictions with
  constitutional principles are surfaced via Step 4; contradictions on
  non-principle matters just merge additively. No automatic refusal.
- **Sharing**: everyone who clones the repo gets these files.

#### Layer 3 — Operator personal config (SHOULD, per-operator)

- **Where**: the operator's user-level CLI instruction file (Claude Code's
  `CLAUDE.md` under its config directory; Codex CLI's `AGENTS.md` under
  `$CODEX_HOME`).
- **Reference**: the CLI's native mechanism; no haex-hive reference needed.
- **Loaded by**: session start, natively by the CLI in every session that
  operator runs — in any repo, opted-in or not.
- **Scope**: the operator, not the repo. Other developers on the same repo
  see none of this.
- **Enforceability**: SHOULD-level guidance, deviation-with-operator-
  approval. Personal workflow preferences (worktree discipline, tool
  integrations, formatting conventions) live here.
- **Sharing**: two patterns work today:
  - **Copy-paste**: manually move the file between devices. Simplest, no
    infrastructure.
  - **Personal config repo**: keep the file in a per-operator git repo
    (e.g. `github.com/<op>/haex-personal-config`), symlink the CLI's
    global-instructions path to a checkout in that repo, sync devices via
    `git pull`. Other developers wanting to inspect or borrow the workflow
    clone the repo. Sharing is git — no haex-hive-specific mechanism
    required.

#### Rule-tagging convention (recommended for layers 2 and 3)

Since layers 2 and 3 are both SHOULD-level, rules within them benefit from
explicit enforcement tags so a session knows what to do on ambiguity:

- **HARD_STOP** — refuse to violate, cite the rule. Rare in layers 2/3;
  usually means the operator has folded a constitutional-adjacent principle
  into their personal or repo-local config.
- **EXPECTED** — do it by default. If the operator explicitly asks to skip
  ("commit without the changelog line this once"), skip after acknowledging
  the deviation in the response.
- **SHOULD** — do it unless there's a specific reason not to. Session may
  ask "convention says X, do you want that here?" for low-friction cases,
  or just proceed and note the deviation in a summary.

The constitution's principles are all HARD_STOP by definition (that's what
NON-NEGOTIABLE means). Repo-local and personal rules pick their own tag
per rule.

#### Why this shape

- **Constitution stays universal.** haex-hive-the-project ships one
  canonical constitution. Adding personal workflow rules into it would
  force those on every contributor to every haex-hive-opted-in project —
  which is exactly the "committed CLAUDE.md commandeers repo-local
  instructions" anti-pattern spec 003 was written to retire.
- **Repo owners keep control of their repo.** Repo-local `CLAUDE.md` /
  `AGENTS.md` are the repo owner's territory. The harness respects them
  additively.
- **Operators keep control of their sessions.** Personal workflow rules
  do not leak into any repo unless the operator deliberately commits them.
  Cross-device sync of personal rules is a git problem, not a haex-hive
  problem.
- **Sharing is git.** Every layer is either in a git repo or trivially
  put into one. Sharing = point at `repository + revision + path` per
  Principle IV. No haex-hive-specific sharing mechanism needed.

## Execution & Dev Environment

- Every satellite runs the same daemon: watches the harness repo, compiles configs,
  launches/wraps agent CLI processes, publishes/subscribes to the relay.
- **Dev environment provisioning is Nix-first**: each project's harness references a
  Nix flake as the canonical, reproducible environment definition (compilers,
  libraries, package managers). A prebuilt container image is a narrow fallback for
  the rare project where Nix doesn't fit well — not a fully parallel devcontainer
  system.
- **Platform support**: Nix runs natively on Linux and macOS. It has no native
  Windows port — on Windows it requires **WSL2**. This means a Windows satellite's
  daemon runs as a Linux process inside WSL2, not as a native Windows process
  (pairs fine with VSCode's Remote-WSL support, so "familiar tools" still holds).
  Bare-Windows-without-WSL2 is not a supported satellite target for Nix-based
  projects — the container fallback is the only option there.
- **Capability tags**: satellites advertise capabilities (e.g. `gpu`, `android-sdk`)
  in their relay status events. Commands can target a specific satellite explicitly,
  or request "any satellite with capability X" — needed both for hardware routing
  and for picking a satellite actually able to run a given project.

## Secrets

The harness repo (git) only ever contains **references** to identities (e.g.
`identity: work-github`), never secret material.

- **Store**: OS keychain per device, never ambiently synced. Each satellite is
  provisioned once with the credentials it needs; nothing leaves a device by
  default.
- **Provisioning/rotation transport**: the Nostr relay, used narrowly — NIP-44
  (ECDH-derived, pubkey-to-pubkey encryption) to push a new/rotated secret to a
  specific device's pubkey, using ephemeral events or relay-side deletion after
  delivery so it isn't retained. This is a one-shot delivery pipe, not an always-on
  synced store — the relay must not become a place where secrets sit long-term
  (harvest-now-decrypt-later risk), and each device's Nostr identity key is itself a
  secret requiring the same keychain protection.
- Reusing haex-vault for this was considered and explicitly declined, in favor of
  keeping haex-hive fully independent — a deliberate trade-off, not an oversight.

## Relay & Hive Memory

- Self-hosted Nostr relay (strfry/nostr-rs-relay), single-tenant, not the public
  social graph.
- Event kinds: `status` (satellite heartbeat/capabilities/current work), `command`
  (instruction, targeted by device-pubkey or capability), `session-ref` (pointer to
  a transcript), plus the narrow secrets-provisioning events above.
- Bulky content (full session transcripts) goes through **Blossom** blob storage;
  events themselves stay small (references/summaries), matching how Buzz already
  uses this pairing.
- **Hive memory serves two distinct needs**, not one:
  - *Resume exactly where I left off* on another device → needs the **raw
    transcript** (Blossom).
  - *Recall what happened/was decided* across sessions → needs something
    **queryable**, not just replayable. Transcripts are ingested into a
    **graphify** knowledge graph (already used for codebase/doc graphs elsewhere)
    so recall works via `graphify query`/`path`/`explain` rather than re-reading raw
    logs.

## Self-Learning / Reflection

On session end, the daemon triggers a reflection pass over the transcript: extract
"what was the problem, what was the fix, is this reusable." The output is **not**
written into the knowledge graph (that's passive recall) — it's drafted as a diff
to the actual harness (a new/updated skill or instruction snippet), at project level
by default, promotable to group/global if broadly applicable.

The diff is **proposed, not auto-merged** — a real commit/PR against the harness
repo, surfaced for review (naturally via the mobile control channel: not just "give
instructions" but also "approve what the agent just learned"). Auto-merging was
considered and rejected: self-modifying instructions without a review gate will
drift — overfitting to one-off incidents, accumulating contradictions — the review
step is what keeps this signal instead of noise.

## Data Flow (example: mobile instructs a satellite)

1. Mobile publishes a signed `command` event (target = device-pubkey or
   `capability:gpu`, payload = "continue on project-id X: fix pipeline").
2. Relay delivers to matching satellite(s). An offline satellite misses it unless
   the relay retains that event kind long enough to catch up on reconnect (must be
   configured explicitly, not assumed).
3. Target daemon resolves `project-id → local path`, applies the compiled harness
   (Nix env, permissions, credentials from OS keychain), launches/resumes the agent
   CLI.
4. Daemon publishes periodic `status` events and, on completion, a `session-ref`
   pointing at the full transcript.
5. Mobile subscribes to status/session-ref events for that project and updates
   live.

## Error Handling

- Relay unreachable → satellites keep working locally; only mobile
  visibility/control pauses.
- Target satellite offline when commanded → not silently lost nor magically
  executed; on reconnect the daemon checks for missed commands within a bounded
  retention window, older ones are dropped with a notification rather than queued
  indefinitely.
- Two devices editing the harness registry concurrently → plain git merge conflict,
  surfaced normally.
- Agent crashes mid-session → status flips to `error` with last-known state;
  session-ref still points at the partial transcript.

## Testing

Mirror secana-specs' `harness-evaluator`/`evals` pattern:
- Evals asserting the compiler renders correct, valid output per target tool (e.g.
  does the compiled `.claude/settings.json` actually restrict what it should).
- Integration tests for the relay round-trip (publish command → daemon receives →
  status observable).

## Constitution (non-negotiable hard rules)

These are hard invariants of the system, not defaults. Every subsequent spec
must respect them; a change requires an explicit constitution amendment.

1. **No secrets in git, ever.** The harness repo carries only references to
   identities (aliases), never key material, tokens, passwords, or SSH keys.
2. **No local absolute filesystem paths in versioned harness configuration.**
   Anything committed must resolve identically on Linux, macOS, and WSL2.
   Cross-repo references use `repository + revision + repo-relative path`.
3. **Cross-repo spec references must pin an immutable Git revision** (full
   commit SHA). Branches are not the normal case.
4. **External harness sources are opt-in per project.** A project without an
   explicit `external_sources.allowed` entry gets nothing external — no
   implicit inheritance from sibling directories, sibling repos, or a global
   agent instruction file.
5. **Project identity is device-independent.** Raw filesystem paths never cross
   a device boundary — the addressable unit over the relay is `(device-pubkey,
   project-identity)`, never a path.
6. **Self-modifying instructions are always review-gated.** Reflection output
   is proposed as a diff/PR against the harness repo, never auto-merged.
7. **Relay-plane unavailability must never block local work.** Only mobile
   visibility/control pauses when the relay is unreachable; agent CLIs on
   satellites keep running against local disk.

## Phasing (execution order)

Build the simple thing that already works before the ambitious thing that
generalizes it. Phases are not optional — do not skip forward.

- **Phase 0 — One repo, cleanly harnessed.** Pick one existing repo (candidate:
  haex-vault or haex-ucan). Write its `CLAUDE.md`/`AGENTS.md` as thin adapters
  pointing at a canonical `.specify/memory/constitution.md`. Test Claude Code ↔
  Codex handoff purely through repository state (no conversation-history
  dependency). Acceptance: a fresh session in either tool reconstructs full
  context from the repo alone.
- **Phase 1 — Portable cross-repo references.** Implement `spec-ref.yaml` +
  `spec-resolve` tool + per-project allowlist. Test on Linux and macOS (WSL2
  deferred to when a Windows satellite is real). Acceptance: the same
  `spec-ref.yaml` resolves the identical revision on both OSes without local
  path configuration.
  _Status_: **v1 implemented and in daily use as of 2026-08-28** via
  Spec 004 + Spec 005; **v2 in design as of 2026-08-29** via Spec 007
  (unified manifest). Spec 004 landed the mechanism: `spec-resolve`
  tool at `.specify/scripts/spec-resolve`, unified `harness_sources`
  array in `.haex-hive.json`, canonical JSON Schema at
  `.specify/schemas/haex-hive.schema.json`, constitution v1.1.1. Spec 005
  landed the adoption path: `haex-init` CLI at
  `.specify/scripts/haex-init` scaffolds `.haex-hive.json` +
  schema mapping, patches operator-global config files inside a
  marker-wrapped block, and — via `--pin-constitution` — completes the
  self-ref flow after `/speckit-constitution`. Shell testsuite under
  `tests/haex-init/` covers fresh-operator, self-ref, external-ref,
  idempotency, marker-safety, version-upgrade, and format-regression
  paths. macOS cross-OS validation still deferred per Spec 004
  Assumptions; Linux is live. The Phase 1 mechanism is what Phase 2
  (harness registry + multi-tool compiler) now builds on. Public-URL
  `--fetch-latest`, `add-source`, multi-spec external-ref, and the
  granular publisher/consumer atom model are **Spec 007** territory
  (unified manifest v2). Spec 006 (multi-spec external-ref draft) is
  superseded by Spec 007. Spec 007 also retires the standalone
  `haex-init` binary in favour of `haex init` as a subcommand of the
  unified `haex` binary (see ADR 0008), and the constitution moves to
  v1.3.0 in step (ADR 0007).
- **Phase 2 — Harness registry + multi-tool compiler.** Central harness repo
  with global/groups/registry structure. Compiler emits per-tool artifacts
  (CLAUDE.md/AGENTS.md/GEMINI.md via symlink, settings.json/config.toml via
  compilation). Acceptance: adding a new project to the registry produces
  correct per-tool files on the next daemon run, no hand-editing.
- **Phase 3 — Nix-first dev environments** for the registered projects.
- **Phase 4 — Self-hosted Nostr relay + satellite daemon.** Status events only,
  no command routing yet. Acceptance: a phone can see which satellites are
  online and what they're currently doing.
- **Phase 5 — Command routing over the relay** (mobile → satellite,
  satellite → satellite for capability routing).
- **Phase 6 — Secrets provisioning via NIP-44** (one-shot encrypted transport
  to a new device, never long-lived storage on the relay).
- **Phase 7 — Hive memory** (Blossom transcripts + graphify ingestion) and
  **reflection pipeline** (session end → proposed harness diff, review-gated).

Everything through Phase 3 is Plan v3's original scope with the multi-tool
compiler added — the parts that solve the *original* problem. Phases 4–7 are
what haex-hive adds beyond Plan v3, and they are gated on the earlier phases
actually being in daily use first.

## Open Questions / Deferred

- Local-model support (via a 4th compiler target, e.g. pi, specifically for
  local/self-hosted models) — explicitly deferred, not designed in now.
- Exact reflection-agent prompt design and skill file format.
- Mobile app UI/UX design.
- Relay event retention/expiry policy specifics (how long to hold `command` and
  `status` events for offline-catch-up).
- Windows symlink permission handling (Developer Mode requirement) — needs
  verification as part of implementation, not just assumed to work.
- Windows satellites require WSL2 for the Nix-first execution path; whether that's
  an acceptable prerequisite to require, or whether Windows-without-WSL2 needs
  first-class container-based support rather than treating it as a narrow fallback,
  depends on how much real Windows-without-WSL2 usage actually happens.

### Spec 002 / Spec 003 follow-ups (opened 2026-08-27)

- **F-3: Are the 7-step global-snippet callouts load-bearing or decorative?**
  Spec 002 Phase 4 validation (all four fresh-CLI refusal runs) succeeded
  using only the OLD 5-step snippet — the strengthened constitution wording
  alone drove the correct refusal on Test 3.2a (Claude) and Test 3.2b (Codex
  x3). Steps 6-7 of the current reference snippet (V/VIII/checkbox-freshness
  callouts) were never exercised in the validation run. Options: (a) run an
  empirical A/B — deliberately weaken the constitution wording, verify the
  snippet callouts still drive the correct behavior; (b) simplify to 5
  steps if the empirical test says the callouts add no value; (c) accept
  belt-and-suspenders and keep 7 steps as insurance. Not urgent; revisit
  when Phase 4-7 mechanics need the snippet extended for other reasons.
- **F-VIII-restate: borderline FR-002 duplication in the Principle-VIII
  snippet callout.** The snippet contract's VIII callout shares the
  ~7-word phrase "emit output that instructs a downstream reader" with
  the constitution's Principle VIII body. Judged acceptable during Spec 002
  T025 review, but a future review could refactor the callout to a stricter
  gist. Low-risk, low-urgency.
- **F-Codex-ide-links: normalize Codex CLI IDE-integration markdown links
  when capturing outputs into versioned config.** Codex emits absolute-path
  IDE-integration links (`[file (line N)](<absolute-path>:N)`). Live
  emission is not a P-II violation; the capture-and-commit step is. Codified
  as a normalization pattern in `specs/002-.../.validation-runs/2026-08-27.md`
  §E.F-4. Future validation-run authors should apply the same normalization.
