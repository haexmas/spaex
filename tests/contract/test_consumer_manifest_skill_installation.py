"""Contract tests for Spec 018 US3 `skill_installation` consumer policy.

See contracts/consumer-manifest-skill-installation.v1.md.
"""

from __future__ import annotations

import pytest

from spaex.model.consumer_manifest import ConsumerManifest, SkillInstallationPolicy
from spaex.schema import validator as schema_validator

_SCHEMA = "consumer-manifest.v4.schema.json"
_SHA40 = "0" * 40
_URL = "https://github.com/example/publisher"


def _valid() -> dict:
    return {
        "spaex_version": "4",
        "identity": "com.example.consumer",
        "compounds": [
            {
                "source": _URL,
                "revision": _SHA40,
                "molecules": ["com.example.publisher.alpha"],
            }
        ],
    }


def _with_policy(policy: dict) -> dict:
    data = _valid()
    data["skill_installation"] = policy
    return data


@pytest.mark.parametrize("mode", ["prompt", "managed", "disabled"])
def test_managed_policy_with_all_fields_is_valid(mode: str) -> None:
    policy = {"mode": mode}
    if mode == "managed":
        policy.update({"adapter": "skillsmd", "scope": "project", "agents": ["codex"]})
    schema_validator.validate(_with_policy(policy), _SCHEMA)


def test_prompt_mode_without_operational_fields_is_valid() -> None:
    schema_validator.validate(_with_policy({"mode": "prompt"}), _SCHEMA)


def test_disabled_mode_without_operational_fields_is_valid() -> None:
    schema_validator.validate(_with_policy({"mode": "disabled"}), _SCHEMA)


def test_absent_policy_is_valid() -> None:
    schema_validator.validate(_valid(), _SCHEMA)


def test_missing_mode_is_rejected() -> None:
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_policy({"adapter": "skillsmd"}), _SCHEMA)


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_policy({"mode": "auto"}), _SCHEMA)


@pytest.mark.parametrize("field", ["adapter", "scope", "agents"])
def test_managed_mode_missing_required_field_is_rejected(field: str) -> None:
    policy = {"mode": "managed", "adapter": "skillsmd", "scope": "project", "agents": ["codex"]}
    del policy[field]
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_policy(policy), _SCHEMA)


def test_unknown_policy_property_is_rejected() -> None:
    policy = {"mode": "prompt", "installer": "skillsmd"}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_policy(policy), _SCHEMA)


def test_invalid_scope_is_rejected() -> None:
    policy = {"mode": "managed", "adapter": "skillsmd", "scope": "user", "agents": ["codex"]}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_policy(policy), _SCHEMA)


def test_empty_agents_list_is_rejected() -> None:
    policy = {"mode": "managed", "adapter": "skillsmd", "scope": "project", "agents": []}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_policy(policy), _SCHEMA)


def test_duplicate_agents_are_rejected() -> None:
    policy = {
        "mode": "managed",
        "adapter": "skillsmd",
        "scope": "project",
        "agents": ["codex", "codex"],
    }
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_policy(policy), _SCHEMA)


@pytest.mark.parametrize("adapter", ["", " ", "skills\nmd", "skills\x00md"])
def test_blank_or_control_adapter_is_rejected(adapter: str) -> None:
    policy = {"mode": "managed", "adapter": adapter, "scope": "project", "agents": ["codex"]}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_policy(policy), _SCHEMA)


@pytest.mark.parametrize("agent", ["", " ", "co\ndex"])
def test_blank_or_control_agent_is_rejected(agent: str) -> None:
    policy = {"mode": "managed", "adapter": "skillsmd", "scope": "project", "agents": [agent]}
    with pytest.raises(schema_validator.SchemaValidationError):
        schema_validator.validate(_with_policy(policy), _SCHEMA)


def test_parser_round_trips_managed_policy() -> None:
    data = _with_policy(
        {
            "mode": "managed",
            "adapter": "skillsmd",
            "scope": "project",
            "agents": ["codex", "claude"],
        }
    )
    import json

    manifest = ConsumerManifest.from_json(json.dumps(data).encode("utf-8"))
    assert manifest.skill_installation == SkillInstallationPolicy(
        mode="managed", adapter="skillsmd", scope="project", agents=("codex", "claude")
    )
    reparsed = ConsumerManifest.from_json(manifest.to_json_bytes())
    assert reparsed.skill_installation == manifest.skill_installation


def test_parser_leaves_absent_policy_as_none() -> None:
    import json

    manifest = ConsumerManifest.from_json(json.dumps(_valid()).encode("utf-8"))
    assert manifest.skill_installation is None
    assert b"skill_installation" not in manifest.to_json_bytes()
