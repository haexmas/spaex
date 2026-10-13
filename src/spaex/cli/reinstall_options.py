"""Options `spaex add` and `spaex remove` forward to their internal install.

Both commands edit the manifest and then reinstall in-process via
`write_and_reinstall`, so they accept the same per-invocation install
controls as `spaex install` itself.
"""

from __future__ import annotations

import argparse
from typing import Any


def add_reinstall_arguments(parser: argparse.ArgumentParser, *, command: str) -> None:
    """Attach `--no-install-hooks`, `--speckit-agents` and `--no-speckit-integrations`."""
    parser.add_argument(
        "--no-install-hooks",
        dest="skip_hooks",
        action="store_true",
        help=(
            "Skip per-molecule install_hook execution during the internal "
            f"install triggered by this {command}. Every molecule declaring "
            "install_hook records hook_status='skipped' in install.lock; "
            "atoms still materialize. Per-invocation only; a later "
            "`spaex install` without this flag runs the hooks (Spec 016 "
            "FR-027)."
        ),
    )
    parser.add_argument(
        "--speckit-agents",
        dest="speckit_agents",
        default=None,
        help="Select declared Spec Kit integrations for the internal install.",
    )
    parser.add_argument(
        "--no-speckit-integrations",
        dest="no_speckit_integrations",
        action="store_true",
        help="Skip declared Spec Kit integrations for the internal install.",
    )


def reinstall_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    """The `write_and_reinstall` keyword arguments selected on the command line."""
    return {
        "skip_hooks": bool(getattr(args, "skip_hooks", False)),
        "speckit_agents": getattr(args, "speckit_agents", None),
        "no_speckit_integrations": bool(getattr(args, "no_speckit_integrations", False)),
    }
