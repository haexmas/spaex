# Feature Specification: Molecule tree materialization store

**Feature Branch**: `017-molecule-store`
**Created**: 2026-09-08
**Status**: Draft
**Input**: User description: "Spec 017: Molecule tree materialization store. Full design captured in docs/plans/2026-09-08-spec-017-molecule-store-design.md (PR #85 merged 2026-09-08)."
**Design reference**: [docs/plans/2026-09-08-spec-017-molecule-store-design.md](../../docs/plans/2026-09-08-spec-017-molecule-store-design.md)

## Clarifications

### Session 2026-09-08

- Q: Does an absolute-path symlink/hardlink target inside a materialized molecule tree get refused unconditionally, or only when it actually resolves outside the destination? → A: Refused unconditionally, regardless of where it would resolve. An absolute path baked into a molecule's tree is inherently non-portable (the local cache root varies per machine) and there is no legitimate reason a molecule's own tree needs to reference an absolute host path. Treating any absolute-path link target as refused-by-construction is also simpler to implement than resolve-then-check, since it requires only a string-shape check with no filesystem resolution.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A caller obtains a real, materialized molecule directory (Priority: P1)

Today, `spaex` reads individual molecule files (a manifest, a constitution fragment) as raw bytes directly from a bare git clone, one file at a time. This works for the constitution-assembly feature (which only ever needs to concatenate a handful of text files) but breaks down the moment any feature needs the molecule's content to exist as a real, navigable directory on disk — for example, a script that needs to be handed to a subprocess interpreter, or a script that imports sibling files relative to its own location.

With this story landed, any part of spaex can ask "give me a real, on-disk directory containing everything under this molecule's declared path, at this exact pinned revision" and get back a directory that behaves exactly like a normal checkout of that subtree — nothing more, nothing less.

**Why this priority**: this is the foundational capability. Without it, no other story in this spec, and no part of Spec 016 (molecule install-hooks), can proceed. Everything else in this spec is either a performance/safety property of this same operation (caching, atomicity, path safety) or a consumer of it (the constitution-resolution migration).

**Independent Test**: publish a minimal molecule (a manifest.json plus one arbitrary sibling file, e.g. `helper.txt`) to a git repository; request materialization for that molecule's path at the commit's SHA; verify the returned directory exists on disk, directly contains `manifest.json` and `helper.txt` with byte-identical content to what was committed, and contains nothing else.

**Acceptance Scenarios**:

1. **Given** a publisher repository with a molecule at path `widgets/hello` containing `manifest.json` and `helper.txt`, committed at SHA `X`, **When** a caller requests materialization of `widgets/hello` at `X`, **Then** the returned directory directly contains `manifest.json` and `helper.txt` (not nested one level deeper under a `widgets/hello/` subdirectory), with content byte-identical to the committed files.
2. **Given** the same molecule and revision, **When** a second, independent request for the same `(source, revision, molecule path)` is made, **Then** the same directory is returned without re-fetching or re-extracting anything, and the directory's content is unchanged.
3. **Given** a molecule path that does not exist at the given revision, **When** materialization is requested, **Then** the request fails with a clear, typed error distinguishing "not found" from other failure kinds, and no partial or empty directory is left behind at the expected cache location.

---

### User Story 2 - Materialization survives concurrent and interrupted requests (Priority: P2)

Multiple `spaex` processes (e.g., two terminals running `spaex install` in different consumer repos that both happen to adopt the same molecule) may request materialization of the same `(source, revision, molecule path)` at the same time. A crash, kill, or power loss mid-materialization must never leave a corrupted or partially-written directory that a later, successful request would mistake for a valid cache hit.

**Why this priority**: correctness under concurrency and interruption is a hard requirement for anything that acts as a shared, persistent, multi-process cache — a cache that can silently return corrupted content is worse than no cache at all. Priority P2 because it doesn't block the single-process happy path (Story 1) but must land before this capability is trusted in production use.

**Independent Test**: launch two materialization requests for the identical `(source, revision, molecule path)` concurrently (e.g., from two threads or two subprocesses); verify both complete successfully, return directories with identical, complete, correct content, and no corrupted intermediate state is observable by either. Separately, simulate an interruption mid-materialization (e.g., kill the process after partial extraction) and verify a subsequent request re-materializes cleanly rather than trusting a partial result.

