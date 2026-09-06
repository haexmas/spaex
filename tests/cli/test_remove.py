"""T080 — CLI tests for `haex remove` (Spec 013)."""

from __future__ import annotations

import json

import pytest

from haex_hive.util.errors import HaexError, UnknownMoleculeIdError

_CONST_ID = "com.example.publisher.const"
_SKILL_ID = "com.example.publisher.skill"


@pytest.fixture
def adopted_repo(tmp_path, haex_add_helpers, monkeypatch):
    """Consumer with two molecules from one compound adopted and installed."""
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _CONST_ID: {
                "path": "const",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
            _SKILL_ID: {
                "path": "skill",
                "version": "1.0.0",
                "atoms": {"skills": ["skill.md"]},
            },
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        revision=head,
        all=True,
    )
    return {
        "consumer": consumer,
        "state_root": state_root,
        "canonical": canonical,
        "head": head,
    }


def test_single_id_retraction(adopted_repo, haex_add_helpers, monkeypatch) -> None:
    consumer = adopted_repo["consumer"]
    rc = haex_add_helpers["run_remove"](
        consumer,
        adopted_repo["state_root"],
        monkeypatch,
        molecule_ids=_SKILL_ID,
    )
    assert rc == 0
    written = json.loads((consumer / ".haex-hive.json").read_text())
    assert len(written["compounds"]) == 1
    assert written["compounds"][0]["molecules"] == [_CONST_ID]


def test_multi_id_comma_separated_retraction(
    adopted_repo, haex_add_helpers, monkeypatch
) -> None:
    # Retracting both molecules empties the sole compound. Install then has no
    # constitution and refuses with `install-transaction-failed`; the manifest
    # edit is rolled back atomically.
    from haex_hive.util.errors import InstallTransactionFailedError

    consumer = adopted_repo["consumer"]
    with pytest.raises(InstallTransactionFailedError):
        haex_add_helpers["run_remove"](
            consumer,
            adopted_repo["state_root"],
            monkeypatch,
            molecule_ids=f"{_CONST_ID},{_SKILL_ID}",
        )
    written = json.loads((consumer / ".haex-hive.json").read_text())
    assert len(written["compounds"]) == 1
    # Manifest was restored, both molecules still adopted.
    assert set(written["compounds"][0]["molecules"]) == {_CONST_ID, _SKILL_ID}


def test_empty_compound_dropped_after_retraction(
    tmp_path, haex_add_helpers, monkeypatch
) -> None:
    """A compound whose molecules[] becomes empty is dropped entirely."""
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _CONST_ID: {
                "path": "const",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
        },
        name="a",
    )
    other_canonical, other_head, _s = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _SKILL_ID: {
                "path": "skill",
                "version": "1.0.0",
                "atoms": {"skills": ["skill.md"]},
            },
        },
        name="b",
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        molecule_ids=_CONST_ID,
        revision=head,
    )
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=other_canonical,
        molecule_ids=_SKILL_ID,
        revision=other_head,
    )
    before = json.loads((consumer / ".haex-hive.json").read_text())
    assert len(before["compounds"]) == 2

    rc = haex_add_helpers["run_remove"](
        consumer, state_root, monkeypatch, molecule_ids=_SKILL_ID
    )
    assert rc == 0
    after = json.loads((consumer / ".haex-hive.json").read_text())
    assert len(after["compounds"]) == 1
    assert after["compounds"][0]["source"] == canonical


def test_unknown_molecule_id_refuses_absent(
    adopted_repo, haex_add_helpers, monkeypatch
) -> None:
    consumer = adopted_repo["consumer"]
    baseline = (consumer / ".haex-hive.json").read_bytes()
    with pytest.raises(UnknownMoleculeIdError) as exc_info:
        haex_add_helpers["run_remove"](
            consumer,
            adopted_repo["state_root"],
            monkeypatch,
            molecule_ids="com.example.publisher.never-adopted",
        )
    assert "never-adopted" in exc_info.value.context["missing"]
    assert (consumer / ".haex-hive.json").read_bytes() == baseline


def test_preflight_refuses_mixed_request_without_touching_manifest(
    adopted_repo, haex_add_helpers, monkeypatch
) -> None:
    """`haex remove <present>,<absent>` names every missing id and writes nothing."""
    consumer = adopted_repo["consumer"]
    baseline = (consumer / ".haex-hive.json").read_bytes()
    with pytest.raises(UnknownMoleculeIdError) as exc_info:
        haex_add_helpers["run_remove"](
            consumer,
            adopted_repo["state_root"],
            monkeypatch,
            molecule_ids=(
                f"{_CONST_ID},"
                "com.example.publisher.absent-a,"
                "com.example.publisher.absent-b"
            ),
        )
    missing = exc_info.value.context["missing"]
    assert "absent-a" in missing
    assert "absent-b" in missing
    assert _CONST_ID not in missing
    assert (consumer / ".haex-hive.json").read_bytes() == baseline


def test_malformed_manifest_is_a_typed_refusal(
    tmp_path, haex_add_helpers, monkeypatch
) -> None:
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    (consumer / ".haex-hive.json").write_text("{}")

    with pytest.raises(HaexError) as exc_info:
        haex_add_helpers["run_remove"](
            consumer,
            tmp_path / "state",
            monkeypatch,
            molecule_ids=_CONST_ID,
        )

    assert exc_info.value.diagnostic_key == "haex-hive-json-invalid"
