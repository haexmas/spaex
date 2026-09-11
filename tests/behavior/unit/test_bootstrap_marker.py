"""Bootstrap marker unit tests (Spec 023 T033).

Covers:

- Fresh install into a missing target file.
- Append when the file exists without markers, preserving prior content.
- Version-attribute-driven upgrade that replaces the block.
- No-op when the version matches.
- Idempotency (SC-009): running install twice produces the same file.
- Preserved content outside the paired markers.
- Preflight aborts on malformed marker layouts (unmatched, duplicated,
  end-before-start).
- Codex CODEX_HOME override selection between AGENTS.override.md and AGENTS.md.
- Gemini settings.json parsing: default, string, array, and rejected
  path-bearing entries.
- `check()` returns False when a target is missing the block and True when
  every target is at the current version.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from spaex.behavior import bootstrap


def _fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def test_install_creates_missing_claude_target(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    outcomes = bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    assert [o.action for o in outcomes] == ["created"]
    target = home / ".claude" / "CLAUDE.md"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert '<!-- spaex-bootstrap:start version="1" -->' in text
    assert bootstrap.END_MARKER in text
    assert "## spaex per-project constitution" in text


def test_install_appends_when_target_has_content_but_no_markers(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    target = home / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text("existing operator content\n", encoding="utf-8")
    outcomes = bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    assert [o.action for o in outcomes] == ["appended"]
    text = target.read_text(encoding="utf-8")
    assert text.startswith("existing operator content\n")
    assert '<!-- spaex-bootstrap:start version="1" -->' in text


def test_install_preserves_symlink_and_mode(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    target = home / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    referent = tmp_path / "shared-instructions.md"
    referent.write_text("operator content\n", encoding="utf-8")
    referent.chmod(stat.S_IRUSR | stat.S_IWUSR)
    original_mode = stat.S_IMODE(referent.stat().st_mode)
    target.symlink_to(referent)

    bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})

    assert target.is_symlink()
    assert target.resolve() == referent
    assert stat.S_IMODE(referent.stat().st_mode) == original_mode
    assert "operator content" in referent.read_text(encoding="utf-8")
    assert bootstrap.END_MARKER in referent.read_text(encoding="utf-8")


def test_install_keeps_original_when_atomic_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _fake_home(tmp_path)
    target = home / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    original = "operator content\n"
    target.write_text(original, encoding="utf-8")

    def fail_replace(*_args, **_kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(bootstrap.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})

    assert target.read_text(encoding="utf-8") == original


def test_install_is_idempotent(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    first = bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    assert first[0].action == "created"
    text_after_first = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    second = bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    assert second[0].action == "unchanged"
    assert (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8") == text_after_first


def test_install_upgrades_older_version_and_preserves_surrounding_content(
    tmp_path: Path,
) -> None:
    home = _fake_home(tmp_path)
    target = home / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "preamble\n"
        '<!-- spaex-bootstrap:start version="0" -->\n'
        "\n"
        "old body\n"
        "\n"
        "<!-- spaex-bootstrap:end -->\n"
        "\n"
        "trailing operator notes\n",
        encoding="utf-8",
    )
    outcomes = bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    assert [o.action for o in outcomes] == ["upgraded"]
    text = target.read_text(encoding="utf-8")
    assert text.startswith("preamble\n")
    assert '<!-- spaex-bootstrap:start version="1" -->' in text
    assert "old body" not in text
    assert text.endswith("trailing operator notes\n")


def test_preflight_rejects_multiple_start_markers(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    target = home / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        '<!-- spaex-bootstrap:start version="1" -->\n\nbody\n\n<!-- spaex-bootstrap:end -->\n'
        '<!-- spaex-bootstrap:start version="1" -->\n\nbody\n\n<!-- spaex-bootstrap:end -->\n',
        encoding="utf-8",
    )
    original = target.read_text(encoding="utf-8")
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    assert target.read_text(encoding="utf-8") == original


def test_preflight_rejects_end_before_start(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    target = home / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "<!-- spaex-bootstrap:end -->\nbody\n"
        '<!-- spaex-bootstrap:start version="1" -->\n',
        encoding="utf-8",
    )
    original = target.read_text(encoding="utf-8")
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    assert target.read_text(encoding="utf-8") == original


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    outcomes = bootstrap.install(
        [bootstrap.Runtime.CLAUDE], home=home, env={}, dry_run=True
    )
    assert outcomes[0].action == "created"
    assert not (home / ".claude" / "CLAUDE.md").exists()


def test_check_returns_false_when_target_missing(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    assert bootstrap.check([bootstrap.Runtime.CLAUDE], home=home, env={}) is False


def test_check_returns_true_after_install(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    bootstrap.install([bootstrap.Runtime.CLAUDE], home=home, env={})
    assert bootstrap.check([bootstrap.Runtime.CLAUDE], home=home, env={}) is True


def test_check_returns_false_for_older_version(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    target = home / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        '<!-- spaex-bootstrap:start version="0" -->\n\nbody\n\n<!-- spaex-bootstrap:end -->\n',
        encoding="utf-8",
    )
    assert bootstrap.check([bootstrap.Runtime.CLAUDE], home=home, env={}) is False


def test_codex_uses_agents_md_by_default(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    targets = bootstrap.resolve_targets(bootstrap.Runtime.CODEX, home=home, env={})
    assert targets == [home / ".codex" / "AGENTS.md"]


def test_codex_uses_agents_override_md_when_non_empty(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    codex_home = home / ".codex"
    codex_home.mkdir()
    (codex_home / "AGENTS.override.md").write_text("operator override\n", encoding="utf-8")
    targets = bootstrap.resolve_targets(bootstrap.Runtime.CODEX, home=home, env={})
    assert targets == [codex_home / "AGENTS.override.md"]


def test_codex_ignores_empty_agents_override(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    codex_home = home / ".codex"
    codex_home.mkdir()
    (codex_home / "AGENTS.override.md").write_text("   \n\t\n", encoding="utf-8")
    targets = bootstrap.resolve_targets(bootstrap.Runtime.CODEX, home=home, env={})
    assert targets == [codex_home / "AGENTS.md"]


def test_codex_honors_codex_home_env(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    custom = tmp_path / "codex-custom"
    targets = bootstrap.resolve_targets(
        bootstrap.Runtime.CODEX, home=home, env={"CODEX_HOME": str(custom)}
    )
    assert targets == [custom / "AGENTS.md"]


def test_gemini_defaults_to_gemini_md(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    targets = bootstrap.resolve_targets(bootstrap.Runtime.GEMINI, home=home, env={})
    assert targets == [home / ".gemini" / "GEMINI.md"]


def test_gemini_reads_settings_string_context_filename(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    gemini_home = home / ".gemini"
    gemini_home.mkdir()
    (gemini_home / "settings.json").write_text(
        json.dumps({"context": {"fileName": "AGENTS.md"}}), encoding="utf-8"
    )
    targets = bootstrap.resolve_targets(bootstrap.Runtime.GEMINI, home=home, env={})
    assert targets == [gemini_home / "AGENTS.md"]


def test_gemini_reads_settings_list_context_filenames(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    gemini_home = home / ".gemini"
    gemini_home.mkdir()
    (gemini_home / "settings.json").write_text(
        json.dumps({"context": {"fileName": ["AGENTS.md", "OPS.md"]}}),
        encoding="utf-8",
    )
    targets = bootstrap.resolve_targets(bootstrap.Runtime.GEMINI, home=home, env={})
    assert targets == [gemini_home / "AGENTS.md", gemini_home / "OPS.md"]


def test_gemini_rejects_path_bearing_context_filename(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    gemini_home = home / ".gemini"
    gemini_home.mkdir()
    (gemini_home / "settings.json").write_text(
        json.dumps({"context": {"fileName": "../etc/passwd"}}), encoding="utf-8"
    )
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.resolve_targets(bootstrap.Runtime.GEMINI, home=home, env={})


def test_gemini_rejects_malformed_settings(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    gemini_home = home / ".gemini"
    gemini_home.mkdir()
    (gemini_home / "settings.json").write_text("{ not valid", encoding="utf-8")
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.resolve_targets(bootstrap.Runtime.GEMINI, home=home, env={})


def test_install_all_three_runtimes_hits_expected_targets(tmp_path: Path) -> None:
    home = _fake_home(tmp_path)
    outcomes = bootstrap.install(home=home, env={})
    written = {o.target for o in outcomes if o.action != "unchanged"}
    assert (home / ".claude" / "CLAUDE.md") in written
    assert (home / ".codex" / "AGENTS.md") in written
    assert (home / ".gemini" / "GEMINI.md") in written
