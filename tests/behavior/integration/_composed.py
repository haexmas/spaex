"""Helpers for tests that need a hand-made version 2 composed constitution (Spec 030)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from spaex.behavior.decisions import Checked, Decision
from spaex.behavior.fragment import BehaviorFragment, Modality
from spaex.behavior.state import expected_text


def fragment(
    molecule: str,
    fragment_id: str,
    body: str,
    *,
    atom_source: str | None = None,
    modality: Modality | None = None,
) -> BehaviorFragment:
    return BehaviorFragment(
        id=fragment_id,
        kind="constitution_fragment",
        atom_source=atom_source or fragment_id,
        modality=modality,
        tags=(),
        body=body,
        molecule_id=molecule,
    )


def write_fragment_file(repo: Path, item: BehaviorFragment) -> None:
    """Write `.spaex/constitution.d/<molecule>/<id>.md` the way install does."""
    target = repo / ".spaex" / "constitution.d" / item.molecule_id
    target.mkdir(parents=True, exist_ok=True)
    header = (
        f"---\nid: {item.id}\nkind: constitution_fragment\natom_source: {item.atom_source}\n"
        + (f"modality: {item.modality.value}\n" if item.modality else "")
        + "---\n"
    )
    (target / f"{item.id}.md").write_bytes((header + item.body).encode("utf-8"))


def write_composed(
    repo: Path,
    fragments: Sequence[BehaviorFragment],
    decisions: Sequence[Decision] = (),
) -> str:
    """Render and write `.spaex/constitution.md` plus the fragment files; return the text."""
    for item in fragments:
        write_fragment_file(repo, item)
    text = expected_text(fragments, decisions)
    (repo / ".spaex").mkdir(parents=True, exist_ok=True)
    (repo / ".spaex" / "constitution.md").write_bytes(text.encode("utf-8"))
    return text


def write_current(
    repo: Path,
    fragments: Sequence[BehaviorFragment],
    decisions: Sequence[Decision] = (),
) -> str:
    """Like `write_composed`, plus a `decisions.json` that records a completed check.

    The result is what a finished `spaex install` leaves behind, so `status` and
    `constitution build --check` call it current.
    """
    from spaex.behavior.decisions import DECISIONS_FILENAME, DecisionStore, save
    from spaex.behavior.state import assess

    text = write_composed(repo, fragments, decisions)
    spaex_dir = repo / ".spaex"
    assessment = assess(fragments, repo_root=repo, spaex_dir=spaex_dir)
    store = DecisionStore(decisions={d.key: d for d in decisions}).with_checked(
        Checked(assessment.fingerprint, assessment.prompt_hash)
    )
    save(spaex_dir / DECISIONS_FILENAME, store)
    return text
