"""Jetons GA4 / Search Console d'un site, à partir de ses liaisons Google.

Réutilise `build_reader` du plan de mesure (même logique que l'audit : une connexion
révoquée passe à `needs_reauth`, que l'appelant committe). Les jetons restent en
mémoire et sont exclus du `repr` (jamais dans un log).

`build_reader` renvoie `None` pour un jeton, que la connexion soit à reconnecter ou que le
rafraîchissement ait échoué temporairement (réseau, 5xx). Ici on relit l'état de la
connexion pour les distinguer : `token_unavailable` (connexion à reconnecter, définitif)
ou `token_refresh_failed` (connexion encore active, une nouvelle tentative a du sens)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus, ResourceType
from app.models.google_connection import GoogleConnection
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import TokenCipher
from app.services.google_oauth import GoogleOAuthClient
from app.services.measurement.google_access import build_reader

TOKEN_UNAVAILABLE = "token_unavailable"
TOKEN_REFRESH_FAILED = "token_refresh_failed"


@dataclass(frozen=True, slots=True)
class GoogleCredentials:
    ga4_property: str | None
    ga4_token: str | None = field(repr=False)
    gsc_site: str | None
    gsc_token: str | None = field(repr=False)
    # Raison de l'absence de jeton pour une source reliée (None si jeton présent ou source
    # non reliée) : `token_unavailable` (définitif) ou `token_refresh_failed` (récupérable).
    ga4_problem: str | None = None
    gsc_problem: str | None = None


def _problem(
    resource_id: str | None,
    token: str | None,
    statuses: dict[tuple[ResourceType, str], ConnectionStatus],
    kind: ResourceType,
) -> str | None:
    if resource_id is None or token is not None:
        return None
    if statuses.get((kind, resource_id)) == ConnectionStatus.ACTIVE:
        return TOKEN_REFRESH_FAILED
    return TOKEN_UNAVAILABLE


async def resolve_google_credentials(
    session: AsyncSession,
    website: Website,
    *,
    oauth: GoogleOAuthClient,
    cipher: TokenCipher,
) -> GoogleCredentials:
    reader = await build_reader(session, website, oauth=oauth, cipher=cipher)
    # Relecture après `build_reader` : l'éventuel passage à `needs_reauth` y est déjà visible.
    rows = await session.execute(
        select(WebsiteGoogleLink.resource_type, WebsiteGoogleLink.resource_id, GoogleConnection.status)
        .join(GoogleConnection, WebsiteGoogleLink.google_connection_id == GoogleConnection.id)
        .where(
            WebsiteGoogleLink.website_id == website.id,
            WebsiteGoogleLink.resource_type.in_((ResourceType.GA4_PROPERTY, ResourceType.GSC_SITE)),
        )
    )
    statuses = {(kind, resource_id): status for kind, resource_id, status in rows.all()}
    return GoogleCredentials(
        ga4_property=reader.ga4_property,
        ga4_token=reader.ga4_token,
        gsc_site=reader.gsc_site,
        gsc_token=reader.gsc_token,
        ga4_problem=_problem(
            reader.ga4_property, reader.ga4_token, statuses, ResourceType.GA4_PROPERTY
        ),
        gsc_problem=_problem(reader.gsc_site, reader.gsc_token, statuses, ResourceType.GSC_SITE),
    )
