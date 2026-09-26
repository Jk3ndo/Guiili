import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import ConnectionStatus, ResourceType
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import GoogleTokenResponse, GoogleUserInfo, InvalidGrantError
from app.services.google_oauth.mock import MockGoogleOAuthClient
from app.services.measurement.google_access import build_reader
from app.services.measurement.google_reader import (
    GoogleReadError,
    HttpGoogleReader,
    parse_event_stats,
    web_stream_hosts,
)
from tests.conftest import owner_workspace_id


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _reader(handler, **overrides) -> HttpGoogleReader:
    args = {
        "ga4_token": "tok-ga4",
        "ga4_property": "properties/123456",
        "gsc_token": "tok-gsc",
        "gsc_site": "sc-domain:exemple.fr",
        "gsc_state": "linked",
        "client": _client(handler),
    }
    args.update(overrides)
    return HttpGoogleReader(**args)


def test_parse_event_stats() -> None:
    payload = {
        "rows": [
            {
                "dimensionValues": [{"value": "purchase"}],
                "metricValues": [{"value": "12"}, {"value": "340.5"}, {"value": "0"}],
            },
            {
                "dimensionValues": [{"value": "page_view"}],
                "metricValues": [{"value": "900"}, {"value": "0"}, {"value": "0"}],
            },
            {"dimensionValues": [], "metricValues": []},
        ]
    }
    stats = parse_event_stats(payload)
    assert stats["purchase"] == {"count": 12.0, "revenue": 340.5, "value": 0.0}
    assert stats["page_view"]["count"] == 900.0
    assert parse_event_stats({}) == {}


async def test_event_stats_calls_run_report() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "dimensionValues": [{"value": "generate_lead"}],
                        "metricValues": [{"value": "4"}, {"value": "0"}, {"value": "0"}],
                    }
                ]
            },
        )

    stats = await _reader(handler).event_stats()
    assert stats["generate_lead"]["count"] == 4.0
    assert seen["url"].endswith("properties/123456:runReport")
    assert seen["auth"] == "Bearer tok-ga4"


async def test_key_events_ads_links_and_measurement_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/keyEvents"):
            return httpx.Response(
                200,
                json={
                    "keyEvents": [
                        {"eventName": "purchase", "defaultValue": {"numericValue": 0}},
                        {"eventName": "generate_lead", "defaultValue": {"numericValue": 50}},
                    ]
                },
            )
        if path.endswith("/googleAdsLinks"):
            return httpx.Response(200, json={"googleAdsLinks": [{"name": "x"}]})
        if path.endswith("/dataStreams"):
            return httpx.Response(
                200,
                json={
                    "dataStreams": [
                        {"type": "IOS_APP_DATA_STREAM"},
                        {
                            "type": "WEB_DATA_STREAM",
                            "webStreamData": {"measurementId": "G-ABC123XYZ"},
                        },
                    ]
                },
            )
        return httpx.Response(404)

    reader = _reader(handler)
    events = await reader.key_events()
    assert [e["eventName"] for e in events] == ["purchase", "generate_lead"]
    assert await reader.ads_links_count() == 1
    assert await reader.measurement_id() == "G-ABC123XYZ"


async def test_empty_admin_lists_are_valid_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    reader = _reader(handler)
    assert await reader.key_events() == []
    assert await reader.ads_links_count() == 0
    assert await reader.measurement_id() is None


async def test_sitemaps_count_quotes_the_site_url() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["raw"] = str(request.url)
        return httpx.Response(200, json={"sitemap": [{"path": "https://exemple.fr/sitemap.xml"}]})

    assert await _reader(handler).sitemaps_count() == 1
    assert "sc-domain%3Aexemple.fr/sitemaps" in seen["raw"]


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "token_unavailable"),
        (403, "permission_or_api_disabled"),
        (404, "not_found"),
        (429, "quota"),
        (500, "api_error"),
    ],
)
async def test_http_errors_map_to_reasons(status: int, reason: str) -> None:
    reader = _reader(lambda request: httpx.Response(status, json={}))
    with pytest.raises(GoogleReadError) as excinfo:
        await reader.event_stats()
    assert excinfo.value.reason == reason


async def test_network_error_maps_to_network_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(GoogleReadError) as excinfo:
        await _reader(handler).event_stats()
    assert excinfo.value.reason == "network"


async def test_missing_connections_raise_dedicated_reasons() -> None:
    reader = _reader(
        lambda request: httpx.Response(200, json={}),
        ga4_token=None,
        ga4_property=None,
        gsc_token=None,
        gsc_site=None,
        gsc_state="not_linked",
    )
    with pytest.raises(GoogleReadError) as ga4:
        await reader.event_stats()
    assert ga4.value.reason == "ga4_not_connected"
    with pytest.raises(GoogleReadError) as gsc:
        await reader.sitemaps_count()
    assert gsc.value.reason == "gsc_not_connected"

    expired = _reader(
        lambda request: httpx.Response(200, json={}), ga4_token=None, gsc_token=None
    )
    with pytest.raises(GoogleReadError) as stale:
        await expired.key_events()
    assert stale.value.reason == "token_unavailable"


