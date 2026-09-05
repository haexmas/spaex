"""Per-invocation proposal registry (Spec 013 T052).

`haex migrate` registers every path a single invocation would create so a
failure inside the invocation can unlink whatever was already written.
Originals are never touched (Principle VI review-gate discipline).

Usage:

    registry = ProposalRegistry()
    try:
        for path, payload in proposals:
            registry.emit(path, payload)
        registry.commit()
    except Exception:
        registry.rollback()
        raise
"""

from __future__ import annotations

import os
from pathlib import Path

from haex_hive.io import atomic


class ProposalRegistry:
    """Track every proposal path a single migrate invocation writes."""

    def __init__(self) -> None:
        self._paths: list[Path] = []

    @property
    def registered(self) -> tuple[Path, ...]:
        return tuple(self._paths)

    def register(self, path: Path) -> None:
        """Record a path that this invocation will (or did) create."""
        self._paths.append(path)

    def emit(self, path: Path, payload: bytes) -> None:
        """Atomically write ``payload`` to ``path`` and register the path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_replace(path, payload)
        self.register(path)

    def commit(self) -> None:
        """Clear the registry after every proposal has landed successfully."""
        self._paths.clear()

    def rollback(self) -> None:
        """Unlink every registered path; missing paths are ignored."""
        while self._paths:
            path = self._paths.pop()
            try:
                os.unlink(path)
            except FileNotFoundError:
                continue
            except OSError:
                # Best-effort cleanup: leave the file if unlink fails so the
                # operator can see what was produced.
                continue
