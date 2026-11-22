"""Ask the operator what to do with a finding (Spec 030, research R7).

Every finding of the check, contradiction or duplicate, goes to the operator
one at a time with both passages shown. Nothing is decided on the operator's
behalf: a blank answer or a non-interactive terminal aborts the install.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from spaex.behavior.composer.check import Finding
from spaex.behavior.decisions import Choice
from spaex.util import exit_codes
from spaex.util.errors import HaexError

OperatorDecision = Callable[[Finding], Choice]

_HINT = (
    "Rerun `spaex install` from an interactive terminal to decide the finding, "
    "or change the fragment that causes it."
)


def default_operator_decision(finding: Finding) -> Choice:
    """Prompt stdin for one finding; refuse on a non-interactive terminal."""
    if not sys.stdin.isatty():
        raise HaexError(
            message=(
                f"the check found a {finding.kind} ({finding.summary}) between "
                f"{', '.join(p.scoped_id for p in finding.passages)}, but stdin is not a "
                "TTY; cannot ask the operator"
            ),
            diagnostic_key="behavior-clarification-required",
            exit_code=exit_codes.BEHAVIOR_SEMANTIC_REFUSE,
            hint=_HINT,
        )
    summary = "\n".join(
        f"  {line}" for line in _escape_terminal_controls(finding.summary).splitlines()
    )
    sys.stdout.write(f"\nFinding ({finding.kind}):\n{summary}\n")
    for number, passage in enumerate(finding.passages, start=1):
        sys.stdout.write(
            f"\n  [{number}] {passage.scoped_id}, lines {passage.start}-{passage.end}:\n"
        )
        for line in _escape_terminal_controls(passage.text).split("\n"):
            sys.stdout.write(f"      {line}\n")
    sys.stdout.write("\n")
    for number in range(1, len(finding.passages) + 1):
        others = "the other" if len(finding.passages) == 2 else "the others"
        sys.stdout.write(f"  {number}: keep [{number}], comment out {others}\n")
    sys.stdout.write("  a: keep all (not a real finding)\n")
    while True:
        sys.stdout.write("Choice (blank to decline and abort install): ")
        sys.stdout.flush()
        answer = sys.stdin.readline().strip().lower()
        if not answer:
            raise HaexError(
                message="the operator declined to decide a finding",
                diagnostic_key="behavior-clarification-required",
                exit_code=exit_codes.BEHAVIOR_SEMANTIC_REFUSE,
                hint=_HINT,
            )
        if answer == "a":
            return Choice(kind="keep_all")
        try:
            choice = int(answer)
        except ValueError:
            choice = 0
        if 1 <= choice <= len(finding.passages):
            return Choice(kind="keep", kept=choice - 1)
        sys.stdout.write("Please answer with a number from the list, or 'a'.\n")


def _escape_terminal_controls(text: str) -> str:
    """Make control and non-printable characters visible in terminal output."""
    escaped: list[str] = []
    for char in text:
        if char.isprintable() or char == "\n":
            escaped.append(char)
        else:
            codepoint = ord(char)
            escaped.append(
                f"\\x{codepoint:02x}"
                if codepoint <= 0xFF
                else f"\\u{codepoint:04x}"
                if codepoint <= 0xFFFF
                else f"\\U{codepoint:08x}"
            )
    return "".join(escaped)


__all__ = ["OperatorDecision", "default_operator_decision"]
