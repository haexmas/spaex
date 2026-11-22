"""`spaex constitution trace <query>` (T057, FR-022, SC-006; reworked by Spec 030 R11).

Query modes on a format version 2 constitution:

1. An exact scoped fragment id (`<molecule-id>/<fragment-id>`): the fragment's block.
2. A molecule id: every block of that molecule.
3. A phrase from a fragment: the lines that contain it, with their file line
   and whether the line lies inside an excluded passage.

...plus the explicit exit-1 cases: a bare (unscoped) fragment id is rejected as
ambiguous, and a missing `.spaex/constitution.md`, a file that is not version 2,
or a genuinely-absent phrase all report "no match". Both `--format text` and
`--format json` are exercised.

No git/molecule resolution is needed: `constitution trace` reads
`.spaex/constitution.md`, `.spaex/constitution.d/` and `.spaex/manifest.json`
directly off disk, so fixtures are hand-written.
"""

from __future__ import annotations

import json
from pathlib import Path

from spaex.behavior.decisions import Choice, Decision, PassageRef
from spaex.behavior.fragment import Modality
from spaex.behavior.passages import finding_key, text_hash
from spaex.cli.main import main

from ._composed import fragment, write_composed

_STRICT = "com.example.strict-testing"
_RULE = "**MUST** run the project's test suite before creating any commit.\n"


def _write_manifest(repo: Path, *, compounds: list[dict[str, object]]) -> None:
    (repo / ".spaex").mkdir(parents=True, exist_ok=True)
    (repo / ".spaex/manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.trace-consumer",
                "compounds": compounds,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _make_fixture(tmp_path: Path) -> Path:
    """One molecule, one fragment: `com.example.strict-testing/tests-before-commit`."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    write_composed(
        repo,
        [
            fragment(
                _STRICT,
                "tests-before-commit",
                _RULE,
                atom_source="hooks.test-runner",
                modality=Modality.MUST,
            )
        ],
    )
    _write_manifest(
        repo,
        compounds=[
            {
                "source": "https://github.com/haexmas/atoms",
                "revision": "a" * 40,
                "molecules": [_STRICT],
            }
        ],
    )
    return repo


def test_trace_exact_scoped_id_text_format(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(["--repo-root", str(repo), "constitution", "trace", f"{_STRICT}/tests-before-commit"])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"Fragment: {_STRICT}/tests-before-commit" in out
    assert "Modality: MUST" in out
    assert "of .spaex/constitution.md" in out
    assert "Atom:     hooks.test-runner" in out
    assert (
        f"Molecule: https://github.com/haexmas/atoms@{'a' * 40} "
        "(pinned in .spaex/manifest.json)" in out
    )


def test_trace_reports_the_line_range_of_the_block(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(
        [
            "--repo-root",
            str(repo),
            "constitution",
            "trace",
            f"{_STRICT}/tests-before-commit",
            "--format",
            "json",
        ]
    )
    record = json.loads(capsys.readouterr().out)["matches"][0]
    assert rc == 0
    start, end = record["lines"]
    lines = (repo / ".spaex/constitution.md").read_text().split("\n")
    assert lines[start - 1] == _RULE.strip()
    assert lines[end] == "<!-- /spaex-fragment -->"


def test_trace_phrase_names_fragment_and_line(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(["--repo-root", str(repo), "constitution", "trace", "test suite before creating"])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"{_STRICT}/tests-before-commit" in out
    assert "Line:" in out
    assert "test suite before creating" in out


def test_trace_molecule_id_lists_every_block(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    write_composed(
        repo,
        [
            fragment(_STRICT, "tests-before-commit", _RULE, atom_source="hooks.test-runner"),
            fragment(_STRICT, "small-commits", "**SHOULD** prefer small commits.\n"),
            fragment("com.example.other", "x", "other rule\n"),
        ],
    )
    rc = main(["--repo-root", str(repo), "constitution", "trace", _STRICT])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"{_STRICT}/tests-before-commit" in out
    assert f"{_STRICT}/small-commits" in out
    assert "com.example.other/x" not in out


def test_trace_bare_fragment_id_rejected_as_ambiguous(tmp_path: Path, capsys) -> None:
    """A bare `<fragment-id>` (no molecule scope) is refused, not treated as a
    phrase, even when it happens to be unique today (FR-022)."""
    repo = _make_fixture(tmp_path)
    rc = main(["--repo-root", str(repo), "constitution", "trace", "tests-before-commit"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "ambiguous" in out
    assert "<molecule-id>/<fragment-id>" in out


def test_trace_unknown_scoped_id_falls_back_to_phrase_search(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(
        ["--repo-root", str(repo), "constitution", "trace", "no-such-molecule/no-such-fragment"]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "no fragment matches" in out


def test_trace_no_match(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(["--repo-root", str(repo), "constitution", "trace", "zzz-nonexistent-zzz"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no fragment matches" in out


def test_trace_missing_spaex_md(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    rc = main(["--repo-root", str(repo), "constitution", "trace", "anything"])
    out = capsys.readouterr().out
    assert rc == 1
    assert ".spaex/constitution.md" in out


def test_trace_finds_nothing_in_a_version_1_file(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    (repo / ".spaex").mkdir(parents=True)
    (repo / ".spaex/constitution.md").write_text(
        '<!-- spaex-composed:source_hash="'
        + "a" * 64
        + '" build_input_hash="'
        + "b" * 64
        + '" version="1" -->\n# spaex Behavior Harness\n',
        encoding="utf-8",
    )
    rc = main(["--repo-root", str(repo), "constitution", "trace", "x"])
    out = capsys.readouterr().out
    assert rc == 1
    assert out.strip()  # a message, not a crash; no fragment can be traced from a v1 file


def test_trace_json_format(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(
        [
            "--repo-root",
            str(repo),
            "constitution",
            "trace",
            f"{_STRICT}/tests-before-commit",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert len(payload["matches"]) == 1
    match = payload["matches"][0]
    assert match["modality"] == "MUST"
    assert match["exclusions"] == []
    source = match["source"]
    assert source["scoped_id"] == f"{_STRICT}/tests-before-commit"
    assert source["atom_source"] == "hooks.test-runner"
    assert source["molecule_source"] == "https://github.com/haexmas/atoms"
    assert source["molecule_revision"] == "a" * 40
    assert source["pinned_in"] == ".spaex/manifest.json"


def test_trace_json_no_match_reports_error(tmp_path: Path, capsys) -> None:
    repo = _make_fixture(tmp_path)
    rc = main(
        [
            "--repo-root",
            str(repo),
            "constitution",
            "trace",
            "zzz-nonexistent-zzz",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["matches"] == []
    assert payload["error"]


def test_trace_two_molecules_with_the_same_fragment_id(tmp_path: Path, capsys) -> None:
    """Both blocks are traceable by scoped id; the shared bare id is ambiguous."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    write_composed(
        repo,
        [
            fragment(_STRICT, "tests-before-commit", _RULE, atom_source="hooks.test-runner"),
            fragment(
                "com.example.qa-baseline",
                "tests-before-commit",
                "run the tests before every commit\n",
                atom_source="qa.tests-before-commit",
            ),
        ],
    )
    _write_manifest(
        repo,
        compounds=[
            {
                "source": "https://github.com/haexmas/atoms",
                "revision": "a" * 40,
                "molecules": [_STRICT],
            },
            {
                "source": "https://github.com/haexmas/qa-atoms",
                "revision": "b" * 40,
                "molecules": ["com.example.qa-baseline"],
            },
        ],
    )
    for scoped, atom, source in (
        (f"{_STRICT}/tests-before-commit", "hooks.test-runner", "atoms@" + "a" * 40),
        (
            "com.example.qa-baseline/tests-before-commit",
            "qa.tests-before-commit",
            "qa-atoms@" + "b" * 40,
        ),
    ):
        rc = main(["--repo-root", str(repo), "constitution", "trace", scoped])
        out = capsys.readouterr().out
        assert rc == 0
        assert f"Fragment: {scoped}" in out
        assert f"Atom:     {atom}" in out
        assert f"https://github.com/haexmas/{source}" in out
    rc = main(["--repo-root", str(repo), "constitution", "trace", "tests-before-commit"])
    assert rc == 1
    assert "ambiguous" in capsys.readouterr().out


