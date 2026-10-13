"""Environment helpers for Git subprocesses that select an explicit repository."""

from __future__ import annotations

import os

_REPOSITORY_SELECTION_VARIABLES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
)


def git_environment() -> dict[str, str]:
    """Return the process environment without inherited repository selectors."""
    environment = os.environ.copy()
    for variable in _REPOSITORY_SELECTION_VARIABLES:
        environment.pop(variable, None)
    return environment


__all__ = ["git_environment"]
