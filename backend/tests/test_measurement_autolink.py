import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import ConnectionStatus, ResourceType
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import (
    DiscoveredResources,
    Ga4Property,
    GoogleTokenResponse,
    GoogleUserInfo,
    GscSite,
)
from app.services.measurement.autolink import (
    autolink_website,
    normalize_host,
    pick_ga4_property,
    pick_gsc_site,
)
from tests.conftest import owner_workspace_id
from tests.measurement_fakes import FakeOAuth, fake_stream_hosts


@pytest.mark.parametrize(
    ("raw", "host"),
    [
        ("sc-domain:Exemple.fr", "exemple.fr"),
        ("https://www.exemple.fr/", "exemple.fr"),
        ("http://exemple.fr:8080/x?y=1", "exemple.fr"),
        ("WWW.Exemple.fr", "exemple.fr"),
        ("exemple.fr", "exemple.fr"),
    ],
)
def test_normalize_host(raw: str, host: str) -> None:
    assert normalize_host(raw) == host


def test_gsc_prefers_the_domain_property_over_url_prefixes() -> None:
    out = pick_gsc_site("exemple.fr", [("c1", "https://exemple.fr/"), ("c1", "sc-domain:exemple.fr")])
    assert out.status == "linked" and out.resource_id == "sc-domain:exemple.fr"
    assert out.connection_id == "c1"


def test_gsc_prefers_https_over_http() -> None:
    out = pick_gsc_site("exemple.fr", [("c1", "http://exemple.fr/"), ("c1", "https://exemple.fr/")])
    assert out.resource_id == "https://exemple.fr/"


def test_gsc_www_variants_are_settled_by_the_stored_domain() -> None:
    sites = [("c1", "https://exemple.fr/"), ("c1", "https://www.exemple.fr/")]
    assert pick_gsc_site("www.exemple.fr", sites).resource_id == "https://www.exemple.fr/"
    assert pick_gsc_site("exemple.fr", sites).resource_id == "https://exemple.fr/"


def test_gsc_is_ambiguous_when_nothing_settles_the_choice() -> None:
    sites = [("c1", "https://exemple.fr/"), ("c1", "https://exemple.fr:8443/")]
    out = pick_gsc_site("www.exemple.fr", sites)
    assert out.status == "ambiguous"
    assert set(out.candidates) == {"https://exemple.fr/", "https://exemple.fr:8443/"}
    assert out.resource_id is None


def test_gsc_duplicates_across_connections_are_not_ambiguous() -> None:
    out = pick_gsc_site("exemple.fr", [("c1", "sc-domain:exemple.fr"), ("c2", "sc-domain:exemple.fr")])
    assert out.status == "linked" and out.connection_id == "c1"


def test_gsc_none_when_no_site_matches() -> None:
    assert pick_gsc_site("exemple.fr", [("c1", "sc-domain:autre.fr")]).status == "none"
    assert pick_gsc_site("exemple.fr", []).status == "none"


def test_ga4_unique_match_ambiguous_and_none() -> None:
    one = [
        ("c1", "properties/1", "Exemple", {"exemple.fr"}),
        ("c1", "properties/2", "Autre", {"www.autre.fr"}),
    ]
    out = pick_ga4_property("exemple.fr", one)
    assert out.status == "linked" and out.resource_id == "properties/1"
    assert out.display_name == "Exemple"

    two = [
        ("c1", "properties/1", "A", {"exemple.fr"}),
        ("c1", "properties/3", "B", {"www.exemple.fr"}),
    ]
    ambiguous = pick_ga4_property("exemple.fr", two)
    assert ambiguous.status == "ambiguous"
    assert set(ambiguous.candidates) == {"properties/1", "properties/3"}

    assert pick_ga4_property("exemple.fr", [("c1", "properties/9", "Z", {"z.fr"})]).status == "none"


# ---- service ------------------------------------------------------------------------
_RESOURCES = DiscoveredResources(
    ga4_properties=(
        Ga4Property("properties/1", "Exemple", "accounts/1", "Compte"),
        Ga4Property("properties/2", "Autre", "accounts/1", "Compte"),
    ),
    gsc_sites=(
        GscSite("sc-domain:exemple.fr", "siteOwner"),
        GscSite("https://exemple.fr/", "siteOwner"),
    ),
)
_HOSTS = {"properties/1": {"exemple.fr"}, "properties/2": {"autre.fr"}}


async def _world(db_session: AsyncSession, make_user, sub: str, domain: str = "exemple.fr"):
    user = await make_user(sub=sub)
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    connection = await upsert_google_connection(
        db_session,
        workspace_id=workspace_id,
        userinfo=GoogleUserInfo(sub=f"g-{sub}", email=f"{sub}@gmail.com"),
        token=GoogleTokenResponse(
            access_token="a",
            expires_in=3600,
            scopes=("openid",),
            refresh_token=f"refresh-{sub}",
        ),
        cipher=load_token_cipher(get_settings()),
    )
    await db_session.flush()
    return site, connection


async def _links(db_session: AsyncSession, site: Website) -> dict[ResourceType, str]:
    rows = (
        await db_session.execute(
            select(WebsiteGoogleLink).where(WebsiteGoogleLink.website_id == site.id)
        )
    ).scalars().all()
    return {row.resource_type: row.resource_id for row in rows}


async def _run(db_session, site, oauth=None, hosts=None, **kwargs):
    return await autolink_website(
        db_session,
        site,
        oauth=oauth or FakeOAuth(_RESOURCES),
        cipher=load_token_cipher(get_settings()),
        stream_hosts=hosts or fake_stream_hosts(_HOSTS),
        **kwargs,
    )


