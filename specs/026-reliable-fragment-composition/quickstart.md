# Quickstart: Reliable Fragment Composition

## For an operator with a small fragment set (the common case)

Nothing changes. `spaex install` behaves exactly as it does today: one Composer call, one composed `.spaex/constitution.md`. This feature only changes behavior once the fragment set is large enough to need more than one batch (SC-004: no regression for the common case).

## For an operator with a large fragment set (today: 9+ molecules)

```console
$ spaex install
composer: invoking claude (payload 6412 chars, timeout 300s)...
composer: claude responded in 8.2s
composer: batch-1 composed (3 molecules, 3 fragments cited)
composer: invoking claude (payload 5890 chars, timeout 300s)...
composer: claude responded in 7.6s
composer: batch-2 composed (3 molecules, 4 fragments cited)
composer: invoking claude (payload 6103 chars, timeout 300s)...
composer: claude responded in 6.9s
composer: batch-3 composed (3 molecules, 2 fragments cited)
composer: invoking claude (payload 2210 chars, timeout 300s)...
composer: claude responded in 5.1s
composer: merge composed (3 batches → 1 constitution, 9 fragments cited)
composed .spaex/constitution.md (9 fragment(s))
installed generation g_20260916T120000Z_a1b2
```

Each batch and the merge step reuse the exact same progress/timing log lines this project already shipped (invocation start, elapsed time on response) — there are just more of them, one set per step, instead of one set for the whole build.

## When something fails partway through

```console
$ spaex install
composer: invoking claude (payload 6412 chars, timeout 300s)...
composer: claude responded in 8.2s
composer: batch-1 composed (3 molecules, 3 fragments cited)
composer: invoking claude (payload 5890 chars, timeout 300s)...
error: exit=30 key=behavior-composer-timeout
  claude timed out after 300.0s (host load avg 1/5/15m: 2.10/2.05/1.98)
  hint: Composer exceeded SPAEX_COMPOSER_TIMEOUT. Increase the budget, reduce the fragment set, or switch to a faster runtime.
```

`.spaex/constitution.md` is unchanged from before this run (FR-004). `.spaex/composer.log` contains one JSON-lines record for `batch-1` (the step that succeeded) even though `batch-2` is the one that failed — the operator can inspect what actually completed, not just the final error.

A manual re-run of `spaex install` is a normal, sufficient way to try again (SC-005) — no special recovery command is needed.

## Verifying reproducibility still holds

```console
$ spaex install            # first run, composes fresh
$ sha256sum .spaex/constitution.md
$ spaex install            # second run, nothing changed
no changes
$ sha256sum .spaex/constitution.md   # identical hash
```

The second run doesn't re-invoke composition at all (the existing reproducibility skip, unaffected by batching). Forcing a real re-composition of the same unchanged fragment set (`spaex constitution build --force`) produces a byte-identical result to the first run.
