"""Jetons GA4 / Search Console d'un site, à partir de ses liaisons Google.

Réutilise `build_reader` du plan de mesure (même logique que l'audit : une connexion
révoquée passe à `needs_reauth`, que l'appelant committe). Les jetons restent en
mémoire et sont exclus du `repr` (jamais dans un log)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website import Website
from app.security.token_crypto import TokenCipher
from app.services.google_oauth import GoogleOAuthClient
from app.services.measurement.google_access import build_reader


@dataclass(frozen=True, slots=True)
class GoogleCredentials:
    ga4_property: str | None
    ga4_token: str | None = field(repr=False)
    gsc_site: str | None
    gsc_token: str | None = field(repr=False)


async def resolve_google_credentials(
    session: AsyncSession,
    website: Website,
    *,
    oauth: GoogleOAuthClient,
    cipher: TokenCipher,
) -> GoogleCredentials:
    reader = await build_reader(session, website, oauth=oauth, cipher=cipher)
    return GoogleCredentials(
        ga4_property=reader.ga4_property,
        ga4_token=reader.ga4_token,
        gsc_site=reader.gsc_site,
        gsc_token=reader.gsc_token,
    )
