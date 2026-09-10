import pytest

from app.services.advisor.llm import BriefResult, MockAdvisorLLM

_SYSTEM = [{"type": "text", "text": "base"}]


async def test_mock_returns_brief_result_with_four_sections() -> None:
    result = await MockAdvisorLLM().generate_brief(system=_SYSTEM, context="{}")
    assert isinstance(result, BriefResult)
    for heading in ("## Synthèse", "## Actions prioritaires", "## Sous surveillance",
                    "## Données manquantes"):
        assert heading in result.text
    assert set(result.usage) == {"input", "output", "cache_read", "cache_creation"}
    assert all(v == 0 for v in result.usage.values())


async def test_mock_honours_injected_text() -> None:
    result = await MockAdvisorLLM(text="brief maison").generate_brief(system=_SYSTEM, context="{}")
    assert result.text == "brief maison"


async def test_mock_can_be_configured_to_raise() -> None:
    with pytest.raises(RuntimeError):
        await MockAdvisorLLM(raises=RuntimeError("boom")).generate_brief(
            system=_SYSTEM, context="{}"
        )
