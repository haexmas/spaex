"""Typed exception hierarchy for every diagnostic emitted by `spaex`.

Each subclass carries its canonical diagnostic key (used by `emit_refuse`) and
its canonical exit code from `spaex.util.exit_codes`. Every CLI contract
diagnostic path is represented; no CLI handler is allowed to invent a new key
or exit code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spaex.util import exit_codes


@dataclass
class HaexError(Exception):
    """Base for every diagnostic emitted by the CLI.

    Subclasses set `diagnostic_key` and `exit_code` as class attributes.
    Instances may attach a machine-parseable `context` dict with fields such
    as `entry`, `atom_id`, or `field_path`; the values are formatted by
    `emit_refuse` without leaking secret payload contents.
    """

    message: str = ""
    context: dict[str, str] = field(default_factory=dict)

    diagnostic_key: str = ""
    exit_code: int = 1
    hint: str = ""

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message or self.diagnostic_key)


# --- Source and manifest boundaries -----------------------------------------


@dataclass
class CredentialInUrlError(HaexError):
    diagnostic_key: str = "credential-in-source-url"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Remove credentials from the URL. Configure git to use a credential helper instead."


@dataclass
class UnsupportedSchemeError(HaexError):
    diagnostic_key: str = "unsupported-source-scheme"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Use https:// or ssh:// for the atom source."


@dataclass
class PermissionOnlyEntryError(HaexError):
    diagnostic_key: str = "permission-only-entry"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Permission-only entries cannot be widened into v2 atom grants."


@dataclass
class IdentityMismatchError(HaexError):
    diagnostic_key: str = "identity-not-github-nor-reverse-dns"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Provide a reverse-DNS identity or a GitHub org/user identity."


@dataclass
class MissingRemoteOriginError(HaexError):
    diagnostic_key: str = "missing-remote-origin"
    exit_code: int = exit_codes.IO_REFUSE
    hint: str = "Configure `git remote add origin` before running spaex."


@dataclass
class MissingPublisherManifestError(HaexError):
    diagnostic_key: str = "publisher-manifest-not-found"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Verify the publisher declares manifest.json at the pinned revision."


@dataclass
class MissingAtomManifestError(HaexError):
    diagnostic_key: str = "atom-manifest-not-found"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Verify the atom declares its manifest.json at the pinned revision."


@dataclass
class AtomIdCollisionError(HaexError):
    diagnostic_key: str = "atom-id-collision"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Two different (source, revision) pairs map to the same atom-id."


@dataclass
class MoleculeAtomsCategoryOverlapError(HaexError):
    diagnostic_key: str = "atoms-category-overlap"
    exit_code: int = exit_codes.VALIDATION_REFUSE
    hint: str = "A delivered path may appear in only one atoms.<category>."


@dataclass
class ExclusiveAtomPathCollisionError(HaexError):
    """Spec 027 FR-003: two adopted molecules claim the same exclusive-category path.

    New cross-molecule enforcement, distinct from `atoms-category-overlap`
    (which only ever caught one molecule's own manifest declaring a path
    twice — `behavior` atoms never had their own destination path to
    collide on before this feature).
    """

    diagnostic_key: str = "exclusive-atom-path-collision"
    exit_code: int = exit_codes.VALIDATION_REFUSE
    hint: str = (
        "Only one adopted molecule may declare a given path under an exclusive atom category."
    )


@dataclass
class ExclusiveAtomPathEscapesRepoError(HaexError):
    """Spec 027 FR-010: an exclusive-category destination resolves outside the repo root."""

    diagnostic_key: str = "exclusive-atom-path-escapes-repo"
    exit_code: int = exit_codes.VALIDATION_REFUSE
    hint: str = (
        "Remove the symlinked ancestor directory redirecting this path outside the repository."
    )


@dataclass
class ExclusiveAtomPathUnsupportedShapeError(HaexError):
    """An exclusive-category path cannot round-trip through install.lock's schema.

    `install-lock.v4.schema.json`'s `paths` items only accept a bare
    single-segment filename or a path whose first segment starts with a
    literal dot; a molecule manifest's own `RepoRelativePath` validation is
    looser (it merely forbids absolute paths, backslashes, and `.`/`..`
    segments), so a nested path without a leading dot-segment (e.g.
    `config/tool.toml`) would pass manifest parsing yet fail the very next
    `install.lock` read.
    """

    diagnostic_key: str = "exclusive-atom-path-unsupported-shape"
    exit_code: int = exit_codes.VALIDATION_REFUSE
    hint: str = (
        "Declare the exclusive atom's path as a bare root-level filename "
        "(e.g. flake.nix) or nested under a leading dot-segment (e.g. "
        ".codex/foo.md)."
    )


@dataclass
class NixPackagesFragmentInvalidError(HaexError):
    """Spec 027 FR-009: a `nix_packages` fragment is not a non-empty array of non-empty strings."""

    diagnostic_key: str = "nix-packages-fragment-invalid"
    exit_code: int = exit_codes.VALIDATION_REFUSE
    hint: str = (
        "Declare nix_packages as a non-empty JSON array of non-empty "
        "package-identifier strings."
    )


@dataclass
class VersionBelowMinError(HaexError):
    diagnostic_key: str = "spaex-version-below-min"
    exit_code: int = exit_codes.SYSTEM_REFUSE
    hint: str = "Upgrade the installed spaex to satisfy `spaex_min_version`."


@dataclass
class SpaexVersionUnsupportedError(HaexError):
    diagnostic_key: str = "spaex-version-unsupported"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Use the current `.spaex/manifest.json` schema."


@dataclass
class NoSourcesDeclaredError(HaexError):
    diagnostic_key: str = "no-sources-declared"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Add at least one atom that contributes a constitution."


@dataclass
class ConstitutionAlreadyAdoptedError(HaexError):
    diagnostic_key: str = "constitution-already-adopted"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = (
        "Adopt only one constitution-contributing molecule, or combine the "
        "constitutions externally."
    )


@dataclass
class ConstitutionNotAssembledError(HaexError):
    diagnostic_key: str = "constitution-not-assembled"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Run `spaex install` first."


@dataclass
class InstallLockMissingError(HaexError):
    diagnostic_key: str = "install-lock-missing"
    exit_code: int = exit_codes.IO_REFUSE
    hint: str = "Run `spaex install` to (re)generate install.lock."


@dataclass
class InstallLockSchemaInvalidError(HaexError):
    diagnostic_key: str = "install-lock-schema-invalid"
    exit_code: int = exit_codes.VALIDATION_REFUSE
    hint: str = "Regenerate install.lock via `spaex install`."


@dataclass
class InstallLockGenerationInconsistentError(HaexError):
    """A read bracketed by `install.lock`'s `generation_id` still disagreed
    after one retry (research.md R9, FR-015): a concurrent `spaex install`
    kept publishing new generations faster than the read could complete."""

    diagnostic_key: str = "install-lock-generation-inconsistent"
    exit_code: int = exit_codes.IO_REFUSE
    hint: str = "Re-run the command; this is caused by a concurrent `spaex install`."


@dataclass
class PublisherCloneUnavailableError(HaexError):
    diagnostic_key: str = "publisher-clone-unavailable"
    exit_code: int = exit_codes.IO_REFUSE
    hint: str = "Ensure the publisher clone exists under $SPAEX_STATE/repos/."


@dataclass
class PinnedRevisionNotFoundError(HaexError):
    diagnostic_key: str = "pinned-revision-not-found"
    exit_code: int = exit_codes.IO_REFUSE
    hint: str = "Fetch the missing revision into the publisher clone."


@dataclass
class ContributionFileNotFoundError(HaexError):
    diagnostic_key: str = "contribution-file-not-found"
    exit_code: int = exit_codes.IO_REFUSE
    hint: str = "Verify the declared contribution path exists at the pinned revision."


@dataclass
class MoleculeTreePathNotFoundError(HaexError):
    diagnostic_key: str = "molecule-tree-path-not-found"
    exit_code: int = exit_codes.IO_REFUSE
    hint: str = (
        "Verify the molecule path exists in the publisher repository at the pinned revision."
    )


@dataclass
class MoleculeTreeExtractionError(HaexError):
    diagnostic_key: str = "molecule-tree-extraction-failed"
    exit_code: int = exit_codes.IO_REFUSE
    hint: str = (
        "Check the publisher repository is reachable and the local cache is writable; "
        "if the failure persists, the source content may be malformed."
    )


@dataclass
class PostWriteValidationError(HaexError):
    diagnostic_key: str = "post-write-validation-failed"
    exit_code: int = exit_codes.POST_WRITE_VALIDATION
    hint: str = "Investigate storage-layer corruption; both output files were rolled back."


@dataclass
class ConstitutionWriterBusyError(HaexError):
    diagnostic_key: str = "constitution-writer-busy"
    exit_code: int = exit_codes.WRITER_BUSY
    hint: str = "Another `spaex install` is running; retry after it releases the lock."


@dataclass
class PlaintextSecretDetectedError(HaexError):
    diagnostic_key: str = "plaintext-secret-detected"
    exit_code: int = exit_codes.PLAINTEXT_SECRET
    hint: str = "Remove the secret; commit no plaintext credentials."


@dataclass
class TerminalUnsafeContributionError(HaexError):
    diagnostic_key: str = "terminal-unsafe-contribution"
    exit_code: int = exit_codes.TERMINAL_UNSAFE_CONTRIBUTION
    hint: str = "Reject terminal control characters other than LF and TAB."


@dataclass
class ConstitutionConcealmentInstructionError(HaexError):
    diagnostic_key: str = "constitution-concealment-instruction"
    exit_code: int = exit_codes.CONSTITUTION_CONCEALMENT
    hint: str = "Reject candidates instructing agents to conceal or withhold information."


@dataclass
class UsageError(HaexError):
    diagnostic_key: str = "usage"
    exit_code: int = exit_codes.USAGE
    hint: str = ""


@dataclass
class SpeckitDeclarationInvalidError(HaexError):
    diagnostic_key: str = "speckit-declaration-invalid"
    exit_code: int = exit_codes.VALIDATION_REFUSE
    hint: str = "Repair the molecule's `speckit` declaration and retry."


@dataclass
class SpeckitCliMissingError(HaexError):
    diagnostic_key: str = "speckit-cli-missing"
    exit_code: int = exit_codes.SYSTEM_REFUSE
    hint: str = "Install the official Spec Kit CLI separately, then retry."


@dataclass
class SpeckitCliVersionIncompatibleError(HaexError):
    diagnostic_key: str = "speckit-cli-version-incompatible"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Use a `specify` CLI version satisfying the molecule declaration."


@dataclass
class SpeckitIntegrationUnsupportedError(HaexError):
    diagnostic_key: str = "speckit-integration-unsupported"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Select an integration reported by `specify integration list`."


@dataclass
class SpeckitSelectionRequiredError(HaexError):
    diagnostic_key: str = "speckit-selection-required"
    exit_code: int = exit_codes.USAGE
    hint: str = "Pass `--speckit-agents <keys>` or `--no-speckit-integrations`."


@dataclass
class SpeckitCliFailedError(HaexError):
    diagnostic_key: str = "speckit-cli-failed"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Inspect the official Spec Kit CLI output and retry."


@dataclass
class SpeckitDeclarationConflictError(HaexError):
    diagnostic_key: str = "speckit-declaration-conflict"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Adopt one compatible Spec Kit declaration per consumer project."


# --- Spec 013 spaex add / spaex remove boundary --------------------------------


@dataclass
class ManifestLockContendedError(HaexError):
    diagnostic_key: str = "manifest-lock-contended"
    exit_code: int = exit_codes.WRITER_BUSY
    hint: str = (
        "Another `spaex add`/`spaex remove`/`spaex install` holds the manifest "
        "lock; retry, or override with `--lock-timeout=<sec>`."
    )


@dataclass
class SourceUrlInvalidError(HaexError):
    diagnostic_key: str = "source-url-invalid"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Verify the source URL is reachable via git."


@dataclass
class RevisionNotFoundError(HaexError):
    diagnostic_key: str = "revision-not-found"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Verify the pinned SHA exists at the remote."


@dataclass
class PublisherManifestInvalidError(HaexError):
    diagnostic_key: str = "publisher-manifest-invalid"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "The relevant manifest.json must exist and validate against its v4 schema."


@dataclass
class PublisherManifestMissingError(HaexError):
    diagnostic_key: str = "publisher-manifest-missing"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = (
        "The resolved revision has no manifest.json at the publisher repo root."
    )


@dataclass
class MoleculeIdNotInSourceError(HaexError):
    diagnostic_key: str = "molecule-id-not-in-source"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "The publisher manifest does not list the requested molecule id."


@dataclass
class InteractiveSelectionUnavailableError(HaexError):
    diagnostic_key: str = "interactive-selection-unavailable"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Provide molecule ids explicitly or pass `--all`."


@dataclass
class WorkflowMoleculeAlreadyAdoptedError(HaexError):
    diagnostic_key: str = "workflow-molecule-already-adopted"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Retract the current workflow molecule with `spaex remove` before adopting another."


@dataclass
class UnknownMoleculeIdError(HaexError):
    diagnostic_key: str = "unknown-molecule-id"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "The molecule id is not adopted in `.spaex/manifest.json`."


@dataclass
class InstallTransactionFailedError(HaexError):
    diagnostic_key: str = "install-transaction-failed"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = (
        "The follow-on `spaex install` failed; the manifest edit was rolled back."
    )


@dataclass
class ManifestRollbackFailedError(HaexError):
    diagnostic_key: str = "manifest-rollback-failed"
    exit_code: int = exit_codes.POST_WRITE_VALIDATION
    hint: str = (
        "Restore `.spaex/manifest.json` from version control, then run `spaex install` again."
    )


# --- Spec 018 US3: consumer-controlled skill installation -------------------


@dataclass
class SkillInstallationCancelledError(HaexError):
    diagnostic_key: str = "skill-installation-cancelled"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "Re-run `spaex skills install` or `spaex skills configure` and answer every prompt."


@dataclass
class SkillInstallationPersistError(HaexError):
    diagnostic_key: str = "skill-installation-persist-failed"
    exit_code: int = exit_codes.IO_REFUSE
    hint: str = "Check `.spaex/manifest.json` permissions and retry; no adapter was invoked."


@dataclass
class SkillAdapterUnavailableError(HaexError):
    diagnostic_key: str = "skill-adapter-unavailable"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = (
        "Install the configured adapter on PATH, or `spaex skills configure` a different one."
    )


@dataclass
class SkillAdapterFailedError(HaexError):
    diagnostic_key: str = "skill-adapter-failed"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = "The adapter exited with an error; atom files and install.lock are unaffected."
