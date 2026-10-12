# Quickstart: Local Molecule Scope

Validation guide for the scenarios in [spec.md](./spec.md). Behavior composition requires the composer runtime; automated tests stub it (see `tests/behavior/integration/test_project_local_fragments.py`).

## Prerequisites

- A consumer repo with project-scope adoptions and a clean working tree (`git status` empty).
- `spaex install --global` already run (bootstrap block version 3 after this feature).

## 1. Adopt locally (US1, US2, SC-001, SC-002)

```bash
cp .spaex/constitution.md "$TMPDIR/project-before.md"
spaex add --local https://github.com/haexmas/atoms com.github.haexmas.atoms.ponytail --revision <sha40>
git status --porcelain            # expected: empty
git add -A --dry-run              # expected: nothing under .spaex/local/
cmp .spaex/constitution.md "$TMPDIR/project-before.md"   # expected: identical
head -n 20 .spaex/local/constitution.md   # expected: preamble "project constitution prevails"
```

## 2. Determinism (SC-004)

```bash
spaex install && sha256sum .spaex/install.lock .spaex/local/install.lock > "$TMPDIR/a"
spaex install && sha256sum .spaex/install.lock .spaex/local/install.lock > "$TMPDIR/b"
diff "$TMPDIR/a" "$TMPDIR/b"      # expected: no difference
```

## 3. Provenance (US4, SC-006)

```bash
spaex status                       # local molecule marked [local]
spaex trace .spaex/local/constitution.md   # owner listed with (local)
spaex constitution show            # project document, then "## Local (this checkout only)"
```

## 4. Conflicts (edge cases)

```bash
spaex add --local <url> <id-already-in-project>   # expected: local-adoption-shadowed, nothing changed
```

A local molecule whose exclusive file collides with a tracked file is refused with `local-path-conflict`.

## 5. Remove (US3, SC-005)

```bash
spaex remove --local com.github.haexmas.atoms.ponytail
test ! -e .spaex/local             # expected: gone after the last local molecule
grep -c 'spaex-local:start' "$(git rev-parse --git-path info/exclude)"   # expected: 0
```

## 6. Fresh clone (US5)

```bash
git clone <remote> "$TMPDIR/fresh" && cd "$TMPDIR/fresh" && spaex install
# expected: identical project outputs, no .spaex/local/
```

## Note on older spaex versions

Running a spaex version without this feature in a checkout that has `.spaex/local/` drops that directory on its next install. Recreate it with `spaex add --local`.
