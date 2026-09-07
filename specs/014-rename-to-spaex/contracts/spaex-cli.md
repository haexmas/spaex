# Contract: `spaex` CLI surface

**Spec**: 014
**Scope**: the CLI binary shape after Phase 2 of the rename. Every subcommand from Spec 013 preserves its argument grammar and refusal keys; the only user-visible change is the binary name and the filenames those commands read and write.

The authoritative per-subcommand grammars live in the Spec 013 contracts:
- [`../../013-add-cli-and-molecule-rename/contracts/haex-add.cli.md`](../../013-add-cli-and-molecule-rename/contracts/haex-add.cli.md)
- [`../../013-add-cli-and-molecule-rename/contracts/haex-remove.cli.md`](../../013-add-cli-and-molecule-rename/contracts/haex-remove.cli.md)

Under Spec 014 those contracts apply verbatim after the following mechanical substitutions.

## Binary name

**Before**: `haex`
**After**: `spaex`

Every invocation `haex <subcommand> ...` becomes `spaex <subcommand> ...`. No option grammar changes, no exit-code changes, no refusal-key changes.

## Config filenames

**Before**: `.haex-hive.json`, `.haex-hive.json.lock`, `.haex-hive/install.lock`, `.haex-hive/pending/`
**After**: `.spaex.json`, `.spaex.json.lock`, `.spaex/install.lock`, `.spaex/pending/`

Every diagnostic, adoption instruction, and help-text reference to a config filename uses the new name after Phase 2.

## Environment variable

**Before**: `HAEX_HIVE_STATE`
**After**: `SPAEX_STATE`

Semantics unchanged. Fallback default path unchanged. `spaex` MUST NOT read `HAEX_HIVE_STATE`.

## Subcommands (post-rename)

| Command | Purpose | Reference |
|---|---|---|
| `spaex add <source-url> <molecule-ids...>` | Adopt one or more molecules from a source URL. Writes `.spaex.json` and calls `spaex install` in the same invocation. | Spec 013 contract, with rename applied. |
| `spaex remove <molecule-ids...>` | Retract one or more molecules from `.spaex.json`. Calls `spaex install` in the same invocation. | Spec 013 contract, with rename applied. |
| `spaex install` | Publish adopted molecules atomically into participating roots. Writes `.spaex/install.lock`. | Spec 008 contract, with rename applied. |
| `spaex migrate` | Read v1/v2/v3 manifests, produce v4 `.migrated` sibling proposals. Idempotent on v4. | This spec's [spaex-migrate.v3-to-v4.md](spaex-migrate.v3-to-v4.md) plus the preserved Spec 013 v2-to-v3 contract. |
| `spaex constitution show` | Print the assembled constitution to stdout. `--no-preface` skips the "Assembled from" header. | Spec 007 contract, with rename applied. |
| `spaex --version` | Print the package version. Must match the value in `pyproject.toml`. | New in this feature; MUST report `4.0.0` after the first release. |

## Exit codes (preserved from Spec 013)

- `0`: success or no-op.
- `1`: mixed proposal-plus-refusal (migrate only).
- `2`: hard refusal without any proposal.
- `6`: manifest-lock contended (add, remove; per Spec 013 FR-028).

## Refusal keys (preserved from Spec 013)

Unchanged. Every key from `manifest-lock-contended` through `unsupported-min-version-constraint`, `constitution-already-adopted`, `workflow-molecule-already-adopted`, `source-url-invalid`, `revision-not-found`, `publisher-manifest-missing`, `publisher-manifest-invalid`, `unknown-molecule-id`, `atoms-category-overlap`, etc.

The only new refusal-key surface is on the schema-loader gate:
- **`spaex-version-unsupported`** (new in this feature, replaces v3-era `haex-hive-version-unsupported`): raised when a manifest read gate sees a `spaex_version` other than `"4"`. Diagnostic names `spaex migrate` as the next step.
- **`unsupported-min-version-constraint`** (v3→v4 leg): raised when `spaex migrate` cannot rewrite a `haex_hive_min_version` constraint. Same semantics as the v2→v3 leg.
