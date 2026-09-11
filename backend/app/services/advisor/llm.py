"""Abstraction de l'appel LLM du conseiller : ABC + Mock + Real (Anthropic).

Le brief est un appel bloquant : on streame en interne (`messages.stream` +
`get_final_message`, pas de timeout HTTP) mais on renvoie le texte complet.
`RealAdvisorLLM` n'est pas couvert par la CI (suite en `MockAdvisorLLM`).
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass

import anthropic

_MOCK_BRIEF = """\
## Synthèse
Le site est globalement sain ; le point le plus urgent est l'événement `purchase`
GA4 qui ne transmet ni `value` ni `currency`, ce qui vide les revenus analytics.

## Actions prioritaires
1. **Quoi** : corriger les paramètres de l'événement `purchase`.
   **Pourquoi** : 0 € de revenu remonté sur toutes les ventes.
   **Comment démarrer** : ajouter `value` et `currency` au `dataLayer.push` de la
   page de confirmation.
   **Effort** : rapide.

## Sous surveillance
- L'INP terrain proche du seuil (200 ms).

## Données manquantes
- Search Console non connectée : le diagnostic SEO tourne en aveugle.
"""

_ZERO_USAGE = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}


@dataclass(frozen=True, slots=True)
class BriefResult:
    text: str
    usage: dict


@dataclass(frozen=True, slots=True)
class TurnDelta:
    """Fragment de texte streame pendant un tour de conversation."""

    text: str


@dataclass(frozen=True, slots=True)
class TurnResult:
    """Tour complet : content blocks bruts (pour replay API) + metadonnees."""

    content: list[dict]
    stop_reason: str
    usage: dict


_MOCK_REPLY = "Je n'ai pas assez d'informations pour repondre precisement."


class AdvisorLLM(abc.ABC):
    @abc.abstractmethod
    async def generate_brief(
        self, *, system: list[dict], context: str, max_tokens: int = 8000
    ) -> BriefResult: ...

    @abc.abstractmethod
    def stream_turn(
        self, *, system: list[dict], messages: list[dict], tools: list[dict], max_tokens: int = 4000
    ) -> AsyncIterator[TurnDelta | TurnResult]: ...


class MockAdvisorLLM(AdvisorLLM):
    def __init__(
        self,
        *,
        text: str | None = None,
        raises: Exception | None = None,
        turns: list[TurnResult] | None = None,
    ) -> None:
        self._text = text if text is not None else _MOCK_BRIEF
        self._raises = raises
        self._turns = list(turns) if turns is not None else None

    async def generate_brief(
        self, *, system: list[dict], context: str, max_tokens: int = 8000
    ) -> BriefResult:
        _ = (system, context, max_tokens)
        if self._raises is not None:
            raise self._raises
        return BriefResult(text=self._text, usage=dict(_ZERO_USAGE))

    async def stream_turn(
        self, *, system: list[dict], messages: list[dict], tools: list[dict], max_tokens: int = 4000
    ) -> AsyncIterator[TurnDelta | TurnResult]:
        _ = (system, messages, tools, max_tokens)
        if self._raises is not None:
            raise self._raises
        if self._turns:
            result = self._turns.pop(0)
        else:
            result = TurnResult(
                content=[{"type": "text", "text": _MOCK_REPLY}],
                stop_reason="end_turn",
                usage=dict(_ZERO_USAGE),
            )
        text = "".join(block.get("text", "") for block in result.content if block.get("type") == "text")
        if text:
            yield TurnDelta(text=text)
        yield result


class RealAdvisorLLM(AdvisorLLM):
    def __init__(self, *, api_key: str, brief_model: str, chat_model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._brief_model = brief_model
        self._chat_model = chat_model

    async def generate_brief(
        self, *, system: list[dict], context: str, max_tokens: int = 8000
    ) -> BriefResult:
        async with self._client.messages.stream(
            model=self._brief_model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": context + "\n\nGénère le plan d'action priorisé.",
                }
            ],
        ) as stream:
            message = await stream.get_final_message()

        text = "".join(block.text for block in message.content if block.type == "text")
        usage = message.usage
        return BriefResult(
            text=text,
            usage={
                "input": usage.input_tokens,
                "output": usage.output_tokens,
                "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                "cache_creation": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            },
        )

    async def stream_turn(
        self, *, system: list[dict], messages: list[dict], tools: list[dict], max_tokens: int = 4000
    ) -> AsyncIterator[TurnDelta | TurnResult]:
        async with self._client.messages.stream(
            model=self._chat_model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            async for text in stream.text_stream:
                yield TurnDelta(text=text)
            message = await stream.get_final_message()

        content = [block.model_dump(mode="json") for block in message.content]
        usage = message.usage
        yield TurnResult(
            content=content,
            stop_reason=message.stop_reason or "end_turn",
            usage={
                "input": usage.input_tokens,
                "output": usage.output_tokens,
                "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                "cache_creation": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            },
        )
