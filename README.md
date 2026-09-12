# spaex — reproducible coding harnesses for any repo and development environment

**Status**: `4.1.0` (adds molecule install-hooks and the on-demand molecule store; see [Spec 016](specs/016-molecule-install-hooks/) and [Spec 017](specs/017-molecule-store/)). Portmanteau of `spec` and `haex`. See [docs/adr/0011-rename-to-spaex.md](docs/adr/0011-rename-to-spaex.md) for the rename decision and [specs/014-rename-to-spaex/](specs/014-rename-to-spaex/) for the full spec.

## What it is

spaex composes a coding harness for a single repo out of reusable pieces (skills, MCPs, constitutions, slash commands, dev-environment files, collectively "molecules"). You declare which molecules you want in `.spaex/manifest.json`. All spaex-owned project state lives under `.spaex/`; `spaex install` writes participating runtime files deterministically, pinned by SHA. Two consecutive `spaex install` runs on unchanged inputs produce byte-identical output.

## What you can do today

- `spaex add <source-url> <molecule-ids...>`: adopt one or more molecules from a publisher repo into `.spaex/manifest.json` and install them in one invocation.
- `spaex remove <molecule-ids...>`: retract one or more molecules from `.spaex/manifest.json` and re-run install (files that only the retracted molecule contributed are deleted).
- `spaex install`: publish adopted molecules atomically into their participating roots. Writes `.spaex/install.lock`.
- `spaex constitution show`: print the effective spaex constitution to stdout, assembled from adopted molecules per `install.lock`.

## Molecule install-hooks

A molecule may declare an optional `install_hook` in its `manifest.json`. `spaex install` invokes it as a normal subprocess (arbitrary code, consumer-user permissions, full environment inheritance) after any required atom materialization and before publishing the install.lock generation; hook-only molecules run without atom materialization. Per-molecule `on_failure: "abort" | "warn"` selects between transaction rollback and continue-with-`hook_status`-recorded. Consumers can opt out for a single invocation via `spaex install --no-install-hooks` (or `spaex add --no-install-hooks`). See [docs/install-hooks.md](docs/install-hooks.md) for the full contract: declaration schema, execution semantics, the four failure kinds, idempotency, non-reversibility, and the trust model.

## Atom-category conventions

The v4 molecule-manifest schema treats `atoms{}` as an open `Dict[str, List[str]]` map. Publishers pick category names by convention. Common categories today: `constitution`, `slash_commands`, `agents`, `mcps`.

**Environment-config files** (`flake.nix`, `Dockerfile`, `devcontainer.json`, `.envrc`, `shell.nix`, etc.) can be declared under any category name a publisher chooses. Spec 014 makes no naming commitment here; multi-environment vocabulary (dev/staging/prod), consumer-side selection, and orchestration verbs are the scope of Spec 015 (planned; see [docs/plans/2026-09-07-slot-015-multi-environment-placeholder.md](docs/plans/2026-09-07-slot-015-multi-environment-placeholder.md)).

## Install

**Once published to PyPI (upcoming with the `v4.1.0` tag):**

```bash
pipx install spaex
```

**From a local checkout (development):**

```bash
git clone https://github.com/haexmas/spaex.git
cd spaex
pip install -e '.[dev]'
```

Requires Python 3.10+ and Git 2.30+ on `$PATH`. Only runtime dependency is `jsonschema`.

After `spaex install` completes, `.spaex/install.lock` is present and byte-identical across two consecutive runs.

## The spaex vocabulary at a glance

- **Compound** (`.spaex/manifest.json.compounds[]`): a `(source, revision)` pair with a list of adopted `molecules[]`. The consumer's allowlist.
- **Molecule**: a published, reverse-DNS-identified bundle that a publisher declares in its root `manifest.json` under `molecules{}`.
- **Atom**: a single delivered file, grouped under a category key in a molecule's `manifest.json` `atoms{}` map.

This vocabulary (compounds -> molecules -> atoms) is the clean-cut spaex format. There is no migration command or legacy manifest fallback.

## Multi-device delegation

Not part of spaex. That is a separate project: [holzi](https://github.com/haexmas/holzi) (Nostr + iroh + MCP agent plane, single-user first). spaex is deliberately scoped to one repo, one device.

## Environment variable

`spaex` honors `$SPAEX_STATE` for the per-invocation publisher-clone state directory. Unset falls back to `~/.local/share/spaex/`.

## Documentation

- Every spec under [specs/](specs/) is authoritative for the mechanism it introduces.
- Design plans under [docs/plans/](docs/plans/) capture pre-spec requirements.
- Architecture Decision Records under [docs/adr/](docs/adr/) record decisions that reshape the system.
- The constitution at [.specify/memory/constitution.md](.specify/memory/constitution.md) is the non-negotiable invariant set every spec, plan, and implementation MUST respect.
