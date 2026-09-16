"""Deterministic fragment→batch partitioning (Spec 026 T004).

Pure functions, no I/O: partitions the canonically-sorted fragment set into
fixed-size batches so no single Composer call's input grows unbounded with
the number of adopted molecules/fragments (research.md §2). A molecule's
fragments are never split across two batches. A fragment set that fits in
one batch degenerates to today's single-call path (see
`spaex.behavior.composer.reduce`).
"""

from __future__ import annotations
