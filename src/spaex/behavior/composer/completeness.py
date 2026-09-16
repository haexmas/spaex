"""Composer output completeness verification (Spec 023 T073, FR-012b).

Shared by `orchestrate.run()` (the final root-document check) and
`composer_reduce.compose()` (Spec 026: a per-batch check, so a batch that
silently drops a fragment is caught right after that batch call instead of
only once the whole build finishes). Lives here rather than in either of
those modules because `orchestrate.py` imports `reduce.py`, so putting it in
either would make the other's import a cycle — the same constraint T003's
`clarify.py` extraction already documented.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from spaex.behavior.composer.clarifications import ClarificationsStore
from spaex.behavior.composer.failure import ComposerFailureCategory, raise_for
from spaex.behavior.composer.invoke import (
    InvokeOptions,
    resolve_composer_log_path,
    write_composer_log,
)
from spaex.behavior.fragment import BehaviorFragment

_CLAUSE_CITATION_RE = re.compile(
    r"^- .+?\. _\[from (?P<provenance>`[^`]+`(?:, `[^`]+`)*)\]_$",
    re.MULTILINE,
)
_SCOPED_ID_RE = re.compile(r"`([^`]+)`")


def _cited_scoped_ids(composed_body: str) -> set[str]:
    """Every scoped id cited in a documented per-clause provenance annotation.

    The full clause shape is required so a Composer cannot satisfy the
    completeness check with a citation-like note outside a rendered clause.
    Clause text itself may contain unrelated inline code, e.g. "Use
    `pyproject.toml` for ...".
    """
    cited: set[str] = set()
    for clause in _CLAUSE_CITATION_RE.finditer(composed_body):
        cited.update(_SCOPED_ID_RE.findall(clause.group("provenance")))
    return cited


def verify_completeness(
    *,
    canonical_fragments: Sequence[BehaviorFragment],
    composed_body: str,
    clarifications: ClarificationsStore,
    repo_root: Path,
    invoke_options: InvokeOptions | None,
    step: str = "final",
    invocation: int = 1,
    phase: str = "initial",
) -> None:
    """Abort as `invalid-output` when the Composer silently dropped a fragment (FR-012b).

    A fragment is accounted for if it is cited in the composed body, or if a
    currently-valid persisted clarification (post-`invalidate()`) names it —
    meaning it was surfaced through the Shape B contradiction/overlap path
    and the operator's resolution already accounts for its absence. Anything
    else is exactly the silent-drop failure mode `emit_composed`'s hash
    checks cannot see, because those hashes are computed from the input, not
    the output body.

    Although the response parsed cleanly, the invocation log records it as
    composed before this post-parse check runs. Write the body here once more
    with the invalid-output outcome, so the same "go inspect the log" hint
    identifies the completeness failure and shows exactly where the body
    stopped citing fragments.
    """
    cited = _cited_scoped_ids(composed_body)
    excused = {
        cited_fragment.scoped_id
        for clarification in clarifications.entries.values()
        for cited_fragment in clarification.cited_fragments
    }
    missing = sorted(
        f.scoped_id
        for f in canonical_fragments
        if f.scoped_id not in cited and f.scoped_id not in excused
    )
    if missing:
        log_path = resolve_composer_log_path(invoke_options or InvokeOptions(), repo_root)
        write_composer_log(
            log_path,
            composed_body,
            step=step,
            invocation=invocation,
            phase=phase,
        )
        raise_for(
            ComposerFailureCategory.INVALID_OUTPUT,
            f"Composer output for {step} omits fragment(s) with no recorded clarification: "
            + ", ".join(missing),
            context={"step": step, "missing_fragments": ", ".join(missing)},
        )


__all__ = ["verify_completeness"]
