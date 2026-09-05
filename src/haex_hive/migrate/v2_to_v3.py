"""v2 → v3 transform per contracts/haex-migrate.v2-to-v3.md (Spec 013 T050/T051).

Pure functions: same input bytes yield byte-identical proposal bytes across
satellites and OSes. The transform never reads any file outside the input
manifest; directory-form ``contributes.<cat> = "<dir>/"`` entries are refused
(``directory-form-contributes-unsupported``) precisely because expanding them
would break that byte-identical-determinism guarantee.

Shape routing (``v2_to_v3``):

- ``compounds`` or ``atoms`` list at the top level + ``identity`` → consumer.
- ``publisher`` at the top level → publisher root.
- ``contributes`` or ``atoms`` map at the top level with an ``id`` → molecule.

``haex_hive_version`` alone does not disambiguate (v2 uses ``"2"`` for all
three shapes); the field-presence heuristic above is what routes each input.
"""

from __future__ import annotations

import re
from typing import Any

from haex_hive.io import json_deterministic
from haex_hive.util import exit_codes
from haex_hive.util.errors import HaexError

_MIN_VERSION_RE = re.compile(r"^(>=)?(\d+)\.(\d+)\.(\d+)$")


class DirectoryFormContributesUnsupportedError(HaexError):
    diagnostic_key: str = "directory-form-contributes-unsupported"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = (
        "Enumerate the intended files as an explicit list in the v2 source "
        "manifest before rerunning `haex migrate`."
    )


class UnsupportedMinVersionConstraintError(HaexError):
    diagnostic_key: str = "unsupported-min-version-constraint"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = (
        "Rewrite `haex_hive_min_version` to an exact `2.x.y` or `>=2.x.y` "
        "before rerunning migrate."
    )


class UnrecognizedManifestShapeError(HaexError):
    diagnostic_key: str = "unrecognized-manifest-shape"
    exit_code: int = exit_codes.INPUT_REFUSE
    hint: str = (
        "Input does not look like a v2 consumer, publisher, or molecule "
        "manifest."
    )


def rewrite_min_version(value: str) -> str:
    """Rewrite a v2 ``haex_hive_min_version`` to its v3 equivalent."""
    match = _MIN_VERSION_RE.match(value)
    if not match:
        raise UnsupportedMinVersionConstraintError(
            message=f"cannot parse haex_hive_min_version: {value!r}",
            context={"value": value},
        )
    op, major, minor, patch = match.groups()
    if major != "2":
        raise UnsupportedMinVersionConstraintError(
            message=(
                f"haex_hive_min_version {value!r} has unsupported major "
                f"{major!r}; only 2.x.y or >=2.x.y are migratable"
            ),
            context={"value": value, "major": major},
        )
    if op == ">=":
        return ">=3.0.0"
    return f"3.{minor}.{patch}"


def is_v3(data: dict[str, Any]) -> bool:
    """Return True when the input is already in v3 shape (idempotency check)."""
    return data.get("haex_hive_version") == "3"


def _looks_like_consumer(data: dict[str, Any]) -> bool:
    return "identity" in data and ("atoms" in data or "compounds" in data)


def _looks_like_publisher(data: dict[str, Any]) -> bool:
    return "publisher" in data and (
        "atoms" in data or "molecules" in data
    )


def _looks_like_molecule(data: dict[str, Any]) -> bool:
    return "id" in data and (
        "contributes" in data or "atoms" in data
    )


def _v2_consumer_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"haex_hive_version": "3", "identity": data["identity"]}
    if "haex_hive_min_version" in data:
        result["haex_hive_min_version"] = rewrite_min_version(
            data["haex_hive_min_version"]
        )
    old_compounds = data.get("compounds") or data.get("atoms") or []
    new_compounds: list[dict[str, Any]] = []
    for entry in old_compounds:
        new_entry: dict[str, Any] = {
            "source": entry["source"],
            "revision": entry["revision"],
            "molecules": list(entry.get("molecules") or entry.get("includes") or []),
        }
        if "track" in entry:
            new_entry["track"] = entry["track"]
        if "config" in entry:
            new_entry["config"] = entry["config"]
        new_compounds.append(new_entry)
    result["compounds"] = new_compounds
    for optional in ("groups", "active_feature", "identity_note"):
        if optional in data:
            result[optional] = data[optional]
    return result


def _v2_publisher_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"haex_hive_version": "3", "publisher": data["publisher"]}
    old_molecules = data.get("molecules") or data.get("atoms") or {}
    new_molecules: dict[str, Any] = {}
    for mid, entry in old_molecules.items():
        new_entry: dict[str, Any] = {
            "path": entry["path"],
            "version": entry["version"],
        }
        if "description" in entry:
            new_entry["description"] = entry["description"]
        new_molecules[mid] = new_entry
    result["molecules"] = new_molecules
    return result


def _v2_molecule_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "haex_hive_version": "3",
        "id": data["id"],
        "version": data["version"],
    }
    result["priority"] = int(data.get("priority", 100))
    if "atoms" in data and isinstance(data["atoms"], dict):
        result["atoms"] = {
            category: list(paths) for category, paths in data["atoms"].items()
        }
    else:
        contributes = data.get("contributes", {})
        directory_form: list[str] = []
        atoms: dict[str, list[str]] = {}
        for category, raw_value in contributes.items():
            if isinstance(raw_value, str):
                if raw_value.endswith("/"):
                    directory_form.append(category)
                    continue
                atoms[category] = [raw_value]
            elif isinstance(raw_value, list):
                for item in raw_value:
                    if isinstance(item, str) and item.endswith("/"):
                        directory_form.append(category)
                        break
                else:
                    atoms[category] = list(raw_value)
        if directory_form:
            raise DirectoryFormContributesUnsupportedError(
                message=(
                    "v2 molecule declares directory-form contributes for "
                    f"{sorted(set(directory_form))}"
                ),
                context={
                    "id": str(data.get("id", "")),
                    "categories": ",".join(sorted(set(directory_form))),
                },
            )
        result["atoms"] = atoms
    for optional in ("defaults", "config_schema"):
        if optional in data:
            result[optional] = data[optional]
    return result


def v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    """Route a parsed v2 manifest object through the correct sub-transform."""
    if is_v3(data):
        return data
    if _looks_like_consumer(data):
        return _v2_consumer_to_v3(data)
    if _looks_like_publisher(data):
        return _v2_publisher_to_v3(data)
    if _looks_like_molecule(data):
        return _v2_molecule_to_v3(data)
    raise UnrecognizedManifestShapeError(
        message="input does not match any known v2 manifest shape"
    )


def v2_to_v3_bytes(raw: bytes) -> bytes:
    """Convenience wrapper: parse, transform, re-serialize deterministically."""
    import json

    data = json.loads(raw.decode("utf-8"))
    return json_deterministic.dumps(v2_to_v3(data))
