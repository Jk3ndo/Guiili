import pytest

from app.services.advisor.personas import (
    PERSONA_DEFAULT,
    PERSONA_PRESETS,
    build_system,
    validate_custom_prompt,
)


def test_presets_cover_the_four_documented_keys() -> None:
    assert {"consultant", "pedagogue", "growth", "technique"} <= set(PERSONA_PRESETS)
    assert PERSONA_DEFAULT in PERSONA_PRESETS


def test_build_system_keeps_base_and_appends_persona() -> None:
    blocks = build_system("technique", None)
    assert len(blocks) == 2
    assert "Synthèse" in blocks[0]["text"]  # squelette fige present
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}
    assert PERSONA_PRESETS["technique"] in blocks[1]["text"]


def test_custom_prompt_is_appended_not_replacing_base() -> None:
    blocks = build_system("custom", "Parle comme un pirate.")
    assert "Synthèse" in blocks[0]["text"]
    assert "pirate" in blocks[1]["text"]


def test_unknown_key_falls_back_to_default() -> None:
    assert PERSONA_PRESETS[PERSONA_DEFAULT] in build_system("bogus", None)[1]["text"]


def test_custom_key_without_prompt_falls_back_to_default() -> None:
    assert PERSONA_PRESETS[PERSONA_DEFAULT] in build_system("custom", None)[1]["text"]


def test_build_system_brief_mode_has_structure() -> None:
    blocks = build_system("consultant", None, mode="brief")
    assert "Synthèse" in blocks[0]["text"]
    assert "Actions prioritaires" in blocks[0]["text"]


def test_build_system_chat_mode_has_no_forced_structure() -> None:
    blocks = build_system("consultant", None, mode="chat")
    assert "Synthèse" not in blocks[0]["text"]
    assert "Actions prioritaires" not in blocks[0]["text"]


def test_build_system_chat_mode_keeps_safety_rules() -> None:
    blocks = build_system("consultant", None, mode="chat")
    assert "invente" in blocks[0]["text"].lower()


def test_build_system_default_mode_is_brief() -> None:
    assert build_system("consultant", None) == build_system("consultant", None, mode="brief")


def test_validate_custom_prompt() -> None:
    assert validate_custom_prompt("  hello  ") == "hello"
    with pytest.raises(ValueError):
        validate_custom_prompt("   ")
    with pytest.raises(ValueError):
        validate_custom_prompt("x" * 2001)
