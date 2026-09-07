"""Regression coverage for the PR #12 review fixes."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import install as install_cli
from spaex.cli.diagnostics import emit_refuse
from spaex.cli.main import main
from spaex.constitution.resolve import ResolvedConstitutionContribution
from spaex.constitution.safety import (
    validate_no_plaintext_secrets,
    validate_terminal_safe_display,
)
from spaex.io import json_deterministic
from spaex.migrate import detect
from spaex.migrate.transform import (
    _glob_matches,
    _select_atom_for_path,
    migrate_v1_to_v2,
)
from spaex.model.consumer_manifest import ConsumerManifest
from spaex.model.install_lock import ConstitutionSource, InstallLock
from spaex.model.molecule_manifest import MoleculeManifest
from spaex.model.publisher_manifest import PublisherManifest
from spaex.schema.validator import _json_pointer
from spaex.util.errors import (
    HaexError,
    IdentityMismatchError,
    InstallLockSchemaInvalidError,
    MissingAtomManifestError,
    MissingPublisherManifestError,
    PlaintextSecretDetectedError,
    SpaexVersionUnsupportedError,
    TerminalUnsafeContributionError,
)


def test_constitution_commands_refuse_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--repo-root", str(tmp_path), "constitution", "show"]) == 2
    assert "key=constitution-not-assembled" in capsys.readouterr().err


def test_migrate_invalid_manifest_is_typed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".spaex.json").write_bytes(b"{")
    assert main(["--repo-root", str(tmp_path), "migrate", "--dry-run"]) == 2
    assert "key=spaex-json-invalid" in capsys.readouterr().err


def test_migrate_invalid_manifest_shape_is_typed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".spaex.json").write_text(
        '{"haex_hive_version": "1","identity":"com.example.project",'
        '"harness_sources":null}'
    )
    assert main(["--repo-root", str(tmp_path), "migrate", "--dry-run"]) == 2
    assert "key=spaex-json-invalid" in capsys.readouterr().err


def test_detect_non_object_manifest_is_shape_error() -> None:
    with pytest.raises(detect.InvalidHaexHiveManifestError):
        detect.detect_version(b"[]")


def test_missing_identity_is_an_identity_refusal() -> None:
    raw = json.dumps({"haex_hive_version": "1", "harness_sources": []}).encode()
    with pytest.raises(IdentityMismatchError):
        migrate_v1_to_v2(raw, Path("."), Path("."))


def test_invalid_atom_manifest_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # _select_atom_for_path reads the raw v2-era publisher shape directly
    # (research.md D6): the migrate-only v1->v2 path never goes through the
    # (now v3-only) PublisherManifest runtime model.
    publisher = json.loads(
        '{"haex_hive_version": "2","publisher":"com.example", "atoms": {'
        '"com.example.atom":{"path":"atom","version":"1.0.0"}}}'
    )
    monkeypatch.setattr(
        "spaex.migrate.transform.git_show.show_bytes", lambda *args, **kwargs: b"{"
    )
    with pytest.raises(MissingAtomManifestError):
        _select_atom_for_path(
            publisher, tmp_path, "0" * 40, "constitution", "atom/constitution.md"
        )


def test_invalid_legacy_publisher_atoms_is_typed(tmp_path: Path) -> None:
    """Malformed publisher-level atoms are reported as publisher errors."""
    with pytest.raises(MissingPublisherManifestError):
        _select_atom_for_path(
            {"atoms": []}, tmp_path, "0" * 40, "constitution", "atom/constitution.md"
        )


@pytest.mark.parametrize(
    "publisher",
    [
        {"atoms": {"com.example.atom": []}},
        {"atoms": {"com.example.atom": {"path": 42}}},
    ],
)
def test_invalid_legacy_atom_entry_is_typed(
    publisher: dict, tmp_path: Path
) -> None:
    """Malformed legacy atom entries are reported before field access."""
    with pytest.raises(MissingAtomManifestError):
        _select_atom_for_path(
            publisher, tmp_path, "0" * 40, "constitution", "atom/constitution.md"
        )


def test_invalid_legacy_contributes_value_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed legacy contributes block does not leak an AttributeError."""
    monkeypatch.setattr(
        "spaex.migrate.transform.git_show.show_bytes",
        lambda *args, **kwargs: b'{"contributes": []}',
    )
    publisher = {"atoms": {"com.example.atom": {"path": "atom"}}}

    with pytest.raises(MissingAtomManifestError):
        _select_atom_for_path(
            publisher, tmp_path, "0" * 40, "constitution", "atom/constitution.md"
        )


def test_glob_contributions_use_segment_aware_matching() -> None:
    assert _glob_matches("rules/*.md", "rules/main.md")
    assert not _glob_matches("rules/*.md", "rules/nested/main.md")
    assert _glob_matches("rules/**/*.md", "rules/nested/main.md")
    assert _glob_matches("rules/**/*.md", "rules/main.md")


@pytest.mark.parametrize("codepoint", [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF])
def test_rejects_invisible_format_controls(codepoint: int) -> None:
    with pytest.raises(TerminalUnsafeContributionError):
        validate_terminal_safe_display(f"safe{chr(codepoint)}text".encode())


