"""Materialize behavior fragments into a staging tree (Spec 023).

Consumes two fragment sources per molecule:

1. Standalone fragment files listed under the molecule manifest's `behavior`
   atom category. Read from the Spec 017 molecule store's on-disk directory
   (`molecule_store.get_or_extract` returns a real path the caller passes in).
2. Inline `constitution_fragments` blocks preserved on `MoleculeManifest` at
   parse time, keyed by enclosing typed-atom id.

Project-local fragments (Spec 023 FR-018) route through the same
materialization path under the synthetic molecule scope `_project`.

Everything is written to a caller-owned staging tree at
`<staging_root>/<molecule-id>/<fragment-id>.md`, never directly to
`.spaex/constitution.d/`. The install transaction (T029) publishes the
staging tree atomically after mechanical pre-check and Composer succeed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from spaex.behavior.fragment import PROJECT_SCOPE, BehaviorFragment, Modality
from spaex.behavior.precheck import precheck
from spaex.model.molecule_manifest import MoleculeManifest

BEHAVIOR_ATOM_CATEGORY = "behavior"


@dataclass(frozen=True)
class MoleculeInput:
    """One molecule's inputs to the materializer.

    `molecule_dir` is the real on-disk directory returned by
    `spaex.git.molecule_store.get_or_extract` for this molecule at its pinned
    revision. Standalone fragment files live at
    `<molecule_dir>/<manifest.atoms[behavior][i]>`.
    """

    molecule_id: str
    manifest: MoleculeManifest
    molecule_dir: Path


@dataclass(frozen=True)
class MaterializedFragment:
    """A fragment successfully written to the staging tree."""

    fragment: BehaviorFragment
    staging_path: Path
    dedup_provenance: tuple[BehaviorFragment, ...] = ()


def materialize(
    inputs: Sequence[MoleculeInput],
    *,
    staging_root: Path,
    project_local: Sequence[BehaviorFragment] = (),
) -> list[MaterializedFragment]:
    """Write every fragment for every molecule into the staging tree.

    Returns the list of `MaterializedFragment` in a stable order: by
    molecule_id, then fragment_id, with project-local fragments last under
    the `_project` scope. Callers use the return value both for the
    mechanical pre-check (T014) and for Composer input.
    """
    fragments: list[BehaviorFragment] = []
    ordered_inputs = sorted(inputs, key=lambda mi: mi.molecule_id)
    for mi in ordered_inputs:
        fragments.extend(_fragments_from_molecule(mi))

    for fragment in sorted(project_local, key=lambda f: f.id):
        if fragment.molecule_id != PROJECT_SCOPE:
            raise ValueError(
                f"project-local fragment {fragment.id!r} has molecule_id "
                f"{fragment.molecule_id!r}; must be {PROJECT_SCOPE!r}"
            )
        fragments.append(fragment)

    outcome = precheck(fragments)
    staging_root.mkdir(parents=True, exist_ok=True)
    dedup_provenance = outcome.dedup_provenance
    materialized: list[MaterializedFragment] = []
    for fragment in outcome.fragments:
        path = _write_fragment(fragment, staging_root=staging_root)
        materialized.append(
            MaterializedFragment(
                fragment=fragment,
                staging_path=path,
                dedup_provenance=dedup_provenance.get(fragment.scoped_id, ()),
            )
        )

    return materialized


def _fragments_from_molecule(mi: MoleculeInput) -> Iterable[BehaviorFragment]:
    """Yield fragments contributed by one molecule (standalone + inline)."""
    behavior_paths = mi.manifest.atoms.get(BEHAVIOR_ATOM_CATEGORY, ())
    for rel in behavior_paths:
        source = mi.molecule_dir / rel
        yield BehaviorFragment.from_file(source, molecule_id=mi.molecule_id)

    for atom_id, entries in mi.manifest.constitution_fragments.items():
        for idx, entry in enumerate(entries):
            path_hint = f"{mi.molecule_id} constitution_fragments[{atom_id!r}][{idx}]"
            yield BehaviorFragment.from_inline(
                entry,
                molecule_id=mi.molecule_id,
                enclosing_atom_id=atom_id,
                path=path_hint,
            )


def _write_fragment(
    fragment: BehaviorFragment, *, staging_root: Path
) -> Path:
    """Write one fragment to `<staging_root>/<molecule-id>/<fragment-id>.md`."""
    target_dir = staging_root / fragment.molecule_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{fragment.id}.md"
    target.write_text(_render_fragment_file(fragment), encoding="utf-8")
    return target


def _render_fragment_file(fragment: BehaviorFragment) -> str:
    """Rebuild the on-disk fragment file for a BehaviorFragment.

    Uses a small hand-rolled YAML serializer (six known fields, all safe
    strings or a list of tag strings) instead of a full YAML dumper to keep
    the output stable and byte-identical across runs (SC-003 reproducibility).
    """
    lines: list[str] = ["---"]
    lines.append(f"id: {_yaml_str(fragment.id)}")
    lines.append(f"kind: {_yaml_str(fragment.kind)}")
    lines.append(f"atom_source: {_yaml_str(fragment.atom_source)}")
    if fragment.modality is not None:
        lines.append(f"modality: {_yaml_str(fragment.modality.value)}")
    if fragment.tags:
        rendered_tags = ", ".join(_yaml_str(tag) for tag in fragment.tags)
        lines.append(f"tags: [{rendered_tags}]")
    lines.append("---")
    header = "\n".join(lines) + "\n"
    body = fragment.body if fragment.body.endswith("\n") else fragment.body + "\n"
    return header + body


def _yaml_str(value: str) -> str:
    """Emit a YAML string that round-trips through yaml.safe_load unchanged.

    Fragment header strings are ASCII-ish (ids, atom sources, tags). Values
    with YAML-special characters get quoted; safe values render bare.
    """
    if not value:
        return "''"
    needs_quote = any(ch in value for ch in ": #[]{}\"'\n\t,")
    if not needs_quote:
        try:
            needs_quote = yaml.safe_load(value) != value
        except yaml.YAMLError:
            needs_quote = True
    if needs_quote:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def project_local_from_config(
    entries: Iterable[Mapping[str, Any]],
    *,
    repo_root: Path | None = None,
    path: str = ".spaex/manifest.json:constitution.local_fragments",
) -> list[BehaviorFragment]:
    """Parse `.spaex/manifest.json`'s `constitution.local_fragments[]` entries (T044).

    Each entry is either inline (a full fragment: `id`/`body`/... per
    contracts/fragment-format.md, distinguished by a `body` key) or a
    file-reference (`{"file": "<repo-relative-path>"}`, distinguished by a
    `file` key) resolved against `repo_root`. `repo_root` is required only
    when a file-reference entry is present.
    """
    fragments: list[BehaviorFragment] = []
    for idx, entry in enumerate(entries):
        entry_path = f"{path}[{idx}]"
        if "file" in entry:
            if repo_root is None:
                raise ValueError(
                    f"{entry_path}: file-reference local fragment requires repo_root"
                )
            repo_root_resolved = repo_root.resolve()
            candidate = (repo_root / str(entry["file"])).resolve()
            if not candidate.is_relative_to(repo_root_resolved):
                raise ValueError(
                    f"{entry_path}: file-reference escapes repository root"
                )
            fragments.append(
                BehaviorFragment.from_file(
                    candidate, molecule_id=PROJECT_SCOPE
                )
            )
            continue
        atom_source = str(entry.get("atom_source", PROJECT_SCOPE))
        fragments.append(
            BehaviorFragment.from_inline(
                entry,
                molecule_id=PROJECT_SCOPE,
                enclosing_atom_id=atom_source,
                path=entry_path,
            )
        )
    return fragments


__all__ = [
    "BEHAVIOR_ATOM_CATEGORY",
    "MaterializedFragment",
    "Modality",
    "MoleculeInput",
    "materialize",
    "project_local_from_config",
]
