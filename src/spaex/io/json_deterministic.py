"""Deterministic JSON serialization (R2).

Two flavours:

- :func:`dumps` — the "pretty" form used for human-inspectable on-disk
  artefacts (`install.lock`): sorted keys, `indent=2`, LF-only line endings,
  single trailing LF.
- :func:`compact_json` — the "hash preimage" form used when a digest is
  computed over structured data: sorted keys, compact separators, no
  insignificant whitespace, no trailing newline. Returned bytes are what
  goes straight into `hashlib.sha256` for `plan_snapshot_digest` and any
  future preimage-shaped consumer.

Both share the deterministic-JSON discipline (sorted keys, UTF-8, reject
non-finite numbers).
"""

from __future__ import annotations

import json
from typing import Any


def dumps(obj: Any) -> bytes:
    text = json.dumps(
        obj,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        separators=(",", ": "),
        allow_nan=False,
    )
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return (text + "\n").encode("utf-8")


def compact_json(obj: Any) -> bytes:
    """Return canonical UTF-8 JSON bytes: sorted keys, no insignificant whitespace."""
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
