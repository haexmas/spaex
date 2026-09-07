"""Detect `.haex-hive.json` version."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from spaex.util.errors import HaexError, InvalidHaexHiveManifestError


@dataclass
class UnsupportedHaexHiveVersionError(HaexError):
    diagnostic_key: str = "unsupported-haex-hive-version"
    exit_code: int = 5
    hint: str = "Expected haex_hive_version 1 or 2."


def detect_version(raw: bytes) -> Literal[1, 2]:
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise InvalidHaexHiveManifestError(
            message=".haex-hive.json root must be a JSON object",
            context={"got": type(data).__name__},
        )
    version = data.get("haex_hive_version")
    if version == "1":
        return 1
    if version == "2":
        return 2
    raise UnsupportedHaexHiveVersionError(
        message=f"unsupported haex_hive_version {version!r}",
        context={"got": str(version)},
    )