async def test_web_stream_hosts_lists_only_web_streams() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/properties/123/dataStreams")
        return httpx.Response(
            200,
            json={
                "dataStreams": [
                    {"type": "IOS_APP_DATA_STREAM"},
                    {
                        "type": "WEB_DATA_STREAM",
                        "webStreamData": {"defaultUri": "https://www.Exemple.fr"},
                    },
                    {"type": "WEB_DATA_STREAM", "webStreamData": {"defaultUri": "exemple.org"}},
                ]
            },
        )

    hosts = await web_stream_hosts("tok", "properties/123", client=_client(handler))
    assert hosts == {"www.exemple.fr", "exemple.org"}


async def test_web_stream_hosts_maps_http_errors() -> None:
    with pytest.raises(GoogleReadError) as excinfo:
        await web_stream_hosts(
            "tok", "properties/1", client=_client(lambda request: httpx.Response(403, json={}))
        )
    assert excinfo.value.reason == "permission_or_api_disabled"


async def test_build_reader_resolves_links_and_tokens(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(sub="mgr-user")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain="mgr.test", display_name="MGR")
    db_session.add(site)
    await db_session.flush()

    cipher = load_token_cipher(get_settings())
    connection = await upsert_google_connection(
        db_session,
        workspace_id=workspace_id,
        userinfo=GoogleUserInfo(sub="google-sub-dev-agence", email="dev.agence@gmail.com"),
        token=GoogleTokenResponse(
            access_token="at",
            refresh_token="mock-refresh|google-sub-dev-agence",
            expires_in=3599,
            scopes=("openid", "email"),
        ),
        cipher=cipher,
    )
    db_session.add(
        WebsiteGoogleLink(
            website_id=site.id,
            google_connection_id=connection.id,
            resource_type=ResourceType.GA4_PROPERTY,
            resource_id="properties/447213908",
        )
    )
    db_session.add(
        WebsiteGoogleLink(
            website_id=site.id,
            google_connection_id=connection.id,
            resource_type=ResourceType.GSC_SITE,
            resource_id="sc-domain:mgr.test",
        )
    )
    await db_session.flush()

    reader = await build_reader(
        db_session, site, oauth=MockGoogleOAuthClient(), cipher=cipher
    )
    assert reader.gsc_state == "linked"
    assert reader.ga4_property == "properties/447213908"
    assert reader.ga4_token and reader.gsc_token


async def test_build_reader_without_links(db_session: AsyncSession, make_user) -> None:
    user = await make_user(sub="mgr-empty")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain="mgr-empty.test", display_name="E")
    db_session.add(site)
    await db_session.flush()

    reader = await build_reader(
        db_session,
        site,
        oauth=MockGoogleOAuthClient(),
        cipher=load_token_cipher(get_settings()),
    )
    assert reader.gsc_state == "not_linked"
    assert reader.ga4_property is None


# -- forme inattendue d'une réponse 200 : jamais un faux succès -------------------


def _json_body(body: str):
    return lambda request: httpx.Response(
        200, content=body, headers={"content-type": "application/json"}
    )


_READS = ["event_stats", "key_events", "ads_links_count", "measurement_id", "sitemaps_count"]


@pytest.mark.parametrize("body", ["[]", '"x"', "null", "12", "not json"])
@pytest.mark.parametrize("read", _READS)
async def test_unexpected_body_is_api_error(read: str, body: str) -> None:
    reader = _reader(_json_body(body))
    with pytest.raises(GoogleReadError) as excinfo:
        await getattr(reader, read)()
    assert excinfo.value.reason == "api_error"


@pytest.mark.parametrize(
    ("read", "key"),
    [
        ("event_stats", "rows"),
        ("key_events", "keyEvents"),
        ("ads_links_count", "googleAdsLinks"),
        ("measurement_id", "dataStreams"),
        ("sitemaps_count", "sitemap"),
    ],
)
@pytest.mark.parametrize("value", ["null", '"x"', "{}", "3"])
async def test_non_list_field_is_api_error(read: str, key: str, value: str) -> None:
    reader = _reader(_json_body(f'{{"{key}": {value}}}'))
    with pytest.raises(GoogleReadError) as excinfo:
        await getattr(reader, read)()
    assert excinfo.value.reason == "api_error"


def test_parse_event_stats_rejects_malformed_rows() -> None:
    for payload in (
        [],
        {"rows": None},
        {"rows": "x"},
        {"rows": ["x"]},
        {"rows": [{"dimensionValues": {"value": "purchase"}, "metricValues": []}]},
        {"rows": [{"dimensionValues": [{"value": "purchase"}], "metricValues": None}]},
    ):
        with pytest.raises(GoogleReadError) as excinfo:
            parse_event_stats(payload)
        assert excinfo.value.reason == "api_error"