**Acceptance Scenarios**:

1. **Given** two concurrent requests for the same `(source, revision, molecule path)` that has never been materialized before, **When** both run simultaneously, **Then** both complete successfully, both return a directory with complete and correct content, and no error or corruption occurs in either.
2. **Given** a materialization that is interrupted after it has started writing but before it completes, **When** a subsequent request for the same key is made, **Then** the subsequent request does not observe or return the incomplete prior attempt, and it completes materialization cleanly on its own.

---

### User Story 3 - Materialization refuses to be tricked into writing outside its target directory (Priority: P1)

The content being materialized originates from a publisher repository that spaex's operator has chosen to pin at a specific revision — but the operator did not necessarily author that content, and it should not be implicitly trusted to behave "nicely" when unpacked. A malicious or buggy publisher could commit a tree containing entries that, if extracted naively, would write files outside the intended destination directory (via `..` path segments, or via symbolic/hard links that redirect a later entry's write target elsewhere on the filesystem).

**Why this priority**: this is a security boundary, not a nice-to-have. A materialization routine that can be tricked into writing arbitrary files to arbitrary filesystem locations on the operator's machine is a critical vulnerability — equivalent in severity to path-traversal bugs in any archive-extraction tool. Priority P1 because Story 1 is not safely usable without this.

**Independent Test**: construct a crafted archive/tree containing (a) an entry with a `..`-escaping path, (b) a symbolic link entry whose target points outside the destination directory, (c) a hard link entry whose target points outside the destination directory, and (d) a "sandwich" attack where an early entry creates a symlink pointing outside the destination and a later entry's path traverses through that symlink to escape. Request materialization of this tree; verify every one of these cases is refused and no file is written outside the intended destination directory in any case.

**Acceptance Scenarios**:

1. **Given** a tree entry whose path contains a `..` segment attempting to escape the destination, **When** materialization processes that entry, **Then** the entry is refused and no file is written outside the destination.
2. **Given** a symbolic-link or hard-link tree entry whose target resolves outside the destination directory, **When** materialization processes that entry, **Then** the entry is refused and no such link is created.
2a. **Given** a symbolic-link or hard-link tree entry whose target is expressed as an absolute filesystem path (even one that would resolve inside the destination directory on the machine performing extraction), **When** materialization processes that entry, **Then** the entry is refused unconditionally.
3. **Given** a tree where an earlier entry is a symlink pointing outside the destination and a later entry's path would traverse through that symlink, **When** materialization processes the tree, **Then** the later entry is also refused (the escape is not permitted merely because it happens indirectly through an earlier entry).
4. **Given** a well-formed, non-malicious molecule tree with ordinary files, subdirectories, and internal (non-escaping) symlinks, **When** materialization processes it, **Then** all entries are extracted successfully and no legitimate content is incorrectly refused.

---

### User Story 4 - Existing constitution assembly keeps working, now on the same content-access path as everything else (Priority: P2)

Today, constitution assembly (the part of `spaex install` that gathers each adopted molecule's constitution text and joins it into the consumer's effective constitution) reads molecule manifests and constitution files as raw bytes, independent of the materialization capability introduced by this spec. Going forward, this same code path is migrated to use materialization for its own molecule-manifest and constitution-body reads, so there is exactly one way the rest of spaex accesses molecule content, not two parallel ones.

**Why this priority**: this consolidation prevents future features from having to choose between two content-access idioms, and prevents subtle drift between them (e.g., a security fix applied to one path but not the other). Priority P2 (not P1) because the existing byte-access approach already works correctly for today's shipped feature set — this migration is about long-term coherence, not fixing a live defect, and can land immediately after Story 1 without blocking it.

**Independent Test**: run the existing constitution-assembly test suite unchanged; every currently-passing scenario (single-molecule adoption, missing-manifest error, version-mismatch error, missing-contribution-file error, multi-compound resolution ordering) continues to pass with identical observable behavior and identical error types, after the migration.

**Acceptance Scenarios**:

