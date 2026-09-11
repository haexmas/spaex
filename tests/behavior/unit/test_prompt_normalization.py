"""Canonical prompt normalization tests."""

from spaex.behavior.composer.prompt import effective_prompt_sha256, load_effective_prompt


def test_effective_prompt_normalizes_to_one_trailing_lf(tmp_path):
    override = tmp_path / ".spaex" / "composer-prompt.md"
    override.parent.mkdir()
    override.write_text("prompt\r\n\r\n", encoding="utf-8", newline="")

    prompt = load_effective_prompt(tmp_path)

    assert prompt == "prompt\n"
    assert effective_prompt_sha256(prompt) == effective_prompt_sha256("prompt\n\n")
