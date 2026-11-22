"""Fragment factory shared by the spec 030 unit tests."""

from __future__ import annotations

from spaex.behavior.fragment import BehaviorFragment, Modality


def make_fragment(
    molecule: str,
    fragment: str,
    body: str,
    *,
    modality: Modality | None = None,
) -> BehaviorFragment:
    return BehaviorFragment(
        id=fragment,
        kind="constitution_fragment",
        atom_source=fragment,
        modality=modality,
        tags=(),
        body=body,
        molecule_id=molecule,
    )
