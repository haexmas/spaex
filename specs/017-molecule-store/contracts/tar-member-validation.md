# Contract: tar-member path-containment validation

**Applies to**: every member of the tar stream produced by `git archive <revision> -- <molecule_path>`, processed in the order they appear in that stream, before any of it is written to disk at its final location.

This is the algorithm that makes Python 3.10/3.11 (which lack `tarfile.extractall(filter="data")`, a 3.12+ feature) as safe as 3.12+'s built-in filtering, specifically against the attack classes enumerated in spec.md's User Story 3.

## Inputs

- `members`: the tar stream's entries, in their original archive order (not sorted, not reordered).
- `destination`: the (temporary, pre-rename) directory that extraction targets.

## Algorithm (per member, in archive order)

For each `member` in `members`:

1. **Normalize the member's own path.** Compute the path `destination / member.name`, resolve `.`/`..` segments lexically (without touching the filesystem yet — the target may not exist yet). If the normalized result is not a strict descendant of `destination` (i.e., `destination` is not a proper prefix of the normalized path, or the normalized path equals `destination` itself) → **reject this member** (FR-010's `..`-escape case). Do not extract it. Continue to the next member (a single bad member does not necessarily abort the whole extraction at this stage — but see "Aggregate outcome" below).

2. **If the member is a symlink or hardlink** (`member.issym()` or `member.islnk()`):
   a. **Absolute-target check** (2026-09-08 clarification): if `member.linkname` is an absolute path (starts with `/` on POSIX, or matches an absolute-path pattern on Windows if ever relevant) → **reject unconditionally**, regardless of where it would resolve. No further resolution is attempted for this member.
   b. **Relative-target resolution**: resolve `member.linkname` relative to the DIRECTORY containing the member's own normalized path (from step 1) — not relative to `destination` itself, matching how filesystems actually resolve relative symlink targets. If the resolved path is not a strict descendant of `destination` → **reject** (FR-011's base case).
   c. **If accepted**, record this member's normalized path as an "established link" for the archive-order tracking in step 3.

3. **Archive-order dependency check** (FR-012, defeats the "sandwich" attack — User Story 3 Acceptance Scenario 3): before extracting a member whose normalized path has any ancestor directory component, check whether that ancestor component corresponds to (or was reached through) a member REJECTED in step 1 or 2 above, OR a symlink member ACCEPTED in step 2 that itself points outside `destination` (which should not happen if step 2 is implemented correctly, but is checked here as defense-in-depth against an implementation bug in step 2). If any ancestor component is unsafe by this check → **reject this member too**, even though its own path and (if applicable) own link target might otherwise pass steps 1-2 in isolation. This is what makes the check "archive-order aware" rather than "per-member independent."
   - Concretely: maintain a set of "confirmed-safe" directory paths as members are accepted, in archive order. A member's full ancestor chain must consist entirely of confirmed-safe (or not-yet-existing, ordinary-directory) components; if any ancestor was established by a REJECTED member, or is itself a symlink whose target was never validated as safe, the current member is rejected too.

4. **If the member passes all checks**, extract it (write the file/directory/symlink at its normalized path under `destination`), and record its path (and, for directories, its status as a safe ancestor for later members) accordingly.

## Aggregate outcome

- If ANY member is rejected by the above, the overall `get_or_extract()` call for this materialization attempt MUST fail (raising `MoleculeTreeExtractionError` per the `get-or-extract.md` contract) rather than silently producing a partial directory containing only the "safe" subset. Partial-but-silently-incomplete materialization would violate the "byte-identical to committed content" postcondition (FR-003) for legitimate content and could mask an attack as a mere "some files missing" oddity rather than surfacing it as the refusal it should be.
- A failed validation pass MUST NOT leave anything at the FINAL cache path (`final_dir`) — the temp-directory-then-atomic-rename design (research.md, `get-or-extract.md`) means a validation failure simply means the rename never happens; the temp directory (now containing a rejected, incomplete extraction) is discarded or left as an orphan, never promoted to `final_dir`.

## Worked examples (from spec.md's User Story 3 Acceptance Scenarios)

1. **`..`-escaping path** — member name `../../../etc/passwd` (or any path whose normalized form under `destination` is not a descendant of `destination`) → rejected at step 1.
2. **Symlink with absolute target** — member is a symlink named `innocuous.txt` with `linkname = "/etc/passwd"` → rejected at step 2a, regardless of the fact that `/etc/passwd` obviously resolves outside `destination` (this case would ALSO be caught by resolve-then-check, but per the 2026-09-08 clarification it is rejected unconditionally without even needing to reach that resolution).
3. **Symlink with escaping relative target** — member is a symlink named `subdir/link` with `linkname = "../../outside"` → resolved relative to `destination/subdir/`, lands outside `destination` → rejected at step 2b.
4. **Chained/sandwich escape** — member 1 is a symlink named `escape` with `linkname = "../outside"` (rejected at step 2b, since it resolves outside `destination`); member 2 is a regular file named `escape/payload.txt`. Because member 1 was rejected, `escape` is never created as a real symlink at all — so member 2's ancestor `escape` doesn't exist as a link; if the implementation naively re-attempted to create `escape` as an ordinary directory to satisfy member 2's parent path, THAT would need its own escape check (it's an ordinary path, caught by step 1 if it escaped, but here `escape` itself is a safe ordinary name — the actual risk case is when member 1 is ACCEPTED as a symlink that resolves INSIDE destination on its own, but a LATER member then uses a DIFFERENT relative target through it that only escapes in combination). The archive-order tracking in step 3 exists precisely for this compounding case — a symlink target that looks safe in isolation but whose combination with a later member's path traverses somewhere unsafe. Implementation and tests MUST construct at least one concrete case of this compounding kind (not just the simpler member-1-directly-escapes case, which steps 1-2 alone already catch).
5. **Legitimate internal symlink** — member is a symlink named `alias` with `linkname = "real-file.txt"` (a sibling in the same directory, resolving inside `destination`) → accepted at step 2b, extracted normally.
6. **Ordinary nested files and directories with no links at all** — every member passes step 1 trivially (no escape), steps 2-3 don't apply (not links), extracted normally. This is the common case (e.g., `graphify-first-authoring`'s actual tree: `manifest.json`, `constitution.md`, `install.py`, `hooks/_tracked_branches.py`, etc. — no links anywhere) and MUST NOT be slowed down or complicated by the presence of this validation logic; the checks above should be cheap for the non-link, non-escaping common case.
