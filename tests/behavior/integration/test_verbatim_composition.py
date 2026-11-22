"""The composed constitution carries every fragment verbatim (spec 030 T010, US1, SC-001).

These tests drive `orchestrate.run` with hand-built `ResolvedMolecule` records
(`cache_dir`/`molecule_manifest` populated directly, no git clone needed) and the
`stub_check` fixture, so the property under test - what spaex writes - does not
depend on the resolver or on a model.
"""

from __future__ import annotations

from pathlib import Path

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior.fragment import PROJECT_SCOPE, BehaviorFragment, Modality
from spaex.behavior.render import parse
from spaex.constitution.resolve import ResolvedMolecule
from spaex.model.molecule_manifest import MoleculeManifest

from ..conftest import StubCheck

RULES = "".join(f"- **MUST** follow rule number {n}.\n" for n in range(1, 33))

STRUCTURED = (
    "# Principle: structure survives\n"
    "\n"
    "Intro line with trailing spaces.  \n"
    "\n"
    "## Rules\n"
    "\n"
    "1. first\n"
    "2. second\n"
    "   - nested bullet\n"
    "\n"
    "```sh\n"
    "$ nix develop --command pnpm test\n"
    "```\n"
    "\n"
    "> a quote\n"
    "\n"
    "| a | b |\n"
    "| - | - |\n"
    "| 1 | 2 |\n"
    "\n"
    "\n"
)


def _molecule(
    cache_root: Path, mol_id: str, fragments: dict[str, tuple[str, str]]
) -> ResolvedMolecule:
    """A resolved molecule with one fragment file per `{fragment id: (modality, body)}`."""
    cache_dir = cache_root / mol_id
    (cache_dir / "fragments").mkdir(parents=True)
    for fragment_id, (modality, body) in fragments.items():
        (cache_dir / "fragments" / f"{fragment_id}.md").write_bytes(
            (
                f"---\nid: {fragment_id}\nkind: constitution_fragment\n"
                f"atom_source: pkg.{fragment_id}\nmodality: {modality}\n---\n{body}"
            ).encode()
        )
    manifest = MoleculeManifest(
        spaex_version="4",
        id=mol_id,
        version="1.0.0",
        priority=20,
        atoms={"behavior": tuple(f"fragments/{fid}.md" for fid in fragments)},
    )
    return ResolvedMolecule(
        molecule_id=mol_id,
        source_url="https://example.invalid/fixture",
        revision="0" * 40,
        repo_dir=cache_root,
        molecule_path=mol_id,
        install_hook=None,
        effective_priority=20,
        molecule_manifest=manifest,
        cache_dir=cache_dir,
    )


def _run(
    tmp_path: Path,
    resolved: list[ResolvedMolecule],
    **kwargs: object,
) -> tuple[behavior_orchestrate.BehaviorOutcome, str]:
    repo = tmp_path / "repo"
    (repo / ".spaex").mkdir(parents=True, exist_ok=True)
    outcome = behavior_orchestrate.run(
        repo_root=repo, state_root=tmp_path / "state", resolved=resolved, **kwargs
    )
    return outcome, (repo / ".spaex" / "constitution.md").read_text(encoding="utf-8")


def test_a_32_rule_fragment_arrives_byte_for_byte(
    tmp_path: Path, stub_check: StubCheck
) -> None:
    resolved = [_molecule(tmp_path / "cache", "big", {"rules": ("MUST", RULES)})]

    outcome, text = _run(tmp_path, resolved)

    assert outcome.published
    (block,) = parse(text).blocks
    assert block.scoped_id == "big/rules"
    assert block.body == RULES, "all 32 rules, unchanged"
    assert block.body.count("\n") == 32
    # The body sits between its two boundary comments exactly as written.
    assert (
        '<!-- spaex-fragment id="big/rules" modality="MUST" -->\n'
        + RULES
        + "<!-- /spaex-fragment -->\n"
    ) in text


