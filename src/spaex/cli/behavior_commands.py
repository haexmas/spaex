"""Spec 023 behavior CLI subcommands.

Currently exposes the `spaex install --global` handler; Phase 10 T055-T057
will add `spaex constitution build` and `spaex constitution trace` here.
"""

from __future__ import annotations

import argparse
import sys

from spaex.behavior import bootstrap
from spaex.util import exit_codes
from spaex.util.errors import HaexError


def run_install_global(args: argparse.Namespace) -> int:
    """Install / upgrade / check the global bootstrap block per runtime."""
    runtimes_arg = getattr(args, "global_runtimes", None)
    runtimes = _parse_runtimes(runtimes_arg)
    dry_run = bool(getattr(args, "dry_run", False))
    check_only = bool(getattr(args, "check_only", False))

    if check_only:
        ok = bootstrap.check(runtimes)
        if ok:
            sys.stdout.write(
                "spaex bootstrap: every target is at the current version\n"
            )
            return exit_codes.SUCCESS
        sys.stdout.write(
            "spaex bootstrap: at least one target is missing or older\n"
        )
        return 1

    try:
        outcomes = bootstrap.install(runtimes, dry_run=dry_run)
    except bootstrap.BootstrapError:
        raise
    for outcome in outcomes:
        sys.stdout.write(
            f"{outcome.runtime.value:<8} {outcome.action:<10} {outcome.target}\n"
        )
    return exit_codes.SUCCESS


def maybe_emit_no_bootstrap_hint() -> None:
    """T036: point the operator at `spaex install --global` when none present.

    Called at the end of a per-project install. Runs `bootstrap.check` for
    every default runtime; if none carry the block, emits one stderr hint.
    Safe to call unconditionally; a broken resolver (e.g. malformed Gemini
    settings) is silently ignored so a bad user config never breaks the
    per-project install.
    """
    try:
        if bootstrap.check():
            return
        found_any = False
        for runtime in bootstrap.ALL_RUNTIMES:
            try:
                targets = bootstrap.resolve_targets(runtime)
            except HaexError:
                continue
            for target in targets:
                if target.exists():
                    found_any = True
                    break
            if found_any:
                break
    except HaexError:
        return
    sys.stderr.write(
        "hint: no runtime global bootstrap detected on this machine; "
        "run `spaex install --global` so agent runtimes discover .spaex.md "
        "(FR-023, contracts/cli-surface.md)\n"
    )


def _parse_runtimes(raw: str | None) -> list[bootstrap.Runtime]:
    if not raw:
        return list(bootstrap.ALL_RUNTIMES)
    names = [name.strip() for name in raw.split(",") if name.strip()]
    parsed: list[bootstrap.Runtime] = []
    for name in names:
        try:
            parsed.append(bootstrap.Runtime(name))
        except ValueError as exc:
            raise HaexError(
                message=(
                    f"unknown runtime {name!r}; expected one of "
                    f"{[r.value for r in bootstrap.ALL_RUNTIMES]}"
                ),
                diagnostic_key="behavior-bootstrap-unknown-runtime",
                exit_code=exit_codes.USAGE,
                hint="Pass a comma-separated list of claude, codex, gemini.",
            ) from exc
    return parsed


__all__ = ["maybe_emit_no_bootstrap_hint", "run_install_global"]
