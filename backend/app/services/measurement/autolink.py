# backend/app/services/measurement/autolink.py
"""Auto-liaison : relie sans saisie la propriété GA4 et le site Search Console qui
correspondent au domaine d'un site. Ne lie que si le choix est unique et n'écrase
jamais une liaison existante (c'est le choix de l'utilisateur)."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus, ResourceType
from app.models.google_connection import GoogleConnection
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import TokenCipher
from app.services.google_oauth import GoogleOAuthClient, GoogleOAuthError
from app.services.measurement.google_access import access_token_for
from app.services.measurement.google_reader import GoogleReadError, web_stream_hosts
from app.services.measurement.service import lock_site

StreamHostsFetcher = Callable[[str, str], Awaitable[set[str]]]
MAX_PROPERTIES = 20


@dataclass(frozen=True, slots=True)
class LinkOutcome:
    # linked | already_linked | ambiguous | none | skipped
    status: str
    resource_id: str | None = None
    display_name: str | None = None
    connection_id: Any | None = None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AutolinkResult:
    ga4: LinkOutcome
    gsc: LinkOutcome


def _raw_host(value: str) -> str:
    text = value.strip().lower().removeprefix("sc-domain:")
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = re.split(r"[/?#]", text, maxsplit=1)[0]
    return text.split(":", 1)[0]


def normalize_host(value: str) -> str:
    return _raw_host(value).removeprefix("www.")


def _gsc_kind(resource_id: str) -> int:
    if resource_id.startswith("sc-domain:"):
        return 0
    if resource_id.startswith("https://"):
        return 1
    if resource_id.startswith("http://"):
        return 2
    return 3


def pick_gsc_site(domain: str, sites: Sequence[tuple[Any, str]]) -> LinkOutcome:
    """`sites` : couples `(id de connexion, identifiant du site Search Console)`."""
    wanted = normalize_host(domain)
    matches: dict[str, Any] = {}
    for connection_id, resource_id in sites:
        if normalize_host(resource_id) == wanted:
            matches.setdefault(resource_id, connection_id)
    if not matches:
        return LinkOutcome("none")
    best = min(_gsc_kind(resource_id) for resource_id in matches)
    top = [resource_id for resource_id in matches if _gsc_kind(resource_id) == best]
    if len(top) > 1:
        exact = [r for r in top if _raw_host(r) == _raw_host(domain)]
        if len(exact) == 1:
            top = exact
    if len(top) == 1:
        return LinkOutcome("linked", resource_id=top[0], connection_id=matches[top[0]])
    return LinkOutcome("ambiguous", candidates=tuple(sorted(top)))


def pick_ga4_property(
    domain: str, candidates: Sequence[tuple[Any, str, str | None, set[str]]]
) -> LinkOutcome:
    """`candidates` : `(id de connexion, propriété, nom, hôtes des flux web)`."""
    wanted = normalize_host(domain)
    hits: dict[str, tuple[Any, str | None]] = {}
    for connection_id, resource_id, name, hosts in candidates:
        if wanted in {normalize_host(host) for host in hosts}:
            hits.setdefault(resource_id, (connection_id, name))
    if not hits:
        return LinkOutcome("none")
    if len(hits) == 1:
        resource_id, (connection_id, name) = next(iter(hits.items()))
        return LinkOutcome(
            "linked", resource_id=resource_id, display_name=name, connection_id=connection_id
        )
    return LinkOutcome("ambiguous", candidates=tuple(sorted(hits)))


def _add_link(
    session: AsyncSession, website_id: UUID, resource_type: ResourceType, outcome: LinkOutcome
) -> None:
    session.add(
        WebsiteGoogleLink(
            website_id=website_id,
            google_connection_id=outcome.connection_id,
            resource_type=resource_type,
            resource_id=outcome.resource_id,
            resource_display_name=outcome.display_name,
        )
    )


async def _existing_links(
    session: AsyncSession, website_id: UUID
) -> dict[ResourceType, WebsiteGoogleLink]:
    # Sans order_by : comme `build_reader`, la dernière liaison lue d'un type l'emporte.
    return {
        row.resource_type: row
        for row in (
            await session.execute(
                select(WebsiteGoogleLink).where(WebsiteGoogleLink.website_id == website_id)
            )
        ).scalars()
    }


def _already(link: WebsiteGoogleLink) -> LinkOutcome:
    return LinkOutcome("already_linked", resource_id=link.resource_id)


async def autolink_website(
    session: AsyncSession,
    website: Website,
    *,
    oauth: GoogleOAuthClient,
    cipher: TokenCipher,
    stream_hosts: StreamHostsFetcher = web_stream_hosts,
    max_properties: int = MAX_PROPERTIES,
) -> AutolinkResult:
    """Lie GA4 et Search Console au site quand la correspondance est unique. Ne commit pas."""
    links = await _existing_links(session, website.id)
    ga4_link = links.get(ResourceType.GA4_PROPERTY)
    gsc_link = links.get(ResourceType.GSC_SITE)
    ga4 = _already(ga4_link) if ga4_link else None
    gsc = _already(gsc_link) if gsc_link else None
    if ga4 and gsc:
        return AutolinkResult(ga4, gsc)

    # Seules les connexions actives du workspace du site : jamais celles d'un autre client.
    connections = (
        (
            await session.execute(
                select(GoogleConnection)
                .where(
                    GoogleConnection.workspace_id == website.workspace_id,
                    GoogleConnection.status == ConnectionStatus.ACTIVE,
                )
                .order_by(GoogleConnection.id)
            )
        )
        .scalars()
        .all()
    )

    cache: dict[UUID, str | None] = {}
    gsc_sites: list[tuple[Any, str]] = []
    ga4_candidates: list[tuple[Any, str, str | None, set[str]]] = []
    usable = False
    inspected = 0
    for connection in connections:
        token = await access_token_for(connection, oauth, cipher, cache)
        if token is None:
            continue
        try:
            discovered = await oauth.discover_resources(access_token=token)
        except (GoogleOAuthError, httpx.HTTPError):
            continue
        usable = True
        if gsc is None:
            gsc_sites += [(connection.id, site.resource_id) for site in discovered.gsc_sites]
        if ga4 is None:
            for prop in discovered.ga4_properties:
                if inspected >= max_properties:
                    break
                inspected += 1
                try:
                    hosts = await stream_hosts(token, prop.resource_id)
                except GoogleReadError:
                    continue  # propriété illisible : ignorée, pas fatale
                ga4_candidates.append((connection.id, prop.resource_id, prop.display_name, hosts))

    # Verrou par site, pris après les appels Google (on ne le tient pas pendant le réseau),
    # puis relecture : une liaison posée entre-temps (autre onglet, choix manuel) prime.
    await lock_site(session, website.id)
    links = await _existing_links(session, website.id)
    ga4_link = links.get(ResourceType.GA4_PROPERTY)
    gsc_link = links.get(ResourceType.GSC_SITE)

    if ga4_link:
        ga4 = _already(ga4_link)
    elif ga4 is None:
        ga4 = pick_ga4_property(website.domain, ga4_candidates) if usable else LinkOutcome("skipped")
        if ga4.status == "linked":
            _add_link(session, website.id, ResourceType.GA4_PROPERTY, ga4)
    if gsc_link:
        gsc = _already(gsc_link)
    elif gsc is None:
        gsc = pick_gsc_site(website.domain, gsc_sites) if usable else LinkOutcome("skipped")
        if gsc.status == "linked":
            _add_link(session, website.id, ResourceType.GSC_SITE, gsc)
    await session.flush()
    return AutolinkResult(ga4, gsc)