1. **Given** a consumer that has adopted one molecule contributing a constitution, **When** `spaex install` resolves and assembles the constitution, **Then** the resulting assembled constitution content is identical to what the pre-migration implementation would have produced from the same input.
2. **Given** a compound entry whose declared molecule does not exist at the pinned revision, **When** resolution runs, **Then** the same typed error that was raised before migration is raised again, with the same diagnostic information.
3. **Given** a molecule that declares a constitution file that is not actually present at the declared path, **When** resolution runs, **Then** the same typed error that was raised before migration ("declared contribution file not found") is raised again.
4. **Given** a compound entry whose revision is supplied in a form that is not already a canonical full 40-character SHA (e.g. supplied programmatically rather than through the schema-validated JSON path), **When** resolution runs, **Then** the canonical full SHA is what gets used for every subsequent read and for the materialization cache key — never the original, unresolved form.

---

### Edge Cases

- **Molecule path exists but is empty at the given revision** (declared in the publisher manifest but the directory contains no committed files): materialization succeeds and returns an existing, empty directory; callers that then look for specific files inside report their own "file not found" per their own contract (e.g., "manifest.json missing" from the constitution-resolution path) — this spec's materialization step itself does not fail merely because the directory is empty.
- **Two requests for the same molecule path but different revisions of the same publisher repo**: treated as entirely independent cache entries; materializing one never affects, invalidates, or reuses the other, since a fixed revision is immutable but two different revisions may have arbitrarily different content at the same path.
- **A previously materialized directory is deleted or corrupted out-of-band** (e.g., an operator manually removes files from the local cache): a subsequent request either re-materializes cleanly (if the cache-presence check is a full validity check) or is explicitly out of this spec's guaranteed-detection scope if only a lightweight existence check is used — the exact behavior here is a design decision for `/speckit-plan`, not a product requirement, since out-of-band tampering with an internal, undocumented local cache directory is not a supported operator workflow this spec needs to protect against; it only needs to not silently propagate corruption it can detect for free (e.g., a completely missing directory triggers fresh materialization).
- **The requested molecule path is not a valid, safe relative path in the first place** (contains `..` segments in the *molecule path* itself, not just in tar entries within it): refused before any git/tar operation is attempted, using the same repo-relative-path validation already applied elsewhere to molecule paths sourced from a publisher manifest.
- **Extraction fails partway due to a legitimate transient failure** (disk full, permission error unrelated to any malicious content): the request fails with a typed error distinguishing this from "content refused for safety reasons" and from "not found"; no partially-written directory is left at the final cache location (Story 2's atomicity guarantee).

## Requirements *(mandatory)*

### Functional Requirements

**Core materialization**

- **FR-001**: The system MUST provide a way to obtain a real, on-disk directory containing the complete contents of a named subtree (a "molecule path") of a given source repository at a given pinned revision.
- **FR-002**: The returned directory MUST directly contain the subtree's top-level entries (files and subdirectories) — it MUST NOT be nested one additional level deeper under a directory named after the requested molecule path.
- **FR-003**: The content of every extracted file MUST be byte-identical to that file's committed content at the given revision.
- **FR-004**: A request for a molecule path that does not exist at the given revision MUST fail with a distinct, identifiable failure kind (distinguishable from "materialization succeeded but the directory happens to be empty," from "the request was refused for safety reasons," and from "a transient IO failure occurred").

**Caching and idempotency**

- **FR-005**: A second request for the same `(source repository, revision, molecule path)` combination MUST NOT re-fetch or re-extract content that has already been successfully materialized; it MUST return a directory with content identical to the first successful materialization.
- **FR-006**: Cache identity MUST be keyed on the canonical, full-length revision identifier. If a caller supplies a revision in a shorter or symbolic (non-canonical) form, the system MUST resolve it to canonical form before using it as a cache key or performing any extraction, and every downstream use (extraction, any provenance record derived from the request) MUST use the canonical form consistently.
- **FR-007**: Materialization MUST be performed on demand, only when a caller actually requests a given `(source, revision, molecule path)`. The system MUST NOT proactively materialize molecule paths that have not been requested.

**Concurrency and durability**

- **FR-008**: Two or more concurrent requests for the same, not-yet-materialized `(source, revision, molecule path)` MUST both complete successfully and both observe complete, correct content — neither request may observe or return a partially-materialized result belonging to the other.
- **FR-009**: An interruption (process crash, kill, power loss) occurring after materialization has begun writing but before it completes MUST NOT leave behind a directory, at the location a future successful request would treat as a valid cache hit, that contains incomplete or corrupted content. A subsequent request for the same key MUST detect the absence of a valid prior result and materialize fresh.

**Safety against malicious or malformed content**

- **FR-010**: An entry within the source content whose path would resolve outside the destination directory via relative path segments (e.g., `..`) MUST be refused; no file MUST be written outside the destination directory as a result of processing it.
- **FR-011**: A symbolic-link or hard-link entry whose target would resolve outside the destination directory MUST be refused; no such link MUST be created. A symbolic-link or hard-link entry whose target is expressed as an absolute filesystem path MUST be refused unconditionally, regardless of where that path would resolve — absolute-path targets are never permitted, not even ones that happen to resolve inside the destination on the machine performing extraction.
- **FR-012**: The refusal checks in FR-010 and FR-011 MUST be effective even when the escape is achieved indirectly — for example, an earlier entry creates a link pointing outside the destination, and a later entry's own path traverses through that link to reach outside the destination. Entries MUST be evaluated in the order they appear in the source content, and a later entry MUST NOT be permitted to rely on a path component established by an earlier entry that was itself refused or that itself points outside the destination.
- **FR-013**: A well-formed source tree containing ordinary files, subdirectories, and internal links that do not escape the destination directory MUST be extracted successfully in full; the safety checks in FR-010 through FR-012 MUST NOT produce false refusals for legitimate content.
- **FR-014**: The molecule path supplied to a materialization request MUST itself be validated as a safe, relative path (no parent-directory segments, no absolute-path form, no disallowed characters) before any repository access is attempted; an invalid molecule path MUST be refused without performing any extraction work.

**Migration of existing constitution assembly**

- **FR-015**: The existing constitution-resolution process's reads of a molecule's own manifest and of a molecule's declared constitution file(s) MUST be served by this spec's materialization capability rather than by direct, single-file remote-content reads, without changing the observable outcome of constitution resolution for any previously-working scenario.
- **FR-016**: The existing constitution-resolution process's read of the *publisher's root manifest* (which is needed to discover a molecule's declared path in the first place, before materialization of that molecule is even possible) is explicitly UNCHANGED by this spec and continues to use direct, single-file remote-content reads.
- **FR-017**: Every existing, previously-passing constitution-resolution test scenario (successful single- and multi-molecule resolution, missing-publisher-manifest error, missing-molecule-manifest error, molecule-id-mismatch error, version-mismatch error, missing-constitution-file error, molecule-id-collision-across-sources error) MUST continue to produce the same typed failure (or the same successful result) after migration.
- **FR-018**: A constitution file path declared by a molecule manifest MUST be subject to the same escape-refusal principle as FR-010/FR-011 at read time: if the declared path, once resolved against the materialized directory, would (via a symbolic link or otherwise) resolve outside that materialized directory, the read MUST be refused rather than silently followed.
- **FR-019**: Failures arising from this spec's materialization capability, when surfaced through the constitution-resolution process, MUST be reported using the same failure categories that process already exposes to its own callers today (a molecule's manifest cannot be found or read; a declared contribution file cannot be found; a declared revision cannot be found) so that existing callers and tests are not required to learn new failure categories for scenarios they already handle. A genuinely new failure category (an unexpected, non-"not found" materialization failure — for example a transient IO error) MUST be exposed as its own distinct, identifiable failure kind, not silently folded into one of the existing "not found" categories.

### Key Entities

- **Materialized molecule directory**: a real, on-disk directory whose content is a byte-identical, safety-checked copy of a molecule path's committed content at one specific, immutable revision. Uniquely identified by the triple (source repository, revision, molecule path). Once successfully created, treated as permanently valid for that exact triple (no expiry, no invalidation, consistent with the immutability of a pinned revision).
- **Materialization request**: an ask, from any part of the system, for the materialized directory corresponding to one (source, revision, molecule path) triple. May be satisfied by returning an already-materialized directory (cache hit) or by performing fresh materialization (cache miss).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Any feature needing a molecule's content as real files on disk (starting with Spec 016's install-hook execution) can obtain a working directory for that molecule with a single request, with zero additional plumbing beyond supplying the (source, revision, molecule path) it already has available.
- **SC-002**: Repeated requests for the same (source, revision, molecule path) impose no additional network or repository-read cost beyond the first successful request — verified by observing that no additional remote-repository access occurs on a cache hit.
- **SC-003**: Zero test cases in the crafted-malicious-content test suite (path traversal, symlink escape, hardlink escape, indirect/chained escape) result in a file being written outside the intended destination directory.
- **SC-004**: One hundred percent of the pre-existing constitution-resolution test scenarios continue to pass, unmodified in their expected outcomes, after the migration described in User Story 4.
- **SC-005**: Under concurrent requests for an identical, not-yet-materialized key from multiple simultaneous processes, one hundred percent of those requests complete successfully with correct, complete content, with zero observed corruption.

