# backend/app/services/measurement/autolink.py
"""Auto-liaison : relie sans saisie la propriété GA4 et le site Search Console qui
correspondent au domaine d'un site. Ne lie que si le choix est unique et n'écrase
jamais une liaison existante (c'est le choix de l'utilisateur)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit
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


LinkStatus = Literal["linked", "already_linked", "ambiguous", "none", "skipped", "incomplete"]

# Libellés français par (statut, raison) ; la raison précise « pourquoi » quand le statut
# seul ne suffit pas. Le code décide, l'interface ne fait qu'afficher ce texte.
MESSAGES: dict[tuple[str, str | None], str] = {
    ("linked", None): "Liaison faite automatiquement.",
    ("already_linked", None): "Déjà lié : ton choix est conservé.",
    ("ambiguous", None): "Plusieurs correspondances : choisis celle à lier.",
    ("ambiguous", "incomplete"): (
        "Vérification incomplète : rien n'a été lié. Réessaie, ou choisis à la main."
    ),
    ("none", None): "Aucune correspondance pour ce domaine dans le compte connecté.",
    ("none", "unverified"): (
        "Le site n'apparaît que comme propriété non validée dans Search Console : "
        "valide-le, ou lie-le à la main."
    ),
    ("none", "path_only"): (
        "Seul un préfixe de chemin (sous-dossier) existe dans Search Console : "
        "ce n'est pas le site entier, rien n'a été lié."
    ),
    ("skipped", None): "Aucune connexion Google utilisable : reconnecte ton compte.",
    ("incomplete", None): (
        "Vérification incomplète : réessaie, ou lie à la main."
    ),
}


def outcome_message(outcome: LinkOutcome) -> str:
    return MESSAGES.get((outcome.status, outcome.reason)) or MESSAGES.get(
        (outcome.status, None), ""
    )


@dataclass(frozen=True, slots=True)
class LinkOutcome:
    status: LinkStatus
    resource_id: str | None = None
    display_name: str | None = None
    connection_id: Any | None = None
    candidates: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AutolinkResult:
    ga4: LinkOutcome
    gsc: LinkOutcome


def _split(value: str):
    text = value.strip().lower().removeprefix("sc-domain:")
    try:
        return urlsplit(text if "//" in text else f"//{text}")
    except ValueError:
        return None


def _raw_host(value: str) -> str:
    parts = _split(value)
    return (parts.hostname or "") if parts else ""


def _is_whole_site(resource_id: str) -> bool:
    """Propriété couvrant tout le site : domaine, ou préfixe d'URL à la racine."""
    parts = _split(resource_id)
    return parts is not None and parts.path in ("", "/")


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
    """`sites` : couples `(id de connexion, identifiant du site Search Console)`, déjà
    limités aux propriétés validées. Seules les propriétés couvrant tout le site comptent."""
    wanted = normalize_host(domain)
    matches: dict[str, Any] = {}
    path_only = False
    for connection_id, resource_id in sites:
        if normalize_host(resource_id) != wanted:
            continue
        if _is_whole_site(resource_id):
            matches.setdefault(resource_id, connection_id)
        else:
            # Un préfixe `/blog/` n'est pas « le site » : lier des données partielles
            # serait un lien deviné.
            path_only = True
    if not matches:
        return LinkOutcome("none", reason="path_only" if path_only else None)
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


_VERIFIED_PERMISSIONS = frozenset({"siteOwner", "siteFullUser", "siteRestrictedUser"})


def _gsc_outcome(
    domain: str, verified: Sequence[tuple[Any, str]], unverified: Sequence[str]
) -> LinkOutcome:
    outcome = pick_gsc_site(domain, verified)
    if outcome.status == "none" and outcome.reason is None:
        wanted = normalize_host(domain)
        if any(normalize_host(resource_id) == wanted for resource_id in unverified):
            # Une propriété non validée ne prouve pas que le compte contrôle le site.
            return LinkOutcome("none", reason="unverified")
    return outcome


def _settle(outcome: LinkOutcome, complete: bool) -> LinkOutcome:
    """Jamais de lien sur une vue partielle : le choix « unique » n'est fiable que si tout
    a pu être lu. Sinon les correspondances trouvées deviennent des candidats à choisir."""
    if complete:
        return outcome
    if outcome.status == "linked" and outcome.resource_id is not None:
        return LinkOutcome(
            "ambiguous", candidates=(outcome.resource_id,), reason="incomplete"
        )
    if outcome.status == "ambiguous":
        return LinkOutcome("ambiguous", candidates=outcome.candidates, reason="incomplete")
    if outcome.status == "none":
        return LinkOutcome("incomplete")
    return outcome


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
    unverified: list[str] = []
    # Propriétés vues, dédupliquées par identifiant AVANT le plafond : la même propriété
    # vue par deux connexions ne compte qu'une fois. On garde le premier jeton qui la voit.
    seen: dict[str, tuple[Any, str, str | None]] = {}
    usable = False
    complete = True  # faux dès qu'une lecture a échoué ou que le plafond coupe la liste
    for connection in connections:
        token = await access_token_for(connection, oauth, cipher, cache)
        if token is None:
            complete = False
            continue
        try:
            discovered = await oauth.discover_resources(access_token=token)
        except (GoogleOAuthError, httpx.HTTPError):
            complete = False
            continue
        usable = True
        if gsc is None:
            for site in discovered.gsc_sites:
                if site.permission_level in _VERIFIED_PERMISSIONS:
                    gsc_sites.append((connection.id, site.resource_id))
                else:
                    unverified.append(site.resource_id)
        if ga4 is None:
            for prop in discovered.ga4_properties:
                seen.setdefault(prop.resource_id, (connection.id, token, prop.display_name))

    ga4_candidates: list[tuple[Any, str, str | None, set[str]]] = []
    ga4_complete = complete
    if ga4 is None:
        items = list(seen.items())
        if len(items) > max_properties:
            ga4_complete = False  # des propriétés n'ont pas été inspectées
        for resource_id, (connection_id, token, name) in items[:max_properties]:
            try:
                hosts = await stream_hosts(token, resource_id)
            except GoogleReadError:
                ga4_complete = False  # propriété illisible : ignorée, mais on le sait
                continue
            ga4_candidates.append((connection_id, resource_id, name, hosts))

    # Verrou par site, pris après les appels Google (on ne le tient pas pendant le réseau),
    # puis relecture : une liaison posée entre-temps (autre onglet, choix manuel) prime.
    await lock_site(session, website.id)
    links = await _existing_links(session, website.id)
    ga4_link = links.get(ResourceType.GA4_PROPERTY)
    gsc_link = links.get(ResourceType.GSC_SITE)

    if ga4_link:
        ga4 = _already(ga4_link)
    elif ga4 is None:
        ga4 = (
            _settle(pick_ga4_property(website.domain, ga4_candidates), ga4_complete)
            if usable
            else LinkOutcome("skipped")
        )
        if ga4.status == "linked":
            _add_link(session, website.id, ResourceType.GA4_PROPERTY, ga4)
    if gsc_link:
        gsc = _already(gsc_link)
    elif gsc is None:
        gsc = (
            _settle(_gsc_outcome(website.domain, gsc_sites, unverified), complete)
            if usable
            else LinkOutcome("skipped")
        )
        if gsc.status == "linked":
            _add_link(session, website.id, ResourceType.GSC_SITE, gsc)
    await session.flush()
    return AutolinkResult(ga4, gsc)
