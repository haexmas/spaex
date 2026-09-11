"""Mechanical pre-check for a materialized fragment set (Spec 023).

Operates on a list of parsed `BehaviorFragment` instances (produced by
`spaex.behavior.materialize`) and rejects three intra-molecule conflict
classes plus one project-local additive-only violation. Cross-molecule
semantic contradictions are the Composer's job (FR-005a) and are out of
scope here.

Conflict classes (from contracts/fragment-format.md §Validation errors):

- `duplicate-id` — two fragments same molecule same id, different modality:
  REJECT with exit code 20.
- `duplicate-id-body-mismatch` — two fragments same molecule same id and
  modality, but different normalized bodies: REJECT with exit code 20.
- `duplicate-id-same-modality` (identical normalized bodies): silent
  dedupe; extra producers are recorded in the dedup provenance table.
- Project-local override (FR-020): a `_project/<fragment-id>` whose bare
  `fragment_id` matches any atom-provided `<molecule-id>/<fragment-id>`
  triggers REJECT with exit code 22.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from spaex.behavior.fragment import (
    PROJECT_SCOPE,
    BehaviorFragment,
    FragmentValidationError,
)
from spaex.util import exit_codes
from spaex.util.errors import HaexError


@dataclass
class IntraMoleculeCollisionError(HaexError):
    diagnostic_key: str = "behavior-precheck-intra-molecule-collision"
    exit_code: int = exit_codes.BEHAVIOR_PRECHECK_REFUSE
    hint: str = (
        "Fix the offending molecule: two fragments with the same id "
        "carry contradictory modalities."
    )


@dataclass
class DuplicateBodyMismatchError(HaexError):
    diagnostic_key: str = "behavior-precheck-body-mismatch"
    exit_code: int = exit_codes.BEHAVIOR_PRECHECK_REFUSE
    hint: str = (
        "Two fragments share id and modality but disagree on body. "
        "Reconcile them at the molecule source; the pre-check does not pick."
    )


@dataclass
class MalformedFragmentError(HaexError):
    diagnostic_key: str = "behavior-precheck-malformed-fragment"
    exit_code: int = exit_codes.BEHAVIOR_PRECHECK_REFUSE
    hint: str = (
        "Fix the fragment file so it parses per contracts/fragment-format.md."
    )


@dataclass
class ProjectLocalOverrideError(HaexError):
    diagnostic_key: str = "behavior-precheck-project-local-override"
    exit_code: int = exit_codes.BEHAVIOR_PROJECT_LOCAL_REFUSE
    hint: str = (
        "Project-local fragments are additive only. Remove the offending "
        "molecule or pick a different local id; do not shadow an "
        "atom-provided fragment id."
    )


@dataclass(frozen=True)
class PrecheckOutcome:
    """Deduped, canonically ordered fragment list ready for the Composer.

    `fragments` is sorted by `scoped_id` for reproducibility.
    `dedup_provenance` records the extra producers a silent-dedup merge
    kept for provenance emission (data-model.md §Composed Clause).
    """

    fragments: tuple[BehaviorFragment, ...] = ()
    dedup_provenance: dict[str, tuple[BehaviorFragment, ...]] = field(
        default_factory=dict
    )


def precheck(fragments: Sequence[BehaviorFragment]) -> PrecheckOutcome:
    """Run every mechanical pre-check and return a canonical result.

    Raises on first hard conflict; there is no partial-success mode. All
    intra-molecule conflicts are reported before any project-local override
    is examined, because collision diagnostics inside a molecule are
    author-fixable without the operator changing their pin set.
    """
    _require_all_parsed(fragments)

    groups: dict[tuple[str, str], list[BehaviorFragment]] = defaultdict(list)
    for fragment in fragments:
        groups[(fragment.molecule_id, fragment.id)].append(fragment)

    deduped: list[BehaviorFragment] = []
    dedup_provenance: dict[str, tuple[BehaviorFragment, ...]] = {}

    for (molecule_id, fragment_id), members in groups.items():
        _check_intra_molecule_modality_collision(members)
        canonical, extras = _dedupe_by_normalized_body(members)
        deduped.append(canonical)
        if extras:
            dedup_provenance[canonical.scoped_id] = tuple(extras)

    _enforce_project_local_additive_only(deduped)

    deduped.sort(key=lambda f: f.scoped_id)
    return PrecheckOutcome(
        fragments=tuple(deduped), dedup_provenance=dedup_provenance
    )


def _require_all_parsed(fragments: Sequence[BehaviorFragment]) -> None:
    """Reject anything that is not a `BehaviorFragment`.

    Parsing errors are supposed to be raised by
    `BehaviorFragment.from_bytes`/`from_file`/`from_inline` before precheck
    runs. This guard exists so a caller who bypasses the parser (e.g. hands
    us dictionaries) gets a typed diagnostic rather than an AttributeError.
    """
    for idx, fragment in enumerate(fragments):
        if not isinstance(fragment, BehaviorFragment):
            raise MalformedFragmentError(
                message=(
                    f"fragment #{idx} is not a BehaviorFragment "
                    f"(got {type(fragment).__name__}); parse it first "
                    "via BehaviorFragment.from_bytes/from_file/from_inline"
                ),
                context={"index": str(idx)},
            )


def _check_intra_molecule_modality_collision(
    members: list[BehaviorFragment],
) -> None:
    modalities = {m.modality for m in members}
    if len(modalities) > 1:
        details = ", ".join(
            f"{m.molecule_id}/{m.id}@{m.atom_source} modality={m.modality}"
            for m in members
        )
        raise IntraMoleculeCollisionError(
            message=(
                f"molecule {members[0].molecule_id!r} declares fragment "
                f"{members[0].id!r} with contradictory modalities: {details}"
            ),
            context={
                "molecule_id": members[0].molecule_id,
                "fragment_id": members[0].id,
            },
        )


def _dedupe_by_normalized_body(
    members: list[BehaviorFragment],
) -> tuple[BehaviorFragment, list[BehaviorFragment]]:
    """Return (canonical fragment, extra producers).

    Order-independent: sorts members by `atom_source` first so the
    "canonical" pick is stable across install runs (SC-003).
    """
    ordered = sorted(members, key=lambda m: (m.atom_source, id(m)))
    canonical = ordered[0]
    canonical_hash = canonical.body_hash
    extras: list[BehaviorFragment] = []
    for member in ordered[1:]:
        if member.body_hash != canonical_hash:
            raise DuplicateBodyMismatchError(
                message=(
                    f"molecule {canonical.molecule_id!r} declares fragment "
                    f"{canonical.id!r} twice under modality "
                    f"{canonical.modality} with different normalized bodies: "
                    f"{canonical.atom_source} vs {member.atom_source}"
                ),
                context={
                    "molecule_id": canonical.molecule_id,
                    "fragment_id": canonical.id,
                    "canonical_atom_source": canonical.atom_source,
                    "duplicate_atom_source": member.atom_source,
                },
            )
        extras.append(member)
    return canonical, extras


def _enforce_project_local_additive_only(
    fragments: list[BehaviorFragment],
) -> None:
    """Reject `_project/<id>` whose bare id matches any atom-provided id."""
    atom_ids_by_bare: dict[str, list[str]] = defaultdict(list)
    for fragment in fragments:
        if fragment.molecule_id != PROJECT_SCOPE:
            atom_ids_by_bare[fragment.id].append(fragment.scoped_id)

    for fragment in fragments:
        if fragment.molecule_id != PROJECT_SCOPE:
            continue
        matches = atom_ids_by_bare.get(fragment.id, [])
        if matches:
            names = ", ".join(sorted(matches))
            raise ProjectLocalOverrideError(
                message=(
                    f"project-local fragment {fragment.id!r} shadows "
                    f"atom-provided fragment(s): {names}. Project-local "
                    "fragments are additive only (FR-020)."
                ),
                context={
                    "fragment_id": fragment.id,
                    "atom_matches": ";".join(sorted(matches)),
                },
            )


__all__ = [
    "DuplicateBodyMismatchError",
    "FragmentValidationError",
    "IntraMoleculeCollisionError",
    "MalformedFragmentError",
    "PrecheckOutcome",
    "ProjectLocalOverrideError",
    "precheck",
]