## Assumptions

- **Publisher content is authenticated but not implicitly trusted for extraction safety**: the pinned revision (a full 40-hex SHA) cryptographically authenticates that the content came from the publisher's actual history — but authenticity of origin is a separate property from safety of extraction. This spec treats every materialization request as needing the safety checks in User Story 3 regardless of how trusted the source is presumed to be, consistent with defense-in-depth.
- **The underlying repository access mechanism (a local, previously-fetched copy of the publisher repository) already exists and is out of scope for this spec** — this spec assumes a local repository copy for the given source is already available (via existing, unmodified machinery) and focuses solely on materializing a subtree of it into a real directory. Fetching or updating that local repository copy is unchanged by this spec.
- **No content-integrity verification (hashing) is in scope.** This spec produces materialized directories but does not compute, store, or verify any cryptographic digest of their content. A previously-designed, more elaborate content-addressed-with-hashing scheme exists on paper but has no current consumer in the system and is deferred to a future spec if and when such a consumer (e.g. a verification command) is actually built.
- **No proactive/eager materialization of molecules that have not been explicitly requested.** Only content actually needed by an active caller is materialized.
- **The local materialized-directory cache is a local, per-machine implementation detail, not a supported operator-facing interface.** Operators are not expected to browse, inspect, or manually manage its contents; out-of-band tampering with it is not a scenario this spec needs to gracefully recover from beyond the basic "missing directory triggers fresh materialization" behavior already implied by cache-miss handling.
- **This spec's capability is a direct, blocking prerequisite for a separate, already-specified feature (molecule install-hooks)** that needs a real on-disk directory to hand a script to a subprocess interpreter. That consuming feature's own requirements are out of scope here; this spec only needs to provide the materialization capability generally, in a way that consumer can build on.

