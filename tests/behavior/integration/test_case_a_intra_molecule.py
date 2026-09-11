"""Case A: intra-molecule contradictory modality aborts install with exit 20 (T039).

A single molecule ships two fragments under the same molecule-scoped id but
with contradictory modalities (MUST vs SHOULD). The mechanical pre-check must
reject the pin set BEFORE the Composer is invoked (FR-005), so `spaex install`
exits 20 with a typed diagnostic naming both producers, and `.spaex.md` is
never written (FR-006, SC-002 Case A).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.cli import install as install_cli
from spaex.migrate.transform import clone_dir
from spaex.util import exit_codes
from spaex.util.errors import HaexError

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


_MOL = "com.example.publisher.contradictory-modality"
_CANONICAL = "https://example.invalid/example/publisher-case-a"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_case_a_molecule(tmp_path: Path) -> tuple[str, str, Path]:
    working = tmp_path / "publisher-working"
    working.mkdir()
    _git(working, "init", "-q", "-b", "main")
    _git(working, "config", "user.email", "author@example.com")
    _git(working, "config", "user.name", "author")
    _git(working, "config", "commit.gpgsign", "false")

    (working / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "publisher": "com.example.publisher",
                "molecules": {_MOL: {"path": "contradictory", "version": "1.0.0"}},
            },
            indent=2,
        )
    )
    mol_dir = working / "contradictory"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOL,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {
                    "behavior": [
                        "fragments/rule-must.md",
                        "fragments/rule-should.md",
                    ],
                },
            },
            indent=2,
        )
    )
    fragments_dir = mol_dir / "fragments"
    fragments_dir.mkdir()
    (fragments_dir / "rule-must.md").write_text(
        "---\n"
        "id: contested-rule\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.strict\n"
        "modality: MUST\n"
        "---\n"
        "**MUST** always run the linter before committing.\n"
    )
    (fragments_dir / "rule-should.md").write_text(
        "---\n"
        "id: contested-rule\n"
        "kind: constitution_fragment\n"
        "atom_source: pkg.lenient\n"
        "modality: SHOULD\n"
        "---\n"
        "**SHOULD** usually run the linter before committing.\n"
    )

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "case A contradictory modality fixture")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head, state_root


def _make_consumer_pinning(
    tmp_path: Path, *, source_url: str, revision: str
) -> Path:
    """Hand-seed a consumer that already pins the Case A molecule.

    `spaex add` would wrap the follow-on install failure in
    `InstallTransactionFailedError` (exit 2) and roll back the manifest edit;
    calling `spaex install` on an already-pinned manifest surfaces the raw
    behavior-precheck exit code (20) that this test asserts on.
    """
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [
                    {
                        "source": source_url,
                        "revision": revision,
                        "molecules": [_MOL],
                    }
                ],
            }
        )
    )
    return consumer


def _run_install(
    consumer: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0)
    return install_cli.run(ns)


def test_case_a_aborts_with_exit_20_before_composer_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical, head, state_root = _publish_case_a_molecule(tmp_path)
    consumer = _make_consumer_pinning(tmp_path, source_url=canonical, revision=head)

    composer_calls: list[int] = []

    def sentinel_composer(*args, **kwargs):
        composer_calls.append(1)
        raise AssertionError(
            "Composer must not be invoked when the mechanical pre-check "
            "rejects the pin set (FR-005)"
        )

    monkeypatch.setattr(
        behavior_orchestrate, "invoke_composer", sentinel_composer
    )

    with pytest.raises(HaexError) as excinfo:
        _run_install(consumer, state_root, monkeypatch)

    err = excinfo.value
    assert err.exit_code == exit_codes.BEHAVIOR_PRECHECK_REFUSE == 20
    assert err.diagnostic_key == "behavior-precheck-intra-molecule-collision"
    message = str(err)
    assert "contested-rule" in message
    assert "MUST" in message
    assert "SHOULD" in message

    assert composer_calls == []
    assert not (consumer / ".spaex.md").exists()
