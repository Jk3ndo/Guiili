"""Abstraction de l'appel LLM du conseiller : ABC + Mock + Real (Anthropic).

Le brief est un appel bloquant : on streame en interne (`messages.stream` +
`get_final_message`, pas de timeout HTTP) mais on renvoie le texte complet.
`RealAdvisorLLM` n'est pas couvert par la CI (suite en `MockAdvisorLLM`).
"""

from __future__ import annotations

import abc
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


class AdvisorLLM(abc.ABC):
    @abc.abstractmethod
    async def generate_brief(
        self, *, system: list[dict], context: str, max_tokens: int = 8000
    ) -> BriefResult: ...


class MockAdvisorLLM(AdvisorLLM):
    def __init__(self, *, text: str | None = None, raises: Exception | None = None) -> None:
        self._text = text if text is not None else _MOCK_BRIEF
        self._raises = raises

    async def generate_brief(
        self, *, system: list[dict], context: str, max_tokens: int = 8000
    ) -> BriefResult:
        _ = (system, context, max_tokens)
        if self._raises is not None:
            raise self._raises
        return BriefResult(text=self._text, usage=dict(_ZERO_USAGE))


class RealAdvisorLLM(AdvisorLLM):
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate_brief(
        self, *, system: list[dict], context: str, max_tokens: int = 8000
    ) -> BriefResult:
        async with self._client.messages.stream(
            model=self._model,
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
