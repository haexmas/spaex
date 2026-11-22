"""Persisted operator decisions about findings (Spec 030, research R5 and R8).

`.spaex/decisions.json` holds the operator's answer to every finding of the
check, bound to the exact text of the passages it concerns, and the state of
the last completed check. The composed constitution is a pure function of the
fragments and the valid decisions.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from spaex.behavior.fragment import BehaviorFragment
from spaex.behavior.passages import PassageError, fragment_index, locate, validate_range

SCHEMA_VERSION = 1
DECISIONS_FILENAME = "decisions.json"
FORMAT_VERSION = "2"


class DecisionsStoreError(ValueError):
    """Raised when the on-disk decisions file is unusable."""


@dataclass(frozen=True)
class PassageRef:
    """A passage a decision concerns: fragment, text hash and the text itself."""

    scoped_id: str
    text_hash: str
    text: str

    def as_json(self) -> dict[str, str]:
        return {"scoped_id": self.scoped_id, "text_hash": self.text_hash, "text": self.text}

    @staticmethod
    def from_json(obj: Mapping[str, Any]) -> PassageRef:
        try:
            return PassageRef(
                scoped_id=str(obj["scoped_id"]),
                text_hash=str(obj["text_hash"]),
                text=str(obj["text"]),
            )
        except KeyError as exc:
            raise DecisionsStoreError(f"passage entry missing field {exc}") from exc


@dataclass(frozen=True)
class Choice:
    """`keep` one passage (index into `passages`), or `keep_all`."""

    kind: Literal["keep", "keep_all"]
    kept: int | None = None

    def as_json(self) -> dict[str, Any]:
        if self.kind == "keep":
            return {"kind": "keep", "kept": self.kept}
        return {"kind": "keep_all"}

    @staticmethod
    def from_json(obj: Mapping[str, Any]) -> Choice:
        kind = obj.get("kind")
        if kind == "keep_all":
            return Choice(kind="keep_all")
        if (
            kind == "keep"
            and isinstance(obj.get("kept"), int)
            and not isinstance(obj.get("kept"), bool)
        ):
            return Choice(kind="keep", kept=int(obj["kept"]))
        raise DecisionsStoreError(f"unknown choice {dict(obj)!r}")


@dataclass(frozen=True)
class Decision:
    """The operator's answer to one finding."""

    key: str
    kind: str
    summary: str
    passages: tuple[PassageRef, ...]
    choice: Choice
    asked_at: str
    answered_at: str

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "passages": [p.as_json() for p in self.passages],
            "choice": self.choice.as_json(),
            "asked_at": self.asked_at,
            "answered_at": self.answered_at,
        }

    @staticmethod
    def from_json(key: str, obj: Mapping[str, Any]) -> Decision:
        try:
            raw_passages = obj["passages"]
            if not isinstance(raw_passages, list) or any(
                not isinstance(passage, Mapping) for passage in raw_passages
            ):
                raise DecisionsStoreError(f"decision {key!r}: passages must be a list of objects")
            raw_choice = obj["choice"]
            if not isinstance(raw_choice, Mapping):
                raise DecisionsStoreError(f"decision {key!r}: choice must be an object")
            passages = tuple(PassageRef.from_json(p) for p in raw_passages)
            choice = Choice.from_json(raw_choice)
            if choice.kind == "keep" and not (
                choice.kept is not None and 0 <= choice.kept < len(passages)
            ):
                raise DecisionsStoreError(f"decision {key!r}: kept index out of range")
            return Decision(
                key=key,
                kind=str(obj["kind"]),
                summary=str(obj["summary"]),
                passages=passages,
                choice=choice,
                asked_at=str(obj["asked_at"]),
                answered_at=str(obj["answered_at"]),
            )
        except KeyError as exc:
            raise DecisionsStoreError(f"decision {key!r} missing field {exc}") from exc


@dataclass(frozen=True)
class Checked:
    """Fragment fingerprint and effective check prompt of the last completed check."""

    source_hash: str
    prompt_hash: str