def test_every_fragment_appears_exactly_once_in_scoped_id_order(
    tmp_path: Path, stub_check: StubCheck
) -> None:
    cache = tmp_path / "cache"
    resolved = [
        _molecule(cache, "zeta", {"last": ("SHOULD", "z\n")}),
        _molecule(cache, "alpha", {"b-rule": ("MUST", "b\n"), "a-rule": ("MAY", "a\n")}),
    ]

    _outcome, text = _run(tmp_path, resolved)

    ids = [block.scoped_id for block in parse(text).blocks]
    assert ids == ["alpha/a-rule", "alpha/b-rule", "zeta/last"]
    for scoped_id in ids:
        assert text.count(f'<!-- spaex-fragment id="{scoped_id}"') == 1
    assert text.count("<!-- /spaex-fragment -->") == 3
    # The version 2 file has neither modality sections nor clause bullets.
    assert "\n## MUST" not in text
    assert "_[from `" not in text


def test_headings_lists_code_and_whitespace_are_unchanged(
    tmp_path: Path, stub_check: StubCheck
) -> None:
    resolved = [_molecule(tmp_path / "cache", "doc", {"structured": ("MUST", STRUCTURED)})]

    _outcome, text = _run(tmp_path, resolved)

    (block,) = parse(text).blocks
    assert block.body == STRUCTURED, "trailing spaces and trailing blank lines are kept"
    assert "  \n" in block.body
    assert block.body.endswith("\n\n\n")


def test_crlf_is_the_only_thing_that_changes(tmp_path: Path, stub_check: StubCheck) -> None:
    body = "- one  \r\n- two\r\n\r\n"
    resolved = [_molecule(tmp_path / "cache", "win", {"crlf": ("MUST", body)})]

    _outcome, text = _run(tmp_path, resolved)

    (block,) = parse(text).blocks
    assert block.body == "- one  \n- two\n\n"
    assert "\r" not in text


def test_a_project_local_fragment_is_included(tmp_path: Path, stub_check: StubCheck) -> None:
    resolved = [_molecule(tmp_path / "cache", "alpha", {"rule": ("MUST", "from a molecule\n")})]
    local = BehaviorFragment(
        id="house-rule",
        kind="constitution_fragment",
        atom_source="project",
        modality=Modality.SHOULD,
        tags=(),
        body="**SHOULD** keep the house tidy.\n",
        molecule_id=PROJECT_SCOPE,
    )

    _outcome, text = _run(tmp_path, resolved, project_local=(local,))

    blocks = {block.scoped_id: block for block in parse(text).blocks}
    assert set(blocks) == {"alpha/rule", f"{PROJECT_SCOPE}/house-rule"}
    assert blocks[f"{PROJECT_SCOPE}/house-rule"].body == "**SHOULD** keep the house tidy.\n"
    assert blocks[f"{PROJECT_SCOPE}/house-rule"].modality == "SHOULD"
    assert (tmp_path / "repo" / ".spaex" / "constitution.d" / "_project" / "house-rule.md").exists()


def test_the_preamble_follows_the_notices_before_the_first_block(
    tmp_path: Path, stub_check: StubCheck
) -> None:
    """Spec 029: the local document's preamble sits after the title and notices (contract v2)."""
    resolved = [_molecule(tmp_path / "cache", "alpha", {"rule": ("MUST", "body\n")})]
    preamble = "<!-- local rules; project rules prevail on conflict -->\n"

    _outcome, text = _run(tmp_path, resolved, preamble=preamble)

    lines = text.split("\n")
    assert lines[0].startswith("<!-- spaex-composed:")
    assert lines[1] == "# spaex Behavior Harness"
    position = lines.index(preamble.rstrip("\n"))
    assert position > 1
    assert lines[position - 1] == "", "separated from the notices by a blank line"
    assert lines[position + 1] == ""
    assert lines[position + 2].startswith('<!-- spaex-fragment id="alpha/rule"')
    (block,) = parse(text).blocks
    assert block.body == "body\n"


def test_the_composed_file_names_no_check_data(tmp_path: Path, stub_check: StubCheck) -> None:
    """FR-003: nothing about the check (prompt, state, findings) reaches the text."""
    resolved = [_molecule(tmp_path / "cache", "alpha", {"rule": ("MUST", "body\n")})]

    _outcome, first = _run(tmp_path, resolved)
    (tmp_path / "repo" / ".spaex" / "check-prompt.md").write_text("a different check prompt\n")
    _outcome, second = _run(tmp_path, resolved)

    assert stub_check.calls == 2, "the changed prompt re-runs the check"
    assert first == second