## Dependencies

- **Design doc**: [docs/plans/2026-09-08-spec-017-molecule-store-design.md](../../docs/plans/2026-09-08-spec-017-molecule-store-design.md) — the source design this spec formalizes, including 2026-09-08 scoping decisions (no hashing, lazy materialization, migrate constitution-resolution) and review-driven refinements (canonical-SHA cache keys, archive-order-aware link-escape defense, resolver error-contract translation).
- **Existing constitution-resolution process**: the feature migrated by User Story 4; this spec's success is partly measured by that process's continued correctness (SC-004).
- **Molecule install-hooks** (a separately specified feature): the concrete, motivating consumer of this spec's materialization capability. That feature's implementation is blocked on this spec landing.

## Out of scope (deferred)

- **Content-integrity hashing and a corresponding verification command.** No current consumer; deferred until one exists.
- **Cross-device or cross-machine synchronization of materialized content.** Purely a local, per-machine cache.
- **A fully-committed, consumer-repository-visible "generated" tree** assembled from many molecules' materialized content (multi-tool compilation output). That is the concern of a separate, not-yet-specified feature; this spec's materialized directories are internal, local-cache-only artifacts.
- **Eager, proactive materialization of every resolvable molecule** regardless of whether anything has asked for it yet.
- **Migrating the adoption-request-validation reads** (the checks performed when a molecule is first being added to a consumer, before any full resolution happens) onto this materialization capability. Those reads serve a different purpose (validating a single small manifest file, not needing a full tree) and are unaffected by this spec.
