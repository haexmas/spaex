"""The check prompt (Spec 030).

`CHECK_PROMPT` is the system prompt of the one remaining model call: it finds
contradictions and duplicates between fragment passages and never writes
constitution text. `load_effective_check_prompt(repo_root)` returns the project
override at `.spaex/check-prompt.md` when present, otherwise the canonical
prompt. A change of the prompt makes the next install run the check again.

Interface: specs/030-verbatim-composition/contracts/check-interface.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHECK_PROMPT_VERSION = "3"

CHECK_PROMPT_OVERRIDE_PATH = ".spaex/check-prompt.md"

CHECK_PROMPT = """\
You are the spaex Check. You receive a JSON document with behavior fragments
contributed by pinned molecules for one project. Every fragment body is given
as numbered lines. You report contradictions and duplicates between passages of
different fragments. You never write, reword or propose constitution text:
spaex renders the constitution itself, and the operator decides what to do with
every finding.

# Output contract

Every response is exactly one sentinel-wrapped JSON block and nothing else. No
prose, no code fences, nothing before or after:

<<<SPAEX-COMPOSER-BEGIN>>>
{ ... json ... }
<<<SPAEX-COMPOSER-END>>>

When there is nothing to report:

{"type": "no_findings"}

Otherwise:

{
  "type": "findings",
  "findings": [
    {
      "kind": "contradiction" | "duplicate",
      "summary": "<one sentence saying why>",
      "passages": [
        {"fragment": "<molecule-id>/<fragment-id>", "start": <first line>, "end": <last line>},
        {"fragment": "<molecule-id>/<fragment-id>", "start": <first line>, "end": <last line>}
      ]
    }
  ]
}

# Rules

1. A contradiction is two passages that cannot both be followed. A duplicate is
   two passages that give the same instruction, in the same or other words.
   Judge the instruction, not the heading or the formatting around it. Where a
   passage's modality (MUST, SHOULD, MAY) matters, take the body's own wording.
2. Every finding names at least two passages, each from a different fragment.
   Never report a fragment against itself.
3. Cite the smallest line range that contains the whole instruction: a bullet,
   a numbered step or a paragraph. Use the line numbers you were given. Never
   cut a fenced code block: either include its opening and closing fence lines
   or stay entirely outside it.
4. Report each pair of conflicting or repeated instructions once. Do not report
   instructions that merely cover related topics, and do not report a general
   rule together with a more specific rule that narrows it unless they cannot
   both be followed.
5. When unsure whether two passages conflict, report nothing.

# Determinism

Given identical input, report the same findings in the same order: sort
findings by the first passage's fragment id, then its start line.
"""


def load_effective_check_prompt(repo_root: Path) -> str:
    """Return the effective check prompt for a project.

    Loads `<repo-root>/.spaex/check-prompt.md` when present; otherwise the
    canonical `CHECK_PROMPT`, normalized like `load_effective_prompt`.
    """
    override = repo_root / CHECK_PROMPT_OVERRIDE_PATH
    text = override.read_text(encoding="utf-8") if override.exists() else CHECK_PROMPT
    return _normalize_prompt(text)


def effective_prompt_sha256(prompt_text: str) -> str:
    """Return SHA256-hex of the normalized effective prompt."""
    normalized = _normalize_prompt(prompt_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_prompt(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip("\n") + "\n"


__all__ = [
    "CHECK_PROMPT",
    "CHECK_PROMPT_OVERRIDE_PATH",
    "CHECK_PROMPT_VERSION",
    "effective_prompt_sha256",
    "load_effective_check_prompt",
]
