"""Canonical source URL normalization (D3, R9).

Accepted schemes on output: `https` and `ssh`, both lowercase, both userinfo-
free. During migration input normalization only, credential-free SCP form
`git@host:path` and `ssh://git@host/path` map to `ssh://host/path`. Every
other userinfo, every other scheme (including `git://`), and any credential
material are refused.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from spaex.util.errors import CredentialInUrlError, UnsupportedSchemeError

_SCP_RE = re.compile(r"^([^@:/\s]+)@([^:/\s]+):(.+)$")
_ALLOWED_SCHEMES = frozenset({"https", "ssh"})


def _refuse_credentials() -> None:
    raise CredentialInUrlError(
        message="source URL contains credentials",
        context={"scheme": "redacted"},
    )


def _refuse_scheme(scheme: str) -> None:
    raise UnsupportedSchemeError(
        message=f"unsupported source URL scheme: {scheme!r}",
        context={"scheme": scheme},
    )


def canonicalize(url: str) -> str:
    if not isinstance(url, str) or not url:
        raise ValueError("source URL must be a non-empty string")

    scp_match = _SCP_RE.match(url)
    if scp_match and "://" not in url:
        user, host, path = scp_match.groups()
        if user != "git":
            _refuse_credentials()
        url = f"ssh://{host.lower()}/{path}"

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        _refuse_scheme(scheme)

    userinfo = parts.username
    if userinfo is not None:
        if scheme == "ssh" and userinfo == "git" and not parts.password:
            userinfo = None
        else:
            _refuse_credentials()
    if parts.password:
        _refuse_credentials()

    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"source URL missing host: {url!r}")

    port = f":{parts.port}" if parts.port else ""
    path = parts.path or ""
    while path.endswith("/"):
        path = path[:-1]
    if path.endswith(".git"):
        path = path[:-4]

    return f"{scheme}://{host}{port}{path}"


class CanonicalSourceUrl:
    __slots__ = ()

    @staticmethod
    def validate(url: str) -> str:
        canonical = canonicalize(url)
        if canonical != url:
            raise ValueError(
                f"source URL is not canonical: got {url!r}, expected {canonical!r}"
            )
        return url
