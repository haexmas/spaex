"""Map-reduce composition: batch dispatch + bounded merge orchestration (Spec 026).

The only new caller of `invoke.py`'s single-call machinery. For each `Batch`
(`batching.py`) this dispatches one Composer call reusing the existing
sentinel/Shape A/Shape B contract unchanged, then combines the batches'
composed output with one bounded merge step (a flat N-ary merge when the
merge input fits the batching byte-size ceiling, otherwise a deterministic
pairwise tree reduction) that re-checks for cross-batch contradictions
before the final, header-bearing document is returned.
"""

from __future__ import annotations
