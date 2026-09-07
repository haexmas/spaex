"""Generation-ID allocation for install publications (Spec 008 §R8, T027).

The generation ID is time-based and lexicographically ordered:
`g_<UTC-basic-timestamp>_<sha256(body)[:4]>`. Allocation MUST advance past
any equal existing ID so the sequence is strictly monotonic.
"""

from __future__ import annotations

import datetime
import hashlib
import re

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_GENERATION_ID_RE = re.compile(r"g_(\d{8}T\d{6}Z)_[0-9a-f]{4}")


def allocate_generation_id(body: bytes, existing_generation_id: str | None) -> str:
    """Return a fresh generation ID strictly greater than any prior one.

    The suffix is `sha256(body)[:4]` so equal-content publications share the
    same stable per-generation-input tag; the timestamp is the tie-breaker
    that makes the sequence monotonic even at sub-second cadence.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    suffix = hashlib.sha256(body).hexdigest()[:4]
    candidate = f"g_{now.strftime(_TIMESTAMP_FORMAT)}_{suffix}"
    if existing_generation_id is None or candidate > existing_generation_id:
        return candidate

    match = _GENERATION_ID_RE.fullmatch(existing_generation_id)
    if match is not None:
        base = datetime.datetime.strptime(match.group(1), _TIMESTAMP_FORMAT).replace(
            tzinfo=datetime.timezone.utc
        )
        bumped = base + datetime.timedelta(seconds=1)
    else:
        bumped = now + datetime.timedelta(seconds=1)
    return f"g_{bumped.strftime(_TIMESTAMP_FORMAT)}_{suffix}"
