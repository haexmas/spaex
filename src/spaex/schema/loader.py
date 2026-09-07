"""Package-data JSON Schema loader."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

_KNOWN_SCHEMAS = frozenset(
    {
        "consumer-manifest.v4.schema.json",
        "publisher-manifest.v4.schema.json",
        "molecule-manifest.v4.schema.json",
        "install-lock.v4.schema.json",
    }
)


def load(name: str) -> dict[str, Any]:
    if name not in _KNOWN_SCHEMAS:
        raise KeyError(f"unknown schema name: {name!r}")
    resource = files("spaex.schema.data").joinpath(name)
    text = resource.read_text(encoding="utf-8")
    return json.loads(text)