@dataclass(frozen=True)
class DecisionStore:
    """Whole `decisions.json` in memory."""

    checked: Checked | None = None
    decisions: Mapping[str, Decision] = field(default_factory=dict)

    def with_decision(self, decision: Decision) -> DecisionStore:
        updated = dict(self.decisions)
        updated[decision.key] = decision
        return replace(self, decisions=updated)

    def with_checked(self, checked: Checked | None) -> DecisionStore:
        return replace(self, checked=checked)

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
        if self.checked is not None:
            payload["checked"] = {
                "source_hash": self.checked.source_hash,
                "prompt_hash": self.checked.prompt_hash,
            }
        payload["decisions"] = {
            key: self.decisions[key].as_json() for key in sorted(self.decisions)
        }
        return payload


def load(path: Path) -> DecisionStore:
    """Read `decisions.json`; empty when absent."""
    if not path.exists():
        return DecisionStore()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DecisionsStoreError(
            f"could not parse {path}: {exc}. Restore from git or delete."
        ) from exc
    if not isinstance(data, dict):
        raise DecisionsStoreError(f"{path} top-level must be an object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise DecisionsStoreError(
            f"{path} schema_version {data.get('schema_version')!r} is not supported "
            f"(current: {SCHEMA_VERSION})"
        )
    checked_raw = data.get("checked")
    checked: Checked | None = None
    if checked_raw is not None:
        if not isinstance(checked_raw, dict):
            raise DecisionsStoreError(f"{path} 'checked' must be an object")
        try:
            checked = Checked(
                source_hash=str(checked_raw["source_hash"]),
                prompt_hash=str(checked_raw["prompt_hash"]),
            )
        except KeyError as exc:
            raise DecisionsStoreError(f"{path} 'checked' missing field {exc}") from exc
    raw_decisions = data.get("decisions", {})
    if not isinstance(raw_decisions, dict):
        raise DecisionsStoreError(f"{path} 'decisions' must be an object")
    decisions: dict[str, Decision] = {}
    for key, obj in raw_decisions.items():
        if not isinstance(obj, dict):
            raise DecisionsStoreError(f"decision {key!r} must be an object")
        decisions[str(key)] = Decision.from_json(str(key), obj)
    return DecisionStore(checked=checked, decisions=decisions)


def save(path: Path, store: DecisionStore) -> None:
    """Atomic tmp+rename write of the whole store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(store.as_json(), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def valid_decisions(
    store: DecisionStore, fragments: Sequence[BehaviorFragment]
) -> tuple[Decision, ...]:
    """Decisions whose passages all still occur exactly once in their fragments.

    Sorted by key. A decision about a passage that changed or vanished is not
    valid; the finding is asked again if the check still reports it.
    """
    index = fragment_index(fragments)
    valid: list[Decision] = []
    for key in sorted(store.decisions):
        decision = store.decisions[key]
        retained = True
        for ref in decision.passages:
            fragment = index.get(ref.scoped_id)
            if fragment is None:
                retained = False
                break
            span = locate(fragment, ref.text)
            if span is None:
                retained = False
                break
            try:
                validate_range(fragment, *span)
            except PassageError:
                retained = False
                break
        if retained:
            valid.append(decision)
    return tuple(valid)


def build_input_hash(decisions: Sequence[Decision]) -> str:
    """Header fingerprint of the valid decisions (contracts/spaex-md-format-v2.md).

    Covers the format version and the key and choice of every valid decision,
    nothing about the check, so a changed check prompt never changes the text.
    """
    lines = [f"format|{FORMAT_VERSION}"]
    for decision in sorted(decisions, key=lambda d: d.key):
        choice = (
            f"keep:{decision.choice.kept}"
            if decision.choice.kind == "keep"
            else "keep_all"
        )
        lines.append(f"{decision.key}|{choice}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


__all__ = [
    "DECISIONS_FILENAME",
    "FORMAT_VERSION",
    "SCHEMA_VERSION",
    "Checked",
    "Choice",
    "Decision",
    "DecisionStore",
    "DecisionsStoreError",
    "PassageRef",
    "build_input_hash",
    "load",
    "save",
    "valid_decisions",
]
