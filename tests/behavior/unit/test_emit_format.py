"""Emit unit tests (Spec 023 T028, reworked for Spec 030).

Covers:

- `source_hash` reproducibility across fragment-input order and its sensitivity
  to body, modality and whitespace-insensitive normalization.
- `emit_rendered`: atomic write, identical file left alone.
- Empty-set behavior (FR-017d): `remove_if_exists`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from spaex.behavior.emit import (
    SPAEX_MD_FILENAME,
    compute_source_hash,
    emit_rendered,
    remove_if_exists,
)
from spaex.behavior.fragment import BehaviorFragment, Modality


def _fragment(molecule: str, fid: str, body: str = "**MUST** run tests.\n") -> BehaviorFragment:
    raw = (
        f"---\nid: {fid}\nkind: constitution_fragment\n"
        f"atom_source: pkg.a\nmodality: MUST\n---\n{body}"
    ).encode()
    return BehaviorFragment.from_bytes(raw, molecule_id=molecule, path=f"{molecule}/{fid}.md")


def test_source_hash_is_input_order_independent() -> None:
    a = _fragment("alpha", "rule-a", body="**MUST** run a.\n")
    b = _fragment("beta", "rule-b", body="**MUST** run b.\n")
    forward = compute_source_hash([a, b])
    reverse = compute_source_hash([b, a])
    assert forward == reverse


def test_source_hash_differs_when_body_changes() -> None:
    a1 = _fragment("alpha", "rule-a", body="**MUST** run a.\n")
    a2 = _fragment("alpha", "rule-a", body="**MUST** run a. And b.\n")
    assert compute_source_hash([a1]) != compute_source_hash([a2])


def test_source_hash_ignores_trailing_whitespace_only_edits() -> None:
    plain = _fragment("alpha", "rule-a", body="**MUST** run a.\n")
    padded = _fragment("alpha", "rule-a", body="**MUST** run a.   \n\n\n")
    assert compute_source_hash([plain]) == compute_source_hash([padded])


def test_source_hash_encodes_modality_none() -> None:
    raw_no_modality = (
        b"---\nid: r\nkind: constitution_fragment\natom_source: p\n---\n"
        b"**MUST** do it.\n"
    )
    without = BehaviorFragment.from_bytes(raw_no_modality, molecule_id="m")
    with_mod = _fragment("m", "r")
    assert without.modality is None
    assert with_mod.modality is Modality.MUST
    assert compute_source_hash([without]) != compute_source_hash([with_mod])


def test_emit_rendered_writes_the_text_verbatim_and_creates_the_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / SPAEX_MD_FILENAME
    outcome = emit_rendered("rendered\ntext\n", target=target)
    assert outcome.path == target
    assert outcome.changed is True
    assert target.read_text(encoding="utf-8") == "rendered\ntext\n"
    assert not list(target.parent.glob("*.tmp"))


def test_emit_rendered_replaces_a_different_file(tmp_path: Path) -> None:
    target = tmp_path / SPAEX_MD_FILENAME
    emit_rendered("one\n", target=target)
    outcome = emit_rendered("two\n", target=target)
    assert outcome.changed is True
    assert target.read_text(encoding="utf-8") == "two\n"


def test_emit_rendered_leaves_an_identical_file_untouched(tmp_path: Path) -> None:
    target = tmp_path / SPAEX_MD_FILENAME
    emit_rendered("same\n", target=target)
    os.utime(target, (1_000_000, 1_000_000))
    outcome = emit_rendered("same\n", target=target)
    assert outcome.changed is False
    assert target.stat().st_mtime == 1_000_000


def test_emit_rendered_keeps_the_old_file_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / SPAEX_MD_FILENAME
    emit_rendered("old\n", target=target)

    def boom(_src: object, _dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("spaex.behavior.emit.os.replace", boom)
    with pytest.raises(OSError, match="simulated replace failure"):
        emit_rendered("new\n", target=target)
    assert target.read_text(encoding="utf-8") == "old\n"


def test_remove_if_exists_deletes_and_reports(tmp_path: Path) -> None:
    target = tmp_path / SPAEX_MD_FILENAME
    target.parent.mkdir(parents=True)
    target.write_text("stale", encoding="utf-8")
    assert remove_if_exists(tmp_path) is True
    assert not target.exists()


def test_remove_if_exists_noop_when_absent(tmp_path: Path) -> None:
    assert remove_if_exists(tmp_path) is False


def test_remove_if_exists_accepts_an_explicit_target(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere" / "decisions.json"
    target.parent.mkdir()
    target.write_text("{}", encoding="utf-8")
    assert remove_if_exists(tmp_path, target) is True
    assert not target.exists()
