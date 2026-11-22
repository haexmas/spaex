"""The check: payload, answer parsing and passage verification (Spec 030 T007)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spaex.behavior.composer.check import CheckInput, parse_check_result, run_check
from spaex.behavior.composer.invoke import InvokeOptions
from spaex.behavior.composer.prompt import (
    CHECK_PROMPT,
    CHECK_PROMPT_VERSION,
    effective_prompt_sha256,
    load_effective_check_prompt,
)
from spaex.util.errors import HaexError

from ._fragments import make_fragment

FRAGMENTS = (
    make_fragment("m", "a", "intro\nalways use tabs\n```sh\nrun\n```\n"),
    make_fragment("m", "b", "never use tabs\nother\n"),
    make_fragment("n", "c", "third\n"),
)


def _answer(payload: dict[str, object]) -> str:
    return f"<<<SPAEX-COMPOSER-BEGIN>>>\n{json.dumps(payload)}\n<<<SPAEX-COMPOSER-END>>>\n"


def _finding(*passages: tuple[str, int, int], kind: str = "contradiction") -> dict[str, object]:
    return {
        "kind": kind,
        "summary": "they disagree",
        "passages": [{"fragment": f, "start": s, "end": e} for f, s, e in passages],
    }


def test_payload_numbers_the_lines_and_sorts_fragments() -> None:
    payload = json.loads(CheckInput(fragments=tuple(reversed(FRAGMENTS))).to_json())
    assert payload["check_prompt_version"] == CHECK_PROMPT_VERSION
    assert [f["id"] for f in payload["fragments"]] == ["m/a", "m/b", "n/c"]
    assert payload["fragments"][1]["body"] == "1: never use tabs\n2: other"
    assert all("lines" not in fragment for fragment in payload["fragments"])


def test_no_findings() -> None:
    assert parse_check_result(_answer({"type": "no_findings"}), FRAGMENTS) == ()


def test_findings_are_verified_and_carry_the_passage_text() -> None:
    raw = _answer(
        {"type": "findings", "findings": [_finding(("m/a", 2, 2), ("m/b", 1, 1))]}
    )
    (finding,) = parse_check_result(raw, FRAGMENTS)
    assert finding.kind == "contradiction"
    assert [(p.scoped_id, p.text) for p in finding.passages] == [
        ("m/a", "always use tabs"),
        ("m/b", "never use tabs"),
    ]
    assert finding.key == parse_check_result(raw, FRAGMENTS)[0].key


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "other"},
        {"type": "findings", "findings": []},
        {"type": "findings", "findings": [_finding(("m/a", 2, 2))]},  # one passage
        {"type": "findings", "findings": [_finding(("m/a", 2, 2), ("m/a", 1, 1))]},  # same fragment
        {"type": "findings", "findings": [_finding(("m/a", 2, 2), ("x/y", 1, 1))]},  # unknown
        {"type": "findings", "findings": [_finding(("m/a", 2, 2), ("m/b", 1, 9))]},  # out of range
        {"type": "findings", "findings": [_finding(("m/a", 3, 3), ("m/b", 1, 1))]},  # cuts fence
        {"type": "findings", "findings": [_finding(("m/a", 2, 2), ("m/b", 1, 1), kind="style")]},
        {
            "type": "findings",
            "findings": [{**_finding(("m/a", 2, 2), ("m/b", 1, 1)), "summary": " "}],
        },
    ],
)
def test_unusable_answers_are_invalid_output(bad: dict[str, object]) -> None:
    with pytest.raises(HaexError) as caught:
        parse_check_result(_answer(bad), FRAGMENTS)
    assert caught.value.exit_code == 32


def test_missing_sentinel_is_invalid_output() -> None:
    with pytest.raises(HaexError) as caught:
        parse_check_result("no envelope here", FRAGMENTS)
    assert caught.value.exit_code == 32


def test_run_check_calls_the_stub_with_the_check_prompt_and_logs(tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def stub(_runtime: str, prompt: str, payload: str, _timeout: float) -> str:
        seen["prompt"], seen["payload"] = prompt, payload
        return _answer({"type": "no_findings"})

    log = tmp_path / "composer.log"
    options = InvokeOptions(stub_caller=stub, composer_log_path=log)
    assert run_check(CheckInput(fragments=FRAGMENTS), repo_root=tmp_path, options=options) == ()
    assert seen["prompt"] == load_effective_check_prompt(tmp_path)
    assert json.loads(seen["payload"])["fragments"][0]["id"] == "m/a"
    entry = json.loads(log.read_text().splitlines()[-1])
    assert (entry["step"], entry["outcome"]) == ("check", "no_findings")


def test_run_check_logs_an_unusable_answer(tmp_path: Path) -> None:
    log = tmp_path / "composer.log"
    options = InvokeOptions(stub_caller=lambda *_: "garbage", composer_log_path=log)
    with pytest.raises(HaexError):
        run_check(CheckInput(fragments=FRAGMENTS), repo_root=tmp_path, options=options)
    assert json.loads(log.read_text().splitlines()[-1])["outcome"] == "invalid-output"


def test_check_prompt_override_and_hash(tmp_path: Path) -> None:
    assert load_effective_check_prompt(tmp_path).strip() == CHECK_PROMPT.strip()
    override = tmp_path / ".spaex" / "check-prompt.md"
    override.parent.mkdir()
    override.write_bytes(b"custom\r\nprompt\r\n")
    assert load_effective_check_prompt(tmp_path) == "custom\nprompt\n"
    assert effective_prompt_sha256("custom\r\nprompt") == effective_prompt_sha256(
        "custom\nprompt\n"
    )
