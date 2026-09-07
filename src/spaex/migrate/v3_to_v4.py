"""v3 → v4 transform per contracts/spaex-migrate.v3-to-v4.md (Spec 014 T030, T031).

Pure functions: same input bytes yield byte-identical proposal bytes across
satellites and OSes. The transform never reads any file outside the input
manifest.

Shape routing (``v3_to_v4``):

- ``compounds`` list at the top level + ``identity`` -> consumer.
- ``publisher`` at the top level + ``molecules`` map -> publisher root.
- ``id`` + ``atoms`` map at the top level -> molecule.
- ``generation_id`` at the top level + ``molecules`` list -> install lock
  (returned unchanged; the migrate CLI skips install.lock inputs by contract,
  but the transform handles the shape defensively).

The only field-level delta v3->v4:

- ``haex_hive_version: "3"`` renamed to ``spaex_version: "4"`` on all shapes.
- ``haex_hive_min_version`` (consumer only) renamed to ``spaex_min_version``,
  with the min-version-bump rule from ``rewrite_min_version`` applied.

Every other field passes through unchanged, so the transform is structurally a
no-op modulo those two field renames.
"""

from __future__ import annotations

import json
import re
from typing import Any, NoReturn

from spaex.io import json_deterministic
from spaex.util import exit_codes
from spaex.util.errors import HaexError, MigrationManifestInvalidError

_MIN_VERSION_RE = re.compile(r"^(>=)?(\d+)\.(\d+)\.(\d+)$")


class UnsupportedMinVersionConstraintError(HaexError):
    diagnostic_key: str = "unsupported-min-version-constraint"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = (
        "Rewrite `haex_hive_min_version` to an exact `3.x.y` or `>=3.x.y` "
        "before rerunning migrate."
    )


class UnrecognizedManifestShapeError(HaexError):
    diagnostic_key: str = "unrecognized-manifest-shape"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = (
        "Input does not look like a v3 consumer, publisher, molecule, or "
        "install-lock manifest."
    )


def _invalid_manifest(message: str, *, field: str) -> NoReturn:
    raise MigrationManifestInvalidError(message=message, context={"field": field})


def rewrite_min_version(value: str) -> str:
    """Rewrite a v3 ``haex_hive_min_version`` to its v4 equivalent.

    Rules per contract:

    - Exact ``3.X.Y`` becomes ``4.X.Y``.
    - Lower-bound ``>=3.X.Y`` becomes ``>=4.0.0``.
    - Any other form refuses with ``unsupported-min-version-constraint``.
    """
    match = _MIN_VERSION_RE.match(value)
    if not match:
        raise UnsupportedMinVersionConstraintError(
            message=f"cannot parse haex_hive_min_version: {value!r}",
            context={"value": value},
        )
    op, major, minor, patch = match.groups()
    if major != "3":
        raise UnsupportedMinVersionConstraintError(
            message=(
                f"haex_hive_min_version {value!r} has unsupported major "
                f"{major!r}; only 3.x.y or >=3.x.y are migratable"
            ),
            context={"value": value, "major": major},
        )
    if op == ">=":
        return ">=4.0.0"
    return f"4.{minor}.{patch}"


def is_v4(data: dict[str, Any]) -> bool:
    """Return True when the input is already in v4 shape (idempotency check)."""
    return data.get("spaex_version") == "4"


def _looks_like_consumer(data: dict[str, Any]) -> bool:
    return "identity" in data and "compounds" in data


def _looks_like_publisher(data: dict[str, Any]) -> bool:
    return "publisher" in data and "molecules" in data and isinstance(
        data.get("molecules"), dict
    )


def _looks_like_molecule(data: dict[str, Any]) -> bool:
    return (
        "id" in data
        and "atoms" in data
        and isinstance(data.get("atoms"), dict)
    )


def _looks_like_install_lock(data: dict[str, Any]) -> bool:
    return "generation_id" in data and isinstance(data.get("molecules"), list)


def _validate_consumer(data: dict[str, Any]) -> None:
    if not isinstance(data.get("identity"), str):
        _invalid_manifest("consumer manifest identity must be a string", field="identity")
    if "haex_hive_min_version" in data and not isinstance(
        data["haex_hive_min_version"], str
    ):
        _invalid_manifest(
            "consumer manifest haex_hive_min_version must be a string",
            field="haex_hive_min_version",
        )
    compounds = data.get("compounds")
    if not isinstance(compounds, list):
        _invalid_manifest(
            "consumer manifest compounds must be an array", field="compounds"
        )


def _validate_publisher(data: dict[str, Any]) -> None:
    if not isinstance(data.get("publisher"), str):
        _invalid_manifest("publisher manifest publisher must be a string", field="publisher")
    if not isinstance(data.get("molecules"), dict):
        _invalid_manifest(
            "publisher manifest molecules must be an object", field="molecules"
        )


def _validate_molecule(data: dict[str, Any]) -> None:
    for required in ("id", "version"):
        if not isinstance(data.get(required), str):
            _invalid_manifest(
                f"molecule manifest is missing string {required}", field=required
            )
    if not isinstance(data.get("atoms"), dict):
        _invalid_manifest("molecule manifest atoms must be an object", field="atoms")
    for category, paths in data["atoms"].items():
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            _invalid_manifest(
                "molecule manifest atoms values must be arrays of strings",
                field=f"atoms.{category}",
            )


def _v3_consumer_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"spaex_version": "4", "identity": data["identity"]}
    if "haex_hive_min_version" in data:
        result["spaex_min_version"] = rewrite_min_version(data["haex_hive_min_version"])
    if "spaex_min_version" in data and "haex_hive_min_version" not in data:
        result["spaex_min_version"] = data["spaex_min_version"]
    result["compounds"] = list(data["compounds"])
    for optional in ("groups", "active_feature", "identity_note"):
        if optional in data:
            result[optional] = data[optional]
    return result


def _v3_publisher_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "spaex_version": "4",
        "publisher": data["publisher"],
        "molecules": dict(data["molecules"]),
    }


def _v3_molecule_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "spaex_version": "4",
        "id": data["id"],
        "version": data["version"],
    }
    if "priority" in data:
        result["priority"] = data["priority"]
    result["atoms"] = {
        category: list(paths) for category, paths in data["atoms"].items()
    }
    for optional in ("defaults", "config_schema"):
        if optional in data:
            result[optional] = data[optional]
    return result


def _v3_install_lock_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "spaex_version": "4",
        "generation_id": data["generation_id"],
        "molecules": list(data["molecules"]),
    }


def v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    """Route a parsed v3 manifest object through the correct sub-transform."""
    if not isinstance(data, dict):
        _invalid_manifest("manifest root must be an object", field="/")
    if is_v4(data):
        return data
    if _looks_like_consumer(data):
        _validate_consumer(data)
        return _v3_consumer_to_v4(data)
    if _looks_like_publisher(data):
        _validate_publisher(data)
        return _v3_publisher_to_v4(data)
    if _looks_like_molecule(data):
        _validate_molecule(data)
        return _v3_molecule_to_v4(data)
    if _looks_like_install_lock(data):
        return _v3_install_lock_to_v4(data)
    raise UnrecognizedManifestShapeError(
        message="input does not match any known v3 manifest shape"
    )


def v3_to_v4_bytes(raw: bytes) -> bytes:
    """Parse, transform, re-serialize deterministically."""
    data = json.loads(raw.decode("utf-8"))
    return json_deterministic.dumps(v3_to_v4(data))