async def test_web_stream_hosts_unexpected_shapes_are_api_error() -> None:
    bodies = (
        "[]",
        "null",
        '{"dataStreams": null}',
        '{"dataStreams": ["x"]}',
        '{"dataStreams": [{"type": "WEB_DATA_STREAM", "webStreamData": "x"}]}',
    )
    for body in bodies:
        with pytest.raises(GoogleReadError) as excinfo:
            await web_stream_hosts("tok", "properties/1", client=_client(_json_body(body)))
        assert excinfo.value.reason == "api_error"


# -- lecture seule : méthodes HTTP -------------------------------------------------


async def test_only_run_report_is_a_post_and_everything_else_is_get() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={})

    reader = _reader(handler)
    await reader.event_stats()
    await reader.key_events()
    await reader.ads_links_count()
    await reader.measurement_id()
    await reader.sitemaps_count()
    await web_stream_hosts("tok", "properties/1", client=_client(handler))

    methods = {path.rsplit("/", 1)[-1]: method for method, path in calls}
    assert methods["123456:runReport"] == "POST"
    for name in ("keyEvents", "googleAdsLinks", "dataStreams", "sitemaps"):
        assert methods[name] == "GET"
    assert [method for method, _ in calls].count("POST") == 1


# -- codes d'erreur sur les autres endpoints ---------------------------------------


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "token_unavailable"),
        (403, "permission_or_api_disabled"),
        (404, "not_found"),
        (429, "quota"),
        (503, "api_error"),
    ],
)
@pytest.mark.parametrize(
    "read", ["key_events", "ads_links_count", "measurement_id", "sitemaps_count"]
)
async def test_http_errors_map_to_reasons_on_admin_and_gsc(
    read: str, status: int, reason: str
) -> None:
    reader = _reader(lambda request: httpx.Response(status, json={}))
    with pytest.raises(GoogleReadError) as excinfo:
        await getattr(reader, read)()
    assert excinfo.value.reason == reason


# -- google_access : jetons indisponibles ------------------------------------------


class _FailingOAuth(MockGoogleOAuthClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def refresh_access_token(self, *, refresh_token: str):
        raise self._error


async def _site_with_links(db_session: AsyncSession, make_user, sub: str, *, status=None):
    user = await make_user(sub=sub)
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=f"{sub}.test", display_name=sub)
    db_session.add(site)
    await db_session.flush()
    cipher = load_token_cipher(get_settings())
    connection = await upsert_google_connection(
        db_session,
        workspace_id=workspace_id,
        userinfo=GoogleUserInfo(sub="google-sub-dev-agence", email="dev.agence@gmail.com"),
        token=GoogleTokenResponse(
            access_token="at",
            refresh_token="mock-refresh|google-sub-dev-agence",
            expires_in=3599,
            scopes=("openid", "email"),
        ),
        cipher=cipher,
    )
    if status is not None:
        connection.status = status
    for resource_type, resource_id in (
        (ResourceType.GA4_PROPERTY, "properties/1"),
        (ResourceType.GSC_SITE, f"sc-domain:{sub}.test"),
    ):
        db_session.add(
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=connection.id,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )
    await db_session.flush()
    return site, connection, cipher


async def test_build_reader_inactive_connection_needs_reauth(
    db_session: AsyncSession, make_user
) -> None:
    site, _, cipher = await _site_with_links(
        db_session, make_user, "mgr-revoked", status=ConnectionStatus.NEEDS_REAUTH
    )
    reader = await build_reader(db_session, site, oauth=MockGoogleOAuthClient(), cipher=cipher)
    assert reader.gsc_state == "needs_reauth"
    assert reader.ga4_token is None and reader.gsc_token is None
    with pytest.raises(GoogleReadError) as excinfo:
        await reader.event_stats()
    assert excinfo.value.reason == "token_unavailable"


async def test_build_reader_revoked_grant_flags_connection_for_reauth(
    db_session: AsyncSession, make_user
) -> None:
    site, connection, cipher = await _site_with_links(db_session, make_user, "mgr-grant")
    reader = await build_reader(
        db_session, site, oauth=_FailingOAuth(InvalidGrantError("revoked")), cipher=cipher
    )
    assert reader.gsc_state == "needs_reauth"
    assert reader.ga4_token is None
    assert connection.status == ConnectionStatus.NEEDS_REAUTH


@pytest.mark.parametrize("error", [httpx.ConnectError("boom"), httpx.ReadTimeout("slow")])
async def test_build_reader_network_failure_on_refresh_degrades(
    db_session: AsyncSession, make_user, error: Exception
) -> None:
    site, connection, cipher = await _site_with_links(db_session, make_user, "mgr-net")
    reader = await build_reader(db_session, site, oauth=_FailingOAuth(error), cipher=cipher)
    assert reader.gsc_state == "needs_reauth"
    assert reader.ga4_token is None and reader.gsc_token is None
    assert reader.ga4_property == "properties/1"
    assert connection.status == ConnectionStatus.ACTIVE
