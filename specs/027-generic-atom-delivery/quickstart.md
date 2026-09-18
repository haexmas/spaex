# Quickstart: Nix devShell via generic atom delivery

Walkthrough of the reference use case this spec exists to enable. Assumes the `haexmas/atoms` publisher repo has adopted this feature and published:

- `com.github.haexmas.atoms.nix-devshell-base` — exclusive atoms: `flake.nix`, `.envrc`, `.gitignore`.
- `com.github.haexmas.atoms.python` — existing `behavior` atoms, extended with a `nix_packages` fragment (`["python312"]`).
- `com.github.haexmas.atoms.rust` — existing `behavior` atoms, extended with a `nix_packages` fragment (e.g. `["rustc", "cargo"]`).

## Adopt the base + one language molecule

```sh
cd ~/Projekte/some-repo
spaex add https://github.com/haexmas/atoms \
  com.github.haexmas.atoms.nix-devshell-base \
  com.github.haexmas.atoms.python
```

`spaex install` runs as part of `add`. Result:

- `flake.nix`, `.envrc`, `.gitignore` appear at the repo root (exclusive atoms).
- `.spaex/generated/nix-packages.json` appears containing `["python312"]`.
- `direnv allow` (one-time) activates the shell; `python3` is on `PATH`.

## Adopt a second, orthogonal language molecule

```sh
spaex add https://github.com/haexmas/atoms com.github.haexmas.atoms.rust
```

- `flake.nix`/`.envrc`/`.gitignore` are untouched (already-satisfied exclusive atoms, no change).
- `.spaex/generated/nix-packages.json` is regenerated: `["cargo", "python312", "rustc"]` (sorted union of both contributors).
- `direnv reload` (or a fresh shell) brings `cargo`/`rustc` onto `PATH` alongside the still-present `python3`.

## Remove one contributor

```sh
spaex remove com.github.haexmas.atoms.python
```

- `.spaex/generated/nix-packages.json` is regenerated to `["cargo", "rustc"]` — Rust's packages are untouched, Python's are gone from the *definition*.
- `flake.nix`/`.envrc`/`.gitignore` are untouched (Rust's base molecule dependency, `nix-devshell-base`, is still adopted).
- The actual Python interpreter build remains in the Nix store until the operator runs their own `nix-collect-garbage` — spaex never triggers this (spec.md Non-Goals).

## Remove the last contributor and the base

```sh
spaex remove com.github.haexmas.atoms.rust com.github.haexmas.atoms.nix-devshell-base
```

- `.spaex/generated/nix-packages.json` is deleted (zero remaining contributors).
- `flake.nix`, `.envrc`, `.gitignore` are deleted (their owning molecule was retracted), unless the operator had modified any of them since install — in that case that file is left in place with a warning (FR-007).
