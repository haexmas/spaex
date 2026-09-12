"""Bootstrap discoverability integration test (Spec 023 T034, SC-007 automated portion).

Simulates the "mocked agent session reads its global instruction file, then
loads `.spaex/constitution.md`" flow. Real runtime processes are not launched; the test
verifies the bootstrap block's instruction survives round-trip and the
`.spaex/constitution.md` referenced from the working directory is discovered along the
git-root walk documented in contracts/bootstrap-block.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spaex.behavior import bootstrap


def _find_spaex_md(cwd: Path) -> Path | None:
    """Mimic what an agent runtime does after reading the bootstrap block.

    Walks from `cwd` upward until it finds `.spaex/constitution.md` or a `.git` directory
    (whichever comes first).
    """
    current = cwd.resolve()
    while True:
        candidate = current / ".spaex/constitution.md"
        if candidate.exists():
            return candidate
        if (current / ".git").exists():
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent


def test_mocked_runtime_finds_spaex_md_after_bootstrap(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".spaex").mkdir()
    (project / ".spaex/constitution.md").write_text(
        '<!-- spaex-composed:source_hash="' + "a" * 64 + '" '
        'build_input_hash="' + "b" * 64 + '" version="1" -->\n'
        "# spaex Behavior Harness\n\n## MUST\n- Do a thing. _[from `mol/rule`]_\n",
        encoding="utf-8",
    )

    outcomes = bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    assert outcomes[0].action == "created"
    global_instructions = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert ".spaex/constitution.md" in global_instructions

    subdir = project / "src" / "sub"
    subdir.mkdir(parents=True)
    discovered = _find_spaex_md(subdir)
    assert discovered is not None
    assert discovered == project / ".spaex/constitution.md"
    body = discovered.read_text(encoding="utf-8")
    assert "## MUST" in body
    assert "- Do a thing." in body


def test_bootstrap_instructions_are_stable_across_reinstalls(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    first = (home / ".claude" / "CLAUDE.md").read_bytes()
    bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    second = (home / ".claude" / "CLAUDE.md").read_bytes()
    assert first == second


def test_walk_stops_at_git_root_without_spaex_md(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    subdir = project / "src"
    subdir.mkdir()
    assert _find_spaex_md(subdir) is None


def test_cli_install_global_check_reports_missing_and_present(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """`spaex install --global --check` returns non-zero when missing, 0 when present."""
    from spaex.cli.main import main

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.delenv("CODEX_HOME", raising=False)

    rc = main(["install", "--global", "--check"])
    assert rc == 1
    capsys.readouterr()

    rc = main(["install", "--global"])
    assert rc == 0
    assert (home / ".claude" / "CLAUDE.md").exists()
    capsys.readouterr()

    rc = main(["install", "--global", "--check", "claude"])
    assert rc == 0


def test_cli_install_global_rejects_unknown_runtime(tmp_path: Path, monkeypatch) -> None:
    """A typo in the runtime list produces a typed usage refuse (exit 64)."""
    from spaex.cli.main import main

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)

    rc = main(["install", "--global", "gibberish"])
    from spaex.util import exit_codes

    assert rc == exit_codes.USAGE


@pytest.mark.parametrize(
    "argv",
    [
        ["install", "--dry-run"],
        ["install", "--check"],
        ["install", "claude"],
        ["install", "--global", "--dry-run", "--check"],
    ],
)
def test_cli_rejects_invalid_global_option_combinations(argv: list[str]) -> None:
    """Global-only flags must fail before the normal install handler runs."""
    from spaex.cli.main import main
    from spaex.util import exit_codes

    assert main(argv) == exit_codes.USAGE
