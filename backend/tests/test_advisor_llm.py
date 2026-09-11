import pytest

from app.services.advisor.llm import BriefResult, MockAdvisorLLM, TurnDelta, TurnResult

_SYSTEM = [{"type": "text", "text": "base"}]


async def _collect(gen):
    return [chunk async for chunk in gen]


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


async def test_stream_turn_default_yields_delta_then_result() -> None:
    chunks = await _collect(MockAdvisorLLM().stream_turn(system=_SYSTEM, messages=[], tools=[]))
    assert isinstance(chunks[-1], TurnResult)
    assert chunks[-1].stop_reason == "end_turn"
    assert any(isinstance(c, TurnDelta) for c in chunks[:-1])


async def test_stream_turn_scripted_tool_use_then_final() -> None:
    turns = [
        TurnResult(
            content=[{"type": "tool_use", "id": "t1", "name": "get_gtm_check", "input": {}}],
            stop_reason="tool_use",
            usage={"input": 1, "output": 1, "cache_read": 0, "cache_creation": 0},
        ),
        TurnResult(
            content=[{"type": "text", "text": "Voila la reponse."}],
            stop_reason="end_turn",
            usage={"input": 1, "output": 1, "cache_read": 0, "cache_creation": 0},
        ),
    ]
    llm = MockAdvisorLLM(turns=turns)
    first = await _collect(llm.stream_turn(system=_SYSTEM, messages=[], tools=[]))
    assert first[-1].stop_reason == "tool_use"
    second = await _collect(llm.stream_turn(system=_SYSTEM, messages=[], tools=[]))
    assert second[-1].stop_reason == "end_turn"
    assert second[-1].content[0]["text"] == "Voila la reponse."
