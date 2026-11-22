# Quickstart: verify verbatim composition

Run from the worktree with `uv run` (or the project's usual test entry). All model calls in tests use the stub caller.

## 1. Every line arrives (US1)

```sh
uv run pytest tests/behavior/unit/test_render.py tests/behavior/integration/test_verbatim_composition.py -q
```

Expect: a 32-rule fragment appears byte for byte; every fragment exactly once; headings, lists and code blocks intact.

## 2. Installing again changes nothing (US2)

```sh
uv run pytest tests/behavior/integration/test_reproducibility.py tests/behavior/integration/test_source_hash_skip.py -q
```

Expect: three installs byte-identical, runs after the first make 0 stub calls, a deleted composed file reappears identical with 0 calls.

## 3. Findings are asked and applied (US3)

```sh
uv run pytest tests/behavior/integration/test_findings_decisions.py -q
```

Expect: a contradiction and a duplicate are each asked with both passages; "keep 1" comments out passage 2 with its text unchanged; "keep all" comments out nothing; a second install asks nothing; a changed passage asks again; a non-interactive run exits 21 and changes no file.

## 4. Old repos move over (US4)

```sh
uv run pytest tests/behavior/integration/test_v1_migration.py -q
```

Expect: a version 1 file is replaced by version 2 in one install, `clarifications.json` and `.stale` are gone, a second install changes nothing, `build --check` reports version 1 as out of date before.

## 5. Tools read the new format (US5)

```sh
uv run pytest tests/behavior/integration/test_provenance_trace.py tests/behavior/integration/test_status.py tests/behavior/integration/test_local_behavior.py -q
```

## 6. Whole suite and static checks

```sh
uv run pytest -q && uv run ruff check . && uv run mypy src
```

## 7. By hand on a real repo

In a copy of a repo that uses spaex (for example haex-vault): `spaex install`, answer the findings, then `git diff --stat .spaex/`. Run `spaex install` again: no output change and no model call (check `.spaex/composer.log` stays empty). Delete `.spaex/constitution.md`, install again: identical file.
