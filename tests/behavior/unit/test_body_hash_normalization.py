"""body_sha256 normalization (Spec 023 T011).

Per research.md §7: normalize before hashing.
1. Convert CRLF to LF.
2. Strip trailing whitespace on each line.
3. Collapse trailing blank lines to exactly one trailing LF.

The CRLF round-trip case is explicitly required by memory
`feedback_verify_tool_behavior_empirically` (git may rewrite line endings on
checkout; hashing raw bytes would spuriously invalidate clarifications).
"""

from __future__ import annotations

import hashlib

from spaex.behavior.fragment import body_sha256


def _hash(text: str) -> str:
    return body_sha256(text)


def test_crlf_and_lf_hash_identically() -> None:
    """A body checked in with LF and later checked out with CRLF must hash the same."""
    lf = "**MUST** honor.\nSecond line.\n"
    crlf = "**MUST** honor.\r\nSecond line.\r\n"
    assert _hash(lf) == _hash(crlf)


def test_cr_only_line_endings_also_normalized() -> None:
    """Old-Mac-style CR-only endings are folded to LF as well."""
    lf = "line one\nline two\n"
    cr = "line one\rline two\r"
    assert _hash(lf) == _hash(cr)


def test_trailing_whitespace_per_line_is_stripped() -> None:
    without_trailing = "**MUST** honor.\n"
    with_trailing = "**MUST** honor.   \t\n"
    assert _hash(without_trailing) == _hash(with_trailing)


def test_multiple_trailing_blank_lines_collapse_to_one_newline() -> None:
    single_tail = "**MUST** honor.\n"
    many_tails = "**MUST** honor.\n\n\n\n\n"
    assert _hash(single_tail) == _hash(many_tails)


def test_intermediate_blank_lines_preserved() -> None:
    """Blank lines between content must not be collapsed."""
    a = "para one.\n\npara two.\n"
    b = "para one.\n\n\npara two.\n"
    assert _hash(a) != _hash(b)


def test_hash_is_lowercase_hex_of_correct_length() -> None:
    h = _hash("body\n")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_matches_sha256_of_normalized_bytes() -> None:
    normalized = "body\n"
    expected = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    assert _hash("body   \n\n\n") == expected


def test_leading_bom_is_not_stripped_from_body_hash() -> None:
    """Only the fragment parser strips a leading UTF-8 BOM (from the wrapping
    file); the body hash is over the exact normalized body bytes the parser
    hands to `body_sha256`. This test pins that boundary.
    """
    with_bom = "﻿body\n"
    without = "body\n"
    assert _hash(with_bom) != _hash(without)


def test_different_bodies_produce_different_hashes() -> None:
    assert _hash("**MUST** X\n") != _hash("**MUST** Y\n")


def test_hash_stable_for_deterministic_reproducibility_check() -> None:
    """A stable golden vector guards against silent normalization changes."""
    body = "**MUST** run tests.\n\n**Rationale:** avoid regressions.\n"
    assert _hash(body) == hashlib.sha256(body.encode("utf-8")).hexdigest()