async def test_links_the_unique_ga4_property_and_the_domain_search_console_site(
    db_session: AsyncSession, make_user
) -> None:
    site, connection = await _world(db_session, make_user, "al-ok")
    result = await _run(db_session, site)
    assert result.ga4.status == "linked" and result.ga4.resource_id == "properties/1"
    assert result.gsc.status == "linked" and result.gsc.resource_id == "sc-domain:exemple.fr"
    assert await _links(db_session, site) == {
        ResourceType.GA4_PROPERTY: "properties/1",
        ResourceType.GSC_SITE: "sc-domain:exemple.fr",
    }
    rows = (await db_session.execute(select(WebsiteGoogleLink))).scalars().all()
    assert {row.google_connection_id for row in rows} == {connection.id}
    assert {row.resource_display_name for row in rows} >= {"Exemple"}


async def test_second_run_is_idempotent(db_session: AsyncSession, make_user) -> None:
    site, _ = await _world(db_session, make_user, "al-idem")
    await _run(db_session, site)
    fetch = fake_stream_hosts(_HOSTS)
    oauth = FakeOAuth(_RESOURCES)
    again = await _run(db_session, site, oauth=oauth, hosts=fetch)
    assert again.ga4.status == "already_linked" and again.gsc.status == "already_linked"
    assert again.ga4.resource_id == "properties/1"
    assert oauth.discover_calls == 0 and fetch.calls == []  # rien à chercher
    assert len(await _links(db_session, site)) == 2


async def test_never_overrides_an_existing_link(db_session: AsyncSession, make_user) -> None:
    site, connection = await _world(db_session, make_user, "al-keep")
    db_session.add(
        WebsiteGoogleLink(
            website_id=site.id,
            google_connection_id=connection.id,
            resource_type=ResourceType.GA4_PROPERTY,
            resource_id="properties/999",
        )
    )
    await db_session.flush()
    result = await _run(db_session, site)
    assert result.ga4.status == "already_linked" and result.ga4.resource_id == "properties/999"
    assert result.gsc.status == "linked"
    assert (await _links(db_session, site))[ResourceType.GA4_PROPERTY] == "properties/999"


async def test_ambiguous_ga4_choice_is_left_to_the_user(
    db_session: AsyncSession, make_user
) -> None:
    site, _ = await _world(db_session, make_user, "al-amb")
    both = {"properties/1": {"exemple.fr"}, "properties/2": {"www.exemple.fr"}}
    result = await _run(db_session, site, hosts=fake_stream_hosts(both))
    assert result.ga4.status == "ambiguous"
    assert set(result.ga4.candidates) == {"properties/1", "properties/2"}
    assert result.gsc.status == "linked"  # l'autre ressource n'est pas bloquée
    assert ResourceType.GA4_PROPERTY not in await _links(db_session, site)


async def test_unreadable_property_is_skipped_not_fatal(
    db_session: AsyncSession, make_user
) -> None:
    site, _ = await _world(db_session, make_user, "al-fail")
    hosts = fake_stream_hosts(_HOSTS, failing=frozenset({"properties/2"}))
    result = await _run(db_session, site, hosts=hosts)
    assert result.ga4.status == "linked" and result.ga4.resource_id == "properties/1"


async def test_only_the_first_properties_are_inspected(
    db_session: AsyncSession, make_user
) -> None:
    site, _ = await _world(db_session, make_user, "al-cap")
    hosts = fake_stream_hosts(_HOSTS)
    await _run(db_session, site, hosts=hosts, max_properties=1)
    assert hosts.calls == ["properties/1"]


async def test_no_usable_connection_means_skipped(db_session: AsyncSession, make_user) -> None:
    site, connection = await _world(db_session, make_user, "al-none")
    connection.status = ConnectionStatus.NEEDS_REAUTH
    await db_session.flush()
    result = await _run(db_session, site)
    assert result.ga4.status == "skipped" and result.gsc.status == "skipped"
    assert await _links(db_session, site) == {}


async def test_nothing_matches_the_domain(db_session: AsyncSession, make_user) -> None:
    site, _ = await _world(db_session, make_user, "al-nomatch", domain="inconnu.fr")
    result = await _run(db_session, site)
    assert result.ga4.status == "none" and result.gsc.status == "none"


async def test_link_added_meanwhile_is_not_overridden(
    db_session: AsyncSession, make_user
) -> None:
    site, connection = await _world(db_session, make_user, "al-race")

    async def racing_hosts(token: str, property_id: str) -> set[str]:
        # Un choix manuel arrive pendant les appels Google.
        if not await _links(db_session, site):
            db_session.add(
                WebsiteGoogleLink(
                    website_id=site.id,
                    google_connection_id=connection.id,
                    resource_type=ResourceType.GA4_PROPERTY,
                    resource_id="properties/777",
                )
            )
            await db_session.flush()
        return set(_HOSTS.get(property_id, set()))

    result = await _run(db_session, site, hosts=racing_hosts)
    assert result.ga4.status == "already_linked" and result.ga4.resource_id == "properties/777"
    assert (await _links(db_session, site))[ResourceType.GA4_PROPERTY] == "properties/777"


async def test_connections_of_another_workspace_are_never_used(
    db_session: AsyncSession, make_user
) -> None:
    site, _ = await _world(db_session, make_user, "al-mine", domain="autre-domaine.fr")
    await _world(db_session, make_user, "al-theirs", domain="exemple.fr")  # autre workspace
    oauth = FakeOAuth(_RESOURCES)
    result = await _run(db_session, site, oauth=oauth)
    assert oauth.discover_calls == 1  # sa seule connexion
    assert result.ga4.status == "none" and result.gsc.status == "none"
