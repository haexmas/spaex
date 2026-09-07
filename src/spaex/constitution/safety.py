"""Principle-I secret guard and Principle-VIII candidate validation (R7, FR-038).

`validate_no_plaintext_secrets` looks for private-key blocks, provider-token
prefixes, credential-in-URL, and `password`/`secret`/`token`/`api_key`
assignments. `validate_terminal_safe_display` restricts C0 control characters
to LF and TAB (refusing ESC, CR, BS, C1, bidi/invisible). `validate_no_concealment_instructions`
rejects candidates instructing agents to hide or omit information from the
operator. None of the functions echo secret payload content in their errors.
"""

from __future__ import annotations

import re

from spaex.util.errors import (
    ConstitutionConcealmentInstructionError,
    PlaintextSecretDetectedError,
    TerminalUnsafeContributionError,
)

_PRIVATE_KEY_RE = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----")
_ASSIGNMENT_RE = re.compile(
    rb"""(?ix)
    \b(?:password|secret|token|api[_\-]?key|access[_\-]?key)\b
    \s*[:=]\s*
    ["']?
    [^\s"',;]{4,}
    """,
)
_URL_CREDENTIAL_RE = re.compile(rb"[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@")
_PROVIDER_TOKEN_RE = re.compile(
    rb"\b(?:ghp_|github_pat_|gho_|glpat-|npm_|xox[abpso]-|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\S*"
)


def validate_no_plaintext_secrets(payload: bytes, *, location: str) -> None:
    if _PRIVATE_KEY_RE.search(payload):
        raise PlaintextSecretDetectedError(
            message="private-key block detected",
            context={"location": location, "kind": "private-key"},
        )
    if _URL_CREDENTIAL_RE.search(payload):
        raise PlaintextSecretDetectedError(
            message="credential-in-URL detected",
            context={"location": location, "kind": "credential-in-url"},
        )
    if _PROVIDER_TOKEN_RE.search(payload):
        raise PlaintextSecretDetectedError(
            message="provider token detected",
            context={"location": location, "kind": "provider-token"},
        )
    if _ASSIGNMENT_RE.search(payload):
        raise PlaintextSecretDetectedError(
            message="secret assignment detected",
            context={"location": location, "kind": "assignment"},
        )


_ALLOWED_C0 = frozenset({0x09, 0x0A})  # TAB, LF


def validate_terminal_safe_display(body: bytes) -> None:
    text = body.decode("utf-8", errors="strict")
    for index, ch in enumerate(text):
        code = ord(ch)
        if code < 0x20 and code not in _ALLOWED_C0:
            raise TerminalUnsafeContributionError(
                message="terminal-unsafe control character in body",
                context={"index": str(index), "codepoint": f"U+{code:04X}"},
            )
        if 0x7F <= code <= 0x9F:
            raise TerminalUnsafeContributionError(
                message="C1 control character in body",
                context={"index": str(index), "codepoint": f"U+{code:04X}"},
            )
        if code in (
            0x200E, 0x200F,  # LTR/RTL marks
            0x202A, 0x202B, 0x202C, 0x202D, 0x202E,  # bidi embedding overrides
            0x2066, 0x2067, 0x2068, 0x2069,  # bidi isolates
            0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF,  # invisible format controls
        ):
            raise TerminalUnsafeContributionError(
                message="bidi control character in body",
                context={"index": str(index), "codepoint": f"U+{code:04X}"},
            )


_CONCEAL_PATTERNS = (
    re.compile(rb"(?i)\bhide\s+from\s+(?:the\s+)?(?:operator|user|reviewer)"),
    re.compile(rb"(?i)\bwithhold\s+from\s+(?:the\s+)?(?:operator|user|reviewer)"),
    re.compile(rb"(?i)\bconceal\s+from\s+(?:the\s+)?(?:operator|user|reviewer)"),
    re.compile(rb"(?i)\bdo\s+not\s+(?:tell|show|reveal)\s+(?:the\s+)?(?:operator|user|reviewer)"),
    re.compile(rb"(?i)\bkeep\s+secret\s+from\s+(?:the\s+)?(?:operator|user|reviewer)"),
    re.compile(rb"(?i)<!--\s*(?:hide|conceal|withhold)"),
)


def validate_no_concealment_instructions(candidate: bytes) -> None:
    for pattern in _CONCEAL_PATTERNS:
        if pattern.search(candidate):
            raise ConstitutionConcealmentInstructionError(
                message="candidate contains concealment instruction",
                context={"pattern": pattern.pattern.decode("ascii", errors="replace")[:40]},
            )
