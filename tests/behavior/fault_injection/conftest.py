"""Fault-injection scaffolding for check failures (Spec 023 T021, reworked for Spec 030).

Every fault-injection test wants the same thing: drive `run_check` through a
canned scenario ("timeout", "quota", ...) and observe the raised `HaexError`
subclass and its exit code. The scaffolding here bundles the `InvokeOptions`
factory into a single `mock_composer` pytest fixture.

Scenarios covered:

- `timeout` - stub raises MockTimeout named to trigger the classifier.
- `runtime-error` - stub raises a generic exception.
- `quota` - stub raises MockRateLimit named to trigger the classifier.
- `invalid-output` - stub returns unparseable text.
- `no-runtime` - no CLI runtimes detected.
- `no_findings` - stub returns a valid answer without findings (parses cleanly).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from spaex.behavior.composer.check import CheckInput, Finding, run_check
from spaex.behavior.composer.invoke import InvokeOptions
from spaex.behavior.fragment import BehaviorFragment


class MockTimeout(Exception):
    """Named so `_classify_stub_exception` maps it to `timeout`."""


class MockRateLimit(Exception):
    """Named so `_classify_stub_exception` maps it to `quota`."""


def _no_findings_body() -> str:
    return (
        "<<<SPAEX-COMPOSER-BEGIN>>>\n"
        '{"type": "no_findings"}\n'
        "<<<SPAEX-COMPOSER-END>>>\n"
    )


@dataclass
class _RecordingStubCaller:
    """Records calls and returns/raises per scenario."""

    scenario: str
    answer_override: str | None = None
    invocations: list[dict[str, Any]] = field(default_factory=list)

    def __call__(
        self, runtime: str, system_prompt: str, payload: str, timeout: float
    ) -> str:
        self.invocations.append(
            {
                "runtime": runtime,
                "system_prompt": system_prompt,
                "payload": payload,
                "timeout": timeout,
            }
        )
        if self.scenario == "timeout":
            raise MockTimeout("mock composer timeout")
        if self.scenario == "quota":
            raise MockRateLimit("mock composer quota")
        if self.scenario == "runtime-error":
            raise RuntimeError("mock composer runtime error")
        if self.scenario == "invalid-output":
            return "this is not a sentinel-wrapped response"
        if self.scenario == "no_findings":
            return self.answer_override or _no_findings_body()
        raise AssertionError(f"unknown scenario: {self.scenario}")


@dataclass
class MockComposer:
    """Built by the `mock_composer` fixture; owns the InvokeOptions + caller.

    A test that only wants to trip a category calls `invoke(repo_root)` with
    no fragments; a test that wants to observe the payload reads
    `mock_composer.calls`.
    """

    scenario: str
    options: InvokeOptions
    caller: _RecordingStubCaller | None = None

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.caller.invocations if self.caller is not None else []

    def invoke(
        self, repo_root: Path, fragments: Sequence[BehaviorFragment] = ()
    ) -> tuple[Finding, ...]:
        return run_check(
            CheckInput(fragments=tuple(fragments)), repo_root=repo_root, options=self.options
        )


@pytest.fixture
def mock_composer() -> Callable[..., MockComposer]:
    """Return a factory that builds a `MockComposer` for one scenario."""

    def factory(
        scenario: str,
        *,
        answer: str | None = None,
        timeout_seconds: float | None = None,
    ) -> MockComposer:
        if scenario == "no-runtime":
            return MockComposer(
                scenario=scenario,
                options=InvokeOptions(
                    forced_cli_runtimes=(),
                    timeout_seconds=timeout_seconds,
                ),
            )
        caller = _RecordingStubCaller(
            scenario=scenario, answer_override=answer
        )
        options = InvokeOptions(
            stub_caller=caller,
            timeout_seconds=timeout_seconds,
        )
        return MockComposer(scenario=scenario, options=options, caller=caller)

    return factory


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A clean per-test repo root; composer prompt override may live inside."""
    (tmp_path / ".spaex").mkdir(parents=True, exist_ok=True)
    return tmp_path
