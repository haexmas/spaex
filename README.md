# spaex — reproducible coding harnesses for any repo and development environment

**Status**: `5.0.0` (external skills remain standard skill content, declared as structured `external_skills` metadata and installed through an explicit consumer-selected adapter, not a molecule hook; see [Spec 018](specs/018-skills-externalization/)). Portmanteau of `spec` and `haex`. See [docs/adr/0011-rename-to-spaex.md](docs/adr/0011-rename-to-spaex.md) for the rename decision and [specs/014-rename-to-spaex/](specs/014-rename-to-spaex/) for the full spec.

## What it is

spaex composes a coding harness for a single repo out of reusable pieces (MCPs, constitutions, slash commands, dev-environment files, and external skill references, collectively "molecules"). You declare which molecules you want in `.spaex/manifest.json`. All spaex-owned project state lives under `.spaex/`; `spaex install` writes participating runtime files deterministically, pinned by SHA. Two consecutive `spaex install` runs on unchanged inputs produce byte-identical output.

## What you can do today

- `spaex add <source-url> <molecule-ids...>`: adopt one or more molecules from a publisher repo into `.spaex/manifest.json` and install them in one invocation.
- `spaex remove <molecule-ids...>`: retract one or more molecules from `.spaex/manifest.json` and re-run install (files that only the retracted molecule contributed are deleted).
- `spaex install`: publish adopted molecules atomically into their participating roots. Writes `.spaex/install.lock`.
- `spaex constitution show`: print the effective spaex constitution to stdout, assembled from adopted molecules per `install.lock`.
- `spaex status`: summarize the repository's active composition — every pinned/installed molecule, what its atoms materialized into, the composed constitution, and any drift between the manifest, the install lock, and the constitution. Read-only.
- `spaex trace <path>`: print which molecule(s) wrote a given file, or every recorded file under a directory. Read-only.

## Molecule install-hooks

A molecule may declare an optional `install_hook` in its `manifest.json`. `spaex install` invokes it as a normal subprocess (arbitrary code, consumer-user permissions, full environment inheritance) after any required atom materialization and before publishing the install.lock generation; hook-only molecules run without atom materialization. Per-molecule `on_failure: "abort" | "warn"` selects between transaction rollback and continue-with-`hook_status`-recorded. Consumers can opt out for a single invocation via `spaex install --no-install-hooks` (or `spaex add --no-install-hooks`). See [docs/install-hooks.md](docs/install-hooks.md) for the full contract: declaration schema, execution semantics, the four failure kinds, idempotency, non-reversibility, and the trust model.

## Atom-category conventions

The v4 molecule-manifest schema treats `atoms{}` as an open `Dict[str, List[str]]` map. Publishers pick category names by convention. Common categories today: `behavior`, `slash_commands`, `agents`, `mcps`. The legacy `constitution` category remains readable for older molecules but is not the canonical way to contribute policy.

**Environment-config files** (`flake.nix`, `Dockerfile`, `devcontainer.json`, `.envrc`, `shell.nix`, etc.) can be declared under any category name a publisher chooses. The retired `skill` and `skills` categories are the one exception: a skill may still live in the publisher repository, but is declared as a structured `external_skills` reference and installed only through an explicit, consumer-selected adapter (`spaex skills install`), never a molecule `install_hook`. Spec 014 makes no other naming commitment here; multi-environment vocabulary (dev/staging/prod), consumer-side selection, and orchestration verbs are the scope of Spec 015 (planned; see [docs/plans/2026-09-07-slot-015-multi-environment-placeholder.md](docs/plans/2026-09-07-slot-015-multi-environment-placeholder.md)).

### Activating an adopted Nix devShell

A molecule that delivers `flake.nix`/`.envrc` under an environment-config
category (e.g. `com.github.haexmas.atoms.nix-devshell-base`) only writes
those files; it does not — and should not — provision Nix or direnv
themselves, since that needs interactive root access spaex should not
attempt unattended. Three preconditions are easy to miss on a fresh
machine after `spaex install`:

1. **Flakes must be enabled.** A default Nix install has `nix-command`
   and `flakes` behind the `experimental-features` flag — without it,
   `nix develop`/direnv's `use flake` fail with `experimental Nix
   feature 'nix-command' is disabled`. Enable it per-user, no root
   needed:

   ```bash
   mkdir -p ~/.config/nix
   echo "experimental-features = nix-command flakes" >> ~/.config/nix/nix.conf
   ```

2. **direnv itself must be installed** (Nix does not bring it in):
   `sudo pacman -S direnv`, `sudo apt install direnv`,
   `brew install direnv`, or `nix profile install nixpkgs#direnv`.

3. **direnv must be hooked into your shell**, then open a new shell:

   ```bash
   # bash (~/.bashrc) / zsh (~/.zshrc)
   eval "$(direnv hook bash)"   # or: zsh

   # fish (~/.config/fish/config.fish)
   direnv hook fish | source
   ```

With all three in place, `cd` into the consumer repo and run
`direnv allow` once; direnv builds the devShell and loads its tools into
`PATH` automatically on every subsequent `cd`. Without direnv,
`nix develop` (with flakes enabled per step 1) drops into an equivalent
shell manually.

## Install

**Once published to PyPI (upcoming with the `v5.0.0` tag):**

```bash
pipx install spaex
```

**From a local checkout (development):**

```bash
git clone https://github.com/haexmas/spaex.git
cd spaex
pip install -e '.[dev]'
```

Requires Python 3.14.x and Git 2.30+ on `$PATH`. spaex includes `uv` for
isolated, pinned CLI provisioning; `jsonschema` and `pyyaml` are the other
runtime dependencies.

### External skills

Molecules may keep standard `SKILL.md` directories in the publisher
repository, including `haexmas/atoms`. They are not copied by spaex's atom
materializer. A molecule declares them as structured `external_skills`
metadata: a repository, a full 40-character revision SHA, and a
repository-relative skill path (co-located with the molecule or elsewhere).
No `install_hook` is required or used for skill installation.

```json
"external_skills": [
  {
    "repository": "https://github.com/haexmas/atoms",
    "revision": "0123456789abcdef0123456789abcdef01234567",
    "path": "skills/example-skill"
  }
]
```

Normal `spaex install` never installs or materializes a referenced skill; its
structured declaration remains in the pinned molecule manifest as metadata.
Installation is a separate, explicit,
consumer-selected operation — see the
[Spec 018 design](specs/018-skills-externalization/spec.md) for the planned
`spaex skills install` / `spaex skills configure` commands and the consumer's
`skill_installation` policy, which are not implemented yet.

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
