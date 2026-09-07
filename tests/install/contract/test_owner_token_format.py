"""T011 — contract test for the owner-token v1 format.

Assertions
- `OwnerToken.parse(str) → OwnerToken` and `OwnerToken.serialize() → str` round-trip.
- Emitted tokens fit the four-field `<pid>:<hostname>:<start_ns>:<uuid4_hex>` shape
  and stay at or below 128 UTF-8 bytes.
- Hostname sanitisation: non-`[A-Za-z0-9.-]` characters are removed, and the
  first 64 matching characters are kept (per contracts/owner-token.v1.md).

The `OwnerToken` type is defined by Spec 008 T013 in `spaex.install.lock`.
Until T013 lands the class, this whole test module is skipped so CI stays
green; when T013 lands, the skip guard falls away automatically and each
assertion below becomes a real contract check.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("spaex.install.lock")

try:
    from spaex.install.lock import OwnerToken  # type: ignore[attr-defined]
except ImportError:
    pytest.skip("OwnerToken lands with Spec 008 T013", allow_module_level=True)


_TOKEN_RE = re.compile(
    r"^(?P<pid>\d+):(?P<hostname>[A-Za-z0-9.-]{1,64}):(?P<start_ns>\d+):(?P<uuid>[0-9a-f]{32})$"
)


def _sample() -> OwnerToken:
    """Build a representative owner token."""
    return OwnerToken(
        pid=31245,
        hostname="laptop-hex.local",
        start_ns=1727612345678901234,
        uuid4_hex="8f3a2d1c9e7b4a5680c2e14f7d6b3a95",
    )


def test_serialize_matches_contract_shape() -> None:
    """Ensure serialized tokens have the four-field contract shape."""
    token = _sample()
    serialized = token.serialize()
    assert _TOKEN_RE.match(serialized), serialized


def test_serialize_stays_within_128_bytes() -> None:
    """Ensure serialized tokens fit the on-disk size limit."""
    token = _sample()
    assert len(token.serialize().encode("utf-8")) <= 128


def test_round_trip_parse_serialize() -> None:
    """Ensure parsing preserves a serialized owner token."""
    token = _sample()
    assert OwnerToken.parse(token.serialize()) == token


def test_hostname_sanitises_disallowed_characters() -> None:
    """Remove characters outside the hostname contract alphabet."""
    token = OwnerToken.emit(pid=1, hostname="foo bar!$baz", start_ns=0)
    assert token.hostname == "foobarbaz"


def test_hostname_truncates_to_64_chars() -> None:
    """Limit emitted hostnames to the contract maximum length."""
    token = OwnerToken.emit(pid=1, hostname="a" * 200, start_ns=0)
    assert token.hostname == "a" * 64


def test_empty_hostname_falls_back_to_unknown() -> None:
    """Use the stable fallback for an empty sanitized hostname."""
    token = OwnerToken.emit(pid=1, hostname="   !!!   ", start_ns=0)
    assert token.hostname == "unknown"


def test_parse_rejects_wrong_field_count() -> None:
    """Reject tokens that do not contain four fields."""
    with pytest.raises(ValueError):
        OwnerToken.parse("1:host:0")


def test_parse_rejects_uppercase_uuid() -> None:
    """Reject uppercase UUID hex in parsed owner tokens."""
    with pytest.raises(ValueError):
        OwnerToken.parse("1:host:0:" + "F" * 32)
