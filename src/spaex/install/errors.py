"""Install-specific `HaexError` subclasses (reserved for future stories).

The initial T017 shape of this module carried an `HaexInstallError` base and
five subclasses (`InstallLockBusy`, `IncompleteTransaction`,
`CommitSnapshotMismatch`, `OverlayUnsupported`, `SealMismatch`). Under the
2026-09-01 trust-git amendment and the 2026-09-02 detect+retry simplification
all five became dead code — no runtime raised them, no test caught them, and
the corresponding diagnostic keys are covered by the sibling classes in
`spaex.util.errors` (`ConstitutionWriterBusyError`,
`PostWriteValidationError`, and friends). They were removed under T055.

Future US2 fenced-lease diagnostics (T036) and Spec-010 mixed-ownership
adapter refusals will reintroduce specific subclasses here.
"""
