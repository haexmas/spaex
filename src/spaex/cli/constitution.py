"""`haex constitution show` handler.

`haex constitution assemble` was retired: `haex install` is the single
entry point that resolves atoms and publishes a new generation. This
module keeps only the read-only `show` subcommand, which prints the
byte-for-byte effective constitution from the currently published
generation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from spaex.constitution.show import show as render_constitution
from spaex.io.state import default_state_root
from spaex.util import exit_codes
from spaex.util.errors import HaexError


def _state_root() -> Path:
    """Return the spaex state directory path from env or default location."""
    return default_state_root()


def run_show(args: argparse.Namespace) -> int:
    """Execute the `haex constitution show` command.

    Verifies install.lock before printing the byte-for-byte constitution body.

    Returns:
        exit_codes.SUCCESS on successful, verified output.

    Raises:
        HaexError: On a missing/incomplete transaction, missing constitution or
            install.lock, corrupt install.lock, or an integrity mismatch.
    """
    repo_root = Path(args.repo_root).resolve()
    try:
        render_constitution(
            repo_root,
            no_preface=args.no_preface,
            state_root=_state_root(),
        )
        return exit_codes.SUCCESS
    except HaexError:
        raise
    except (OSError, ValueError) as exc:
        raise HaexError(
            message=f"constitution show failed: {exc}",
            diagnostic_key="constitution-show-failed",
            exit_code=exit_codes.INPUT_REFUSE,
        ) from exc