def test_rejects_openpgp_private_key() -> None:
    with pytest.raises(PlaintextSecretDetectedError):
        validate_no_plaintext_secrets(
            b"-----BEGIN PGP PRIVATE KEY BLOCK-----\nsecret\n", location="test"
        )


def test_deterministic_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError):
        json_deterministic.dumps({"value": float("nan")})


def test_diagnostics_quote_control_characters() -> None:
    stream = StringIO()
    emit_refuse(HaexError(message="bad", context={"value": "a\x00\x1bb"}), stream=stream)
    assert 'value="a\\u0000\\u001bb"' in stream.getvalue()


def test_install_lock_freezes_unknown_nested_values() -> None:
    # Unknown top-level fields are accepted by the model's forward-compatible
    # projection and remain immutable after they are stored.
    lock = InstallLock(
        spaex_version="4",
        generation_id="g_20260901T120000Z_abcd",
        molecules=(),
        unknown_top_level={"future": {"nested": [1]}},
    )
    with pytest.raises(TypeError):
        lock.unknown_top_level["future"]["nested"][0] = 2


def test_install_lock_parse_failures_are_typed() -> None:
    with pytest.raises(InstallLockSchemaInvalidError) as exc_info:
        InstallLock.from_json(b"{")
    assert exc_info.value.__cause__ is not None


def test_install_allows_multiple_paths_from_one_molecule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A multi-file constitution from one molecule is not a multi-source install."""
    (tmp_path / ".spaex.json").write_text('{"identity":"com.example.project"}')
    source = ConstitutionSource(
        id="com.example.constitution",
        revision="0" * 40,
        source="https://example.com/publisher",
    )
    contributions = [
        ResolvedConstitutionContribution(source=source, body=b"first"),
        ResolvedConstitutionContribution(source=source, body=b"second"),
    ]
    captured: list[list[ResolvedConstitutionContribution]] = []

    monkeypatch.setattr(install_cli, "default_state_root", lambda: tmp_path / "state")
    monkeypatch.setattr(install_cli, "_load_consumer_manifest", lambda root: object())
    monkeypatch.setattr(
        install_cli,
        "resolve_constitution_contributions",
        lambda manifest, state_root: contributions,
    )
    monkeypatch.setattr(install_cli, "_is_no_op_single_source", lambda *args: False)
    monkeypatch.setattr(install_cli, "_live_generation_id", lambda root: "generation")
    monkeypatch.setattr(
        install_cli,
        "publish_constitution",
        lambda resolved, root, **kwargs: captured.append(list(resolved)),
    )

    assert install_cli.run(SimpleNamespace(repo_root=str(tmp_path))) == 0
    assert captured == [contributions]


def test_models_freeze_nested_json_values() -> None:
    molecule = MoleculeManifest.from_json(
        b'{"spaex_version": "4","id":"com.example.atom","version":"1.0.0",'
        b'"priority":100,"atoms":{"constitution":["constitution.md"]},'
        b'"defaults":{"nested":{"x":1}}}'
    )
    with pytest.raises(TypeError):
        molecule.defaults["nested"]["x"] = 2

    consumer = ConsumerManifest.from_json(
        b'{"spaex_version": "4","identity":"com.example.project","compounds":['
        b'{"source":"https://example.com/publisher","revision":"' + b"0" * 40
        + b'","molecules":["com.example.atom"],"config":{"com.example.atom":'
        b'{"values":{"nested":{"x":1}}}}}]}'
    )
    with pytest.raises(TypeError):
        consumer.compounds[0].config["com.example.atom"].values["nested"]["x"] = 2
    before = consumer.to_json_bytes()
    assert consumer.to_json_bytes() == before

    publisher = PublisherManifest.from_json(
        b'{"spaex_version": "4","publisher":"com.example","molecules":{'
        b'"com.example.atom":{"path":"atom","version":"1.0.0"}}}'
    )
    with pytest.raises(TypeError):
        publisher.molecules["com.example.other"] = publisher.molecules["com.example.atom"]


@pytest.mark.parametrize(
    "payload",
    [
        {"haex_hive_version": "3"},
        {"spaex_version": "3"},
        {"spaex_version": "5"},
    ],
)
def test_consumer_manifest_rejects_legacy_and_unsupported_versions(
    payload: dict[str, str],
) -> None:
    with pytest.raises(SpaexVersionUnsupportedError) as exc_info:
        ConsumerManifest.from_json(json.dumps(payload).encode())

    assert exc_info.value.diagnostic_key == "spaex-version-unsupported"
    assert "spaex migrate" in exc_info.value.hint


def test_molecule_manifest_rejects_negative_priority() -> None:
    with pytest.raises(ValueError):
        MoleculeManifest.from_json(
            b'{"spaex_version":"4","id":"com.example.atom",'
            b'"version":"1.0.0","priority":-1,"atoms":{"constitution":['
            b'"constitution.md"]}}'
        )


def test_json_pointer_escapes_tokens() -> None:
    assert _json_pointer(["bad/key~name"]) == "/bad~1key~0name"


# NOTE: The two `test_recovery_*` tests were retired by the R1/R7 amendment
# (2026-09-01). They exercised the bespoke JSON transaction journal's path
# validation and completeness checks; both have no counterpart under the
# rename-swap contract, which encodes state entirely in directory names.
# See tests/unit/test_transaction.py for the replacement in-flight coverage.
