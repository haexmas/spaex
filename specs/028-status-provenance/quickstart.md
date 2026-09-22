# Quickstart: `spaex status` and `spaex trace`

Walkthrough for an operator who has already run `spaex install` in a repository with a handful of adopted molecules, some behavior-contributing, one shipping a generic root file, and one whose pin has drifted from what is installed.

## See the whole composition

```sh
cd ~/Projekte/some-repo
spaex status
```

Shows every pinned and installed molecule, grouped by what it actually contributed:

- Molecules that materialized behavior fragments list them by fragment id.
- Molecules that contributed to a composed generated artifact (for example `.spaex/generated/nix-packages.json`, Spec 027) name it.
- Molecules that wrote plain files (for example `flake.nix`) list the paths.

Below the molecule list, a constitution summary: whether `.spaex/constitution.md` exists, its clause count per modality, which molecules contribute to it, and any project-local fragments.

Nothing on disk changes; `spaex status --format json` (below) gives the same facts as structured data.

## Notice a drifted pin

```sh
# .spaex/manifest.json was hand-edited to bump a revision, but `spaex install`
# has not been run since.
spaex status
```

The report flags the mismatch under `Drift:` (or the JSON `drift` array), naming both the pinned and the installed revision, and suggests `spaex install`. `spaex status` never runs it; the exit code stays 0.

## Find out which molecule wrote a file

```sh
spaex trace flake.nix
```

```text
Path: flake.nix
Owner:
  com.github.haexmas.atoms.nix-devshell-base@<revision> (pinned in .spaex/manifest.json)
```

```sh
spaex trace .spaex/constitution.md
```

Lists every molecule that contributes behavior, and points to `spaex constitution trace <query>` for clause-level detail — `spaex trace` itself does not parse constitution clauses.

```sh
spaex trace README.md
echo $?   # 1 — no molecule is recorded for this file
```

A hand-written file, or one written by a molecule's `install_hook`, is not tracked; `spaex trace` says so rather than guessing.

## Consume the same data from a script or the future GUI

```sh
spaex status --format json | jq '.molecules[] | select(.install_state != "installed")'
spaex trace .spaex/generated/nix-packages.json --format json | jq '.matches[0].owners'
```

Both commands' JSON carries a `format_version` field; an unchanged repository produces byte-identical output on every run and on every supported OS.

## Fresh clone, no local molecule cache

```sh
git clone https://github.com/some-org/some-repo
cd some-repo
spaex status   # works — everything it reports is already committed
```

`spaex status` and `spaex trace` never read a molecule's own manifest or its content from the local cache (research.md R1); a fresh clone shows exactly what a checkout with a warm cache shows.
