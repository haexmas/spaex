"""T090 — install.lock is byte-identical between two consecutive install runs.

Spec 008 SC-003 regression guardrail. The task text as originally captured in
tasks.md also mentioned `.haex-hive/visibility.json`; that file was retired
by the 2026-09-03 install.lock amendment (Spec 008 npm/pip-shape). Only
`install.lock` survives as the publication record, so this check is against
`install.lock` alone.

If the second consecutive install allocated a fresh generation ID (or
otherwise touched the file), that would silently churn every consumer's git
history on unchanged inputs. The check must be BYTE-identical, not just
JSON-equal, so canonical-serialization drift also fails.
"""

from __future__ import annotations

import pytest


def test_two_consecutive_installs_leave_install_lock_byte_identical(
    single_source_constitution_fixture: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from haex_hive.cli import install as install_cli

    consumer = single_source_constitution_fixture["consumer"]
    state_root = single_source_constitution_fixture["state_root"]
    monkeypatch.setenv("HAEX_HIVE_STATE", str(state_root))
    from types import SimpleNamespace

    ns = SimpleNamespace(repo_root=str(consumer))
    assert install_cli.run(ns) == 0
    lock_path = consumer / ".haex-hive" / "install.lock"
    first = lock_path.read_bytes()

    assert install_cli.run(ns) == 0
    second = lock_path.read_bytes()

    assert first == second, (
        "consecutive installs on unchanged inputs must produce byte-identical "
        "install.lock (Spec 008 SC-003)"
    )
