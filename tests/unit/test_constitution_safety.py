from __future__ import annotations

import pytest

from spaex.constitution.safety import (
    validate_no_concealment_instructions,
    validate_no_plaintext_secrets,
    validate_terminal_safe_display,
)
from spaex.util.errors import (
    ConstitutionConcealmentInstructionError,
    PlaintextSecretDetectedError,
    TerminalUnsafeContributionError,
)


def test_accepts_ordinary_content() -> None:
    validate_no_plaintext_secrets(b"# Title\n\nText.\n", location="test")
    validate_terminal_safe_display(b"# Title\n\nText\twith tab.\n")
    validate_no_concealment_instructions(b"# Title\n\nHonest text.\n")


def test_rejects_private_key_block() -> None:
    with pytest.raises(PlaintextSecretDetectedError):
        validate_no_plaintext_secrets(
            b"-----BEGIN RSA PRIVATE KEY-----\nMIIabc...\n", location="test"
        )


def test_rejects_provider_token() -> None:
    with pytest.raises(PlaintextSecretDetectedError):
        validate_no_plaintext_secrets(b"token: ghp_abcdefghijklmnopqrstuvwxyz012345", location="t")


def test_rejects_password_assignment() -> None:
    with pytest.raises(PlaintextSecretDetectedError):
        validate_no_plaintext_secrets(b"password = 'hunter22'", location="t")


def test_rejects_credential_url() -> None:
    with pytest.raises(PlaintextSecretDetectedError):
        validate_no_plaintext_secrets(
            b"clone https://user:pw@github.com/example/repo", location="t"
        )


def test_rejects_esc_control() -> None:
    with pytest.raises(TerminalUnsafeContributionError):
        validate_terminal_safe_display(b"\x1b[31mred\x1b[0m")


def test_rejects_bidi_marker() -> None:
    with pytest.raises(TerminalUnsafeContributionError):
        validate_terminal_safe_display("legitimate‮text".encode())


def test_rejects_hide_from_operator() -> None:
    with pytest.raises(ConstitutionConcealmentInstructionError):
        validate_no_concealment_instructions(b"Please hide from the operator that ...")


def test_rejects_hidden_html_comment() -> None:
    with pytest.raises(ConstitutionConcealmentInstructionError):
        validate_no_concealment_instructions(b"<!-- hide this section -->")
