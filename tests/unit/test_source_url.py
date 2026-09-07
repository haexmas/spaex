from __future__ import annotations

import pytest

from spaex.model.source_url import CanonicalSourceUrl, canonicalize
from spaex.util.errors import CredentialInUrlError, UnsupportedSchemeError


@pytest.mark.parametrize(
    "input_url,expected",
    [
        ("https://github.com/example/repo", "https://github.com/example/repo"),
        ("https://github.com/example/repo.git", "https://github.com/example/repo"),
        ("https://github.com/example/repo/", "https://github.com/example/repo"),
        ("https://GITHUB.COM/example/repo", "https://github.com/example/repo"),
        ("ssh://git@github.com/example/repo", "ssh://github.com/example/repo"),
        ("git@github.com:example/repo.git", "ssh://github.com/example/repo"),
    ],
)
def test_canonicalize(input_url: str, expected: str) -> None:
    assert canonicalize(input_url) == expected


def test_rejects_credentials() -> None:
    with pytest.raises(CredentialInUrlError):
        canonicalize("https://user:pass@github.com/example/repo")


def test_rejects_git_scheme() -> None:
    with pytest.raises(UnsupportedSchemeError):
        canonicalize("git://github.com/example/repo")


def test_validate_requires_canonical_form() -> None:
    CanonicalSourceUrl.validate("https://github.com/example/repo")
    with pytest.raises(ValueError):
        CanonicalSourceUrl.validate("https://github.com/example/repo.git")
