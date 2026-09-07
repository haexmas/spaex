"""Deterministic v1 → v2 rewrite (design-doc migration table)."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from spaex.constitution.safety import validate_no_plaintext_secrets
from spaex.git import remote as git_remote
from spaex.git import revparse as git_revparse
from spaex.git import show as git_show
from spaex.io import json_deterministic
from spaex.model.molecule_id import MoleculeId
from spaex.model.repo_relative_path import RepoRelativePath
from spaex.model.source_url import canonicalize
from spaex.util.errors import (
    AtomIdCollisionError,
    IdentityMismatchError,
    MissingAtomManifestError,
    MissingPublisherManifestError,
    PermissionOnlyEntryError,
)

_ROLE_TO_CONTRIBUTES = {
    "constitution": "constitution",
    "spec": "spec",
    "rules": "rules",
    "hooks": "hooks",
    "skills": "skills",
}

_GITHUB_IDENTITY_RE = re.compile(r"^github\.com/([^/]+)/([^/]+)$")

# Private to the migrate module (research.md D6): the shared package schema
# set went v3-only under Spec 013 (D1), but migrate_v1_to_v2's own output
# contract is unchanged and still targets v2. This mirrors the retired
# haex-hive.v2.schema.json contract for the post-migration sanity check only.
_V2_CONSUMER_MANIFEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["haex_hive_version", "identity", "atoms"],
    "properties": {
        "haex_hive_version": {"const": "2"},
        "haex_hive_min_version": {"$ref": "#/$defs/versionConstraint"},
        "identity": {"$ref": "#/$defs/atomId"},
        "atoms": {"type": "array", "items": {"$ref": "#/$defs/atomEntry"}},
        "groups": {"type": "array", "items": {"type": "string"}},
        "active_feature": {"type": ["string", "null"]},
        "identity_note": {"type": "string"},
    },
    "$defs": {
        "atomId": {
            "type": "string",
            "pattern": (
                r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
            ),
            "minLength": 3,
            "maxLength": 253,
        },
        "versionConstraint": {
            "type": "string",
            "pattern": r"^(?:>=)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$",
        },
        "canonicalSourceUrl": {
            "type": "string",
            "pattern": (
                r"^(?!.*\.git$)(?:https|ssh):\/\/[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?"
                r"(?::[0-9]+)?(?:\/[A-Za-z0-9._~!$&'()*+,;=:%-]+)+$"
            ),
        },
        "fullSha40": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
        "atomEntry": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source", "revision", "includes"],
            "properties": {
                "source": {"$ref": "#/$defs/canonicalSourceUrl"},
                "revision": {"$ref": "#/$defs/fullSha40"},
                "track": {"type": "string", "minLength": 1},
                "includes": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"$ref": "#/$defs/atomId"},
                },
                "config": {
                    "type": "object",
                    "additionalProperties": {"$ref": "#/$defs/configEntry"},
                    "propertyNames": {"$ref": "#/$defs/atomId"},
                },
            },
        },
        "configEntry": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "priority": {"type": "integer"},
                "values": {"type": "object"},
            },
        },
    },
}


def validate_v2_consumer_manifest(data: dict[str, Any]) -> None:
    """Validate migrate_v1_to_v2's own output against the retired v2 shape.

    Raises `ValueError` naming the first violation, mirroring
    `schema.validator.SchemaValidationError`'s message shape closely enough
    for `cli/migrate.py`'s `post-migration-schema-invalid` diagnostic.
    """
    validator = Draft202012Validator(_V2_CONSUMER_MANIFEST_SCHEMA)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = "/" + "/".join(str(token) for token in first.absolute_path)
        raise ValueError(f"{path or '/'}: {first.message}")


def clone_dir(state_root: Path, canonical_source: str) -> Path:
    digest = hashlib.sha256(canonical_source.encode("utf-8")).hexdigest()[:16]
    return state_root / "repos" / digest


def _convert_identity(v1_identity: str) -> str:
    match = _GITHUB_IDENTITY_RE.match(v1_identity)
    if match:
        owner, repo = match.groups()
        candidate = f"com.github.{owner.lower()}.{repo.lower()}"
        return MoleculeId.parse_identity(candidate)
    try:
        return MoleculeId.parse_identity(v1_identity)
    except ValueError as exc:
        raise IdentityMismatchError(
            message=f"identity {v1_identity!r} is neither GitHub-style nor a reverse-DNS ID: {exc}",
            context={"identity": v1_identity},
        ) from None


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _relative_path_segments(path: str) -> list[str]:
    RepoRelativePath.validate(path)
    return [_nfc(seg) for seg in path.split("/")]


def _glob_matches(pattern: str, path: str) -> bool:
    """Match slash-separated globs where ``*`` stays within one segment."""

    pattern_segments = pattern.split("/")
    path_segments = path.split("/")

    def segment_matches(segment_pattern: str, segment: str) -> bool:
        regex = "".join(
            "[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char)
            for char in segment_pattern
        )
        return re.fullmatch(regex, segment) is not None

    def matches(pattern_index: int, path_index: int) -> bool:
        if pattern_index == len(pattern_segments):
            return path_index == len(path_segments)
        segment = pattern_segments[pattern_index]
        if segment == "**":
            return any(
                matches(pattern_index + 1, candidate)
                for candidate in range(path_index, len(path_segments) + 1)
            )
        return (
            path_index < len(path_segments)
            and segment_matches(segment, path_segments[path_index])
            and matches(pattern_index + 1, path_index + 1)
        )

    return matches(0, 0)


@dataclass
class _ResolvedEntry:
    source: str
    revision: str
    atom_id: str


def _select_atom_for_path(
    publisher: dict[str, Any],
    repo_dir: Path,
    revision: str,
    role: str,
    v1_path: str,
) -> str:
    """Match a v1 contribution path to its v2-era atom-id.

    `publisher` is the raw parsed JSON of a v2-era publisher root manifest
    (`{"atoms": {atom_id: {"path": ...}}}`), read independently of the
    (now v3-only) `PublisherManifest` runtime model per research.md D6: this
    migrate-only reader must keep understanding older shapes on its own.
    """
    contributes_key = _ROLE_TO_CONTRIBUTES[role]
    path_segments = _relative_path_segments(v1_path)

    raw_atoms = publisher.get("atoms")
    if not isinstance(raw_atoms, dict):
        raise MissingPublisherManifestError(
            message="publisher manifest atoms must be an object",
            context={"sha_short": revision[:12]},
        )

    matches: list[str] = []
    for atom_id, entry in raw_atoms.items():
        if not isinstance(entry, dict):
            raise MissingAtomManifestError(
                message=f"publisher atom entry {atom_id!r} must be an object",
                context={"atom_id": str(atom_id)},
            )
        entry_path = entry.get("path")
        if not isinstance(entry_path, str):
            raise MissingAtomManifestError(
                message=f"publisher atom entry {atom_id!r} has no string path",
                context={"atom_id": str(atom_id)},
            )
        try:
            atom_segments = _relative_path_segments(entry_path)
        except ValueError as exc:
            raise MissingAtomManifestError(
                message=f"publisher atom entry {atom_id!r} has an invalid path",
                context={"atom_id": str(atom_id), "path": entry_path},
            ) from exc
        if path_segments[: len(atom_segments)] != atom_segments:
            continue
        atom_manifest_bytes = git_show.show_bytes(
            repo_dir,
            revision,
            f"{entry_path}/manifest.json",
            not_found_error=MissingAtomManifestError,
        )
        try:
            atom_data = json.loads(atom_manifest_bytes.decode("utf-8"))
            if not isinstance(atom_data, dict):
                raise ValueError("atom manifest root must be a JSON object")
        except (UnicodeError, ValueError) as exc:
            raise MissingAtomManifestError(
                message=f"atom manifest at {entry_path!r} is invalid",
                context={"path": entry_path, "sha_short": revision[:12]},
            ) from exc
        if "contributes" not in atom_data:
            contributes = {}
        else:
            contributes = atom_data["contributes"]
            if not isinstance(contributes, dict):
                raise MissingAtomManifestError(
                    message=(
                        f"atom manifest at {entry_path!r} has a malformed "
                        "contributes object"
                    ),
                    context={"path": entry_path, "sha_short": revision[:12]},
                )
        declared = contributes.get(contributes_key)
        if declared is None:
            continue
        relative = "/".join(path_segments[len(atom_segments) :])
        is_exact_match = isinstance(declared, str) and _nfc(declared) == relative
        is_glob_match = isinstance(declared, list) and any(
            _glob_matches(_nfc(pattern), relative) for pattern in declared
        )
        if is_exact_match or is_glob_match:
            matches.append(atom_id)
    if not matches:
        raise MissingAtomManifestError(
            message=f"no atom in publisher matches path {v1_path!r} for role {role!r}",
            context={"path": v1_path, "role": role},
        )
    if len(matches) > 1:
        raise AtomIdCollisionError(
            message=f"multiple atoms match path {v1_path!r}: {sorted(matches)}",
            context={"path": v1_path, "matches": ",".join(sorted(matches))},
        )
    return matches[0]


def _resolve_v1_entry(
    entry: dict[str, Any],
    index: int,
    repo_root: Path,
    state_root: Path,
) -> _ResolvedEntry:
    role = entry.get("role")
    repository = entry.get("repository")
    revision = entry.get("revision")
    path = entry.get("path")

    if role is None:
        raise PermissionOnlyEntryError(
            message=f"harness_sources[{index}] is permission-only (no role)",
            context={"entry": str(index)},
        )
    if path is None:
        raise PermissionOnlyEntryError(
            message=f"harness_sources[{index}] has no contribution path",
            context={"entry": str(index)},
        )
    if role not in _ROLE_TO_CONTRIBUTES:
        raise PermissionOnlyEntryError(
            message=f"harness_sources[{index}] role {role!r} is not supported",
            context={"entry": str(index), "role": role},
        )
    if repository is None or revision is None:
        raise PermissionOnlyEntryError(
            message=f"harness_sources[{index}] missing repository or revision",
            context={"entry": str(index)},
        )

    if repository == "self":
        raw_source = git_remote.origin_url(repo_root)
        publisher_dir = repo_root
    else:
        raw_source = repository
        publisher_dir = None  # resolved below

    canonical_source = canonicalize(raw_source)
    if publisher_dir is None:
        publisher_dir = clone_dir(state_root, canonical_source)

    full_sha = git_revparse.full_sha(publisher_dir, revision)

    publisher_bytes = git_show.show_bytes(
        publisher_dir,
        full_sha,
        "manifest.json",
        not_found_error=MissingPublisherManifestError,
    )
    try:
        publisher = json.loads(publisher_bytes.decode("utf-8"))
        if not isinstance(publisher, dict):
            raise ValueError("publisher manifest root must be a JSON object")
    except (UnicodeError, ValueError) as exc:
        raise MissingPublisherManifestError(
            message=f"publisher manifest at {raw_source!r}@{full_sha[:12]} is invalid",
            context={"source": raw_source, "sha_short": full_sha[:12]},
        ) from exc

    atom_id = _select_atom_for_path(publisher, publisher_dir, full_sha, role, path)

    return _ResolvedEntry(
        source=canonical_source,
        revision=full_sha,
        atom_id=atom_id,
    )


def migrate_v1_to_v2(raw_v1: bytes, repo_root: Path, state_root: Path) -> bytes:
    validate_no_plaintext_secrets(raw_v1, location="original .haex-hive.json")

    data = json.loads(raw_v1.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a JSON object")
    if data.get("haex_hive_version") != "1":
        raise ValueError("migrate_v1_to_v2 called on non-v1 input")

    identity_value = data.get("identity")
    if not isinstance(identity_value, str) or not identity_value:
        raise IdentityMismatchError(
            message="v1 manifest does not declare a valid identity",
            context={"field": "identity"},
        )
    identity = _convert_identity(identity_value)

    harness_sources = data.get("harness_sources", [])
    if not isinstance(harness_sources, list):
        raise ValueError("harness_sources must be a JSON array")

    resolved: list[_ResolvedEntry] = []
    for i, entry in enumerate(harness_sources):
        if not isinstance(entry, dict):
            raise ValueError(f"harness_sources[{i}] must be a JSON object")
        resolved.append(_resolve_v1_entry(entry, i, repo_root, state_root))

    grouped: dict[tuple[str, str], list[str]] = {}
    for r in resolved:
        grouped.setdefault((r.source, r.revision), []).append(r.atom_id)

    atoms_out = []
    for (source, revision), atom_ids in sorted(grouped.items()):
        includes = sorted(set(atom_ids), key=lambda s: s.encode("utf-8"))
        atoms_out.append(
            {
                "source": source,
                "revision": revision,
                "includes": includes,
            }
        )

    obj: dict[str, Any] = {
        "haex_hive_version": "2",
        "haex_hive_min_version": ">=2.0.0",
        "identity": identity,
        "atoms": atoms_out,
    }

    if "identity_note" in data:
        obj["identity_note"] = data["identity_note"]
    if "groups" in data:
        obj["groups"] = data["groups"]
    if "active_feature" in data:
        obj["active_feature"] = data["active_feature"]

    result = json_deterministic.dumps(obj)
    validate_no_plaintext_secrets(result, location="proposed v2 sidecar")
    return result
