"""Unit tests for app.core.prompt_manager.load_prompt.

load_prompt resolves a name like 'analysis' to app/prompts/analysis.prompt.md,
parses the YAML frontmatter, and substitutes {{var}} placeholders.

The function hardcodes its base path to app/prompts/ relative to its own
__file__, so these tests assert against the real prompt files that ship in
the repo rather than against tmp_path fixtures.
"""

from __future__ import annotations

import pytest

from app.core.prompt_manager import load_prompt


def test_load_existing_prompt_returns_config_and_body():
    """analysis.prompt.md ships with the repo; loading it should always work."""
    config, body = load_prompt("analysis")
    assert isinstance(config, dict)
    assert isinstance(body, str)
    # Frontmatter for analysis.prompt.md declares provider/model/temperature
    assert config.get("provider") == "deepseek"
    assert "model" in config
    assert "temperature" in config


def test_load_missing_prompt_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_prompt("this_prompt_definitely_does_not_exist")


def test_template_variables_are_substituted():
    """{{ticker}} appears in analysis.prompt.md — passing ticker= should replace
    every occurrence."""
    _, body = load_prompt("analysis", ticker="QDEL")
    assert "{{ticker}}" not in body
    assert "QDEL" in body


def test_missing_kwargs_leave_placeholders_intact():
    """If a caller forgets to pass a variable, the placeholder stays in the
    output rather than being silently emptied. (This matches the current
    behavior — useful for debugging unfilled slots.)"""
    _, body = load_prompt("analysis")
    # No ticker kwarg → the literal placeholder should still be present
    assert "{{ticker}}" in body


def test_multiple_kwargs_all_substituted():
    _, body = load_prompt(
        "analysis",
        ticker="TEST",
        narrative_sources="<narrative sources list>",
    )
    assert "TEST" in body
    assert "<narrative sources list>" in body
    # No placeholder left for the variables we passed
    for placeholder in ("{{ticker}}", "{{narrative_sources}}"):
        assert placeholder not in body


def test_extra_unused_kwargs_are_harmless():
    """Passing a kwarg that the prompt doesn't reference should not raise."""
    config, body = load_prompt("analysis", ticker="X", nonexistent_var="ignored")
    assert "X" in body
    # The unused kwarg simply has no placeholder to replace; no error.


def test_classify_prompt_has_deepseek_v4_flash_for_json_mode():
    """classify.prompt.md targets the cheaper Flash model with JSON-mode."""
    config, _ = load_prompt("classify")
    assert config.get("provider") == "deepseek"
    assert "flash" in (config.get("model") or "").lower()