def test_trace_project_local_source(tmp_path: Path, capsys) -> None:
    """A project-local fragment has no pinned molecule; the Molecule line names it so."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    write_composed(
        repo,
        [
            fragment(
                "_project",
                "small-commits",
                "**SHOULD** prefer small commits.\n",
                atom_source="_project",
            )
        ],
    )
    _write_manifest(repo, compounds=[])
    rc = main(["--repo-root", str(repo), "constitution", "trace", "_project/small-commits"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "project-local" in out


def test_trace_marks_excluded_passages_and_lines_inside_them(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    kept = fragment("m", "a", "intro\nalways use tabs\n")
    other = fragment("m", "b", "alpha\nnever use tabs\nomega\n")
    refs = (
        PassageRef("m/a", text_hash("always use tabs"), "always use tabs"),
        PassageRef("m/b", text_hash("never use tabs"), "never use tabs"),
    )
    decision = Decision(
        key=finding_key([(r.scoped_id, r.text_hash) for r in refs]),
        kind="contradiction",
        summary="s",
        passages=refs,
        choice=Choice(kind="keep", kept=0),
        asked_at="t",
        answered_at="t",
    )
    write_composed(repo, [kept, other], [decision])
    _write_manifest(repo, compounds=[])

    rc = main(["--repo-root", str(repo), "constitution", "trace", "m/b", "--format", "json"])
    record = json.loads(capsys.readouterr().out)["matches"][0]
    assert rc == 0
    assert [e["kept"] for e in record["exclusions"]] == [["m/a:2-2"]]

    rc = main(
        ["--repo-root", str(repo), "constitution", "trace", "never use tabs", "--format", "json"]
    )
    hit = json.loads(capsys.readouterr().out)["matches"][0]
    assert rc == 0
    assert hit["excluded"] is True
    assert hit["kept"] == ["m/a:2-2"]

    rc = main(["--repo-root", str(repo), "constitution", "trace", "omega", "--format", "json"])
    outside = json.loads(capsys.readouterr().out)["matches"][0]
    assert outside["excluded"] is False
