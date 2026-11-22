"""Shared fixtures for the behavior tests (Spec 030).

Integration tests drive `spaex install` through `install_cli.run`, which cannot
take `InvokeOptions`, so the model and the operator are replaced where
`orchestrate.run` looks them up:

- `stub_check` replaces `check_fragments` (the one model call). It counts calls
  and returns the findings the test queued.
- `operator` replaces the interactive prompt. It records every finding it is
  asked about and answers from a queue (or a default).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from spaex.behavior import orchestrate as behavior_orchestrate
from spaex.behavior.composer.check import Finding
from spaex.behavior.composer.invoke import InvokeOptions
from spaex.behavior.decisions import Choice
from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.passages import validate_range


@dataclass
class StubCheck:
    """Stands in for `check_fragments`; counts calls and returns queued findings."""

    findings: list[Finding] = field(default_factory=list)
    #: Alternative to `findings`: build findings from the fragments the check
    #: actually receives (use `make_finding(fragments, ...)` inside).
    factory: Callable[[Sequence[BehaviorFragment]], Sequence[Finding]] | None = None
    calls: int = 0
    seen: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(
        self,
        fragments: Sequence[BehaviorFragment],
        *,
        repo_root: Path,
        options: InvokeOptions | None = None,
        **_ignored: object,
    ) -> tuple[Finding, ...]:
        self.calls += 1
        self.seen.append(tuple(sorted(f.scoped_id for f in fragments)))
        if self.factory is not None:
            return tuple(self.factory(fragments))
        return tuple(self.findings)

    def queue(self, *findings: Finding) -> None:
        self.findings = list(findings)


@dataclass
class Operator:
    """Stands in for the interactive prompt; answers from `choices`, then `default`."""

    choices: list[Choice] = field(default_factory=list)
    default: Choice | None = None
    asked: list[Finding] = field(default_factory=list)

    def __call__(self, finding: Finding) -> Choice:
        self.asked.append(finding)
        if self.choices:
            return self.choices.pop(0)
        if self.default is not None:
            return self.default
        raise AssertionError(f"unexpected question: {finding.kind} {finding.summary}")


@pytest.fixture
def stub_check(monkeypatch: pytest.MonkeyPatch) -> StubCheck:
    stub = StubCheck()
    monkeypatch.setattr(behavior_orchestrate, "check_fragments", stub)
    return stub


@pytest.fixture
def operator(monkeypatch: pytest.MonkeyPatch) -> Operator:
    stub = Operator()
    monkeypatch.setattr(behavior_orchestrate, "default_operator_decision", stub)
    return stub


def make_finding(
    fragments: Iterable[BehaviorFragment],
    kind: str,
    *spans: tuple[str, int, int],
    summary: str = "they disagree",
) -> Finding:
    """A verified finding over `spans` = (scoped id, start line, end line)."""
    index = {fragment.scoped_id: fragment for fragment in fragments}
    return Finding(
        kind=kind,
        summary=summary,
        passages=tuple(validate_range(index[sid], start, end) for sid, start, end in spans),
    )


FindingFactory = Callable[..., Finding]
