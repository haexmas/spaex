"""Constitution Clarification persistence (Spec 023 T016).

`.spaex/clarifications.json` schema per
`specs/023-behavior-harness/contracts/clarifications-schema.md`.

The composer subsystem calls into this module for four operations:

- `derive_key(cited)` — SHA256 hex over the sorted `<molecule-id>/<fragment-id>|<body_sha256>`
  lines cited by a clarification (research.md §7, contracts §"Key derivation").
- `load(path)` — read `clarifications.json`, tolerate its absence, reject
  parse errors and unknown `schema_version`.
- `save(path, store)` — atomic tmp+rename write of the whole store.
- `invalidate(store, current_fragments_by_scoped_id)` — recompute each
  entry's key from the current on-disk body hashes; drop the entry when
  the key no longer matches or a cited fragment is missing.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLARIFICATIONS_FILENAME = "clarifications.json"
SCHEMA_VERSION = 1


class ClarificationsStoreError(ValueError):
    """Raised when the on-disk clarifications store is unusable."""


@dataclass(frozen=True)
class CitedFragment:
    """One `(molecule_id, fragment_id, body_sha256)` triple cited by a question."""

    molecule_id: str
    fragment_id: str
    body_sha256: str

    @property
    def scoped_id(self) -> str:
        return f"{self.molecule_id}/{self.fragment_id}"

    def as_json(self) -> dict[str, str]:
        return {
            "molecule_id": self.molecule_id,
            "fragment_id": self.fragment_id,
            "body_sha256": self.body_sha256,
        }

    @staticmethod
    def from_json(obj: Mapping[str, Any]) -> CitedFragment:
        try:
            return CitedFragment(
                molecule_id=str(obj["molecule_id"]),
                fragment_id=str(obj["fragment_id"]),
                body_sha256=str(obj["body_sha256"]),
            )
        except KeyError as exc:
            raise ClarificationsStoreError(
                f"cited_fragments entry missing required field: {exc}"
            ) from exc


@dataclass(frozen=True)
class Clarification:
    """One persisted operator answer."""

    key: str
    question: str
    cited_fragments: tuple[CitedFragment, ...]
    answer: str
    asked_at: str
    answered_at: str

    def as_json(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "cited_fragments": [c.as_json() for c in self.cited_fragments],
            "answer": self.answer,
            "asked_at": self.asked_at,
            "answered_at": self.answered_at,
        }

    @staticmethod
    def from_json(key: str, obj: Mapping[str, Any]) -> Clarification:
        try:
            cited_raw = obj["cited_fragments"]
            if not isinstance(cited_raw, list):
                raise ClarificationsStoreError(
                    f"clarification {key!r} cited_fragments must be a list"
                )
            cited = tuple(
                CitedFragment.from_json(entry)
                for entry in _canonicalize_cited(cited_raw)
            )
            answer = str(obj["answer"])
            if not answer:
                raise ClarificationsStoreError(
                    f"clarification {key!r} answer must be non-empty"
                )
            return Clarification(
                key=key,
                question=str(obj["question"]),
                cited_fragments=cited,
                answer=answer,
                asked_at=str(obj["asked_at"]),
                answered_at=str(obj["answered_at"]),
            )
        except KeyError as exc:
            raise ClarificationsStoreError(
                f"clarification {key!r} missing required field: {exc}"
            ) from exc


@dataclass(frozen=True)
class ClarificationsStore:
    """Whole `.spaex/clarifications.json` in memory."""

    entries: Mapping[str, Clarification] = field(default_factory=dict)

    def with_entry(self, entry: Clarification) -> ClarificationsStore:
        new = dict(self.entries)
        new[entry.key] = entry
        return replace(self, entries=new)

    def without_keys(self, keys: Iterable[str]) -> ClarificationsStore:
        remove = set(keys)
        return replace(
            self, entries={k: v for k, v in self.entries.items() if k not in remove}
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "clarifications": {
                key: self.entries[key].as_json()
                for key in sorted(self.entries)
            },
        }


def derive_key(cited: Iterable[CitedFragment]) -> str:
    """Compute the SHA256-hex clarification key per research.md §7.

    Deterministic ordering: cited fragments sorted by their scoped id, one
    line per entry as `<molecule-id>/<fragment-id>|<body_sha256>`, LF
    separators, no trailing LF.
    """
    ordered = sorted(cited, key=lambda c: c.scoped_id)
    payload = "\n".join(
        f"{c.scoped_id}|{c.body_sha256}" for c in ordered
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load(path: Path) -> ClarificationsStore:
    """Read `clarifications.json`; empty when absent."""
    if not path.exists():
        return ClarificationsStore()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClarificationsStoreError(
            f"could not parse {path}: {exc}. Restore from git or delete."
        ) from exc

    if not isinstance(data, dict):
        raise ClarificationsStoreError(
            f"{path} top-level must be an object, got {type(data).__name__}"
        )
    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ClarificationsStoreError(
            f"{path} schema_version {schema_version!r} is not supported "
            f"(current: {SCHEMA_VERSION})"
        )
    entries_raw = data.get("clarifications", {})
    if not isinstance(entries_raw, dict):
        raise ClarificationsStoreError(
            f"{path} 'clarifications' must be an object"
        )
    entries: dict[str, Clarification] = {}
    for key, obj in entries_raw.items():
        if not isinstance(obj, dict):
            raise ClarificationsStoreError(
                f"clarification {key!r} must be an object"
            )
        entries[str(key)] = Clarification.from_json(str(key), obj)
    return ClarificationsStore(entries=entries)


def save(path: Path, store: ClarificationsStore) -> None:
    """Atomic tmp+rename write of the whole store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(store.as_json(), indent=2, sort_keys=False) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def invalidate(
    store: ClarificationsStore,
    current_body_hashes: Mapping[str, str],
) -> tuple[ClarificationsStore, tuple[str, ...]]:
    """Drop entries whose recomputed key no longer matches the stored key.

    `current_body_hashes` maps `<molecule-id>/<fragment-id>` to the current
    on-disk `body_sha256`. Missing keys mean the fragment is no longer in
    the pinned set; the entry is invalidated.

    Returns the pruned store and the tuple of removed keys.
    """
    to_remove: list[str] = []
    for key, entry in store.entries.items():
        current_cited: list[CitedFragment] = []
        missing = False
        for cited in entry.cited_fragments:
            current_hash = current_body_hashes.get(cited.scoped_id)
            if current_hash is None:
                missing = True
                break
            current_cited.append(
                CitedFragment(
                    molecule_id=cited.molecule_id,
                    fragment_id=cited.fragment_id,
                    body_sha256=current_hash,
                )
            )
        if missing:
            to_remove.append(key)
            continue
        recomputed = derive_key(current_cited)
        if recomputed != key:
            to_remove.append(key)
    return store.without_keys(to_remove), tuple(to_remove)


def _canonicalize_cited(entries: Iterable[Any]) -> list[Mapping[str, Any]]:
    """Sort cited_fragments by scoped id for reproducibility (contract §Storage)."""
    normalized: list[Mapping[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ClarificationsStoreError(
                f"cited_fragments[{index}] must be an object"
            )
        normalized.append(entry)
    normalized.sort(
        key=lambda e: (str(e.get("molecule_id", "")), str(e.get("fragment_id", "")))
    )
    return normalized


def utc_timestamp() -> str:
    """ISO-8601 UTC timestamp (Zulu). Used for `asked_at` / `answered_at`."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "CLARIFICATIONS_FILENAME",
    "SCHEMA_VERSION",
    "CitedFragment",
    "Clarification",
    "ClarificationsStore",
    "ClarificationsStoreError",
    "derive_key",
    "invalidate",
    "load",
    "save",
    "utc_timestamp",
]
