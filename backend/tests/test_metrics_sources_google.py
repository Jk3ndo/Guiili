# backend/tests/test_metrics_sources_google.py
import json
from datetime import date

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import ConnectionStatus, ResourceType
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import (
    DiscoveredResources,
    GoogleOAuthError,
    GoogleTokenResponse,
    GoogleUserInfo,
    InvalidGrantError,
)
from app.services.metrics.sources import ga4 as ga4_module
from app.services.metrics.sources import gsc as gsc_module
from app.services.metrics.sources.credentials import resolve_google_credentials
from app.services.metrics.sources.ga4 import Ga4Source, parse_events, parse_totals
from app.services.metrics.sources.gsc import GscSource, parse_dimension
from app.services.metrics.sources.gsc import parse_totals as parse_gsc_totals
from app.services.metrics.types import DayRange, Observation, SourceError
from tests.conftest import owner_workspace_id
from tests.measurement_fakes import FakeOAuth

SITE = Website(domain="exemple.fr", display_name="Exemple")
WINDOW = DayRange(date(2026, 9, 20), date(2026, 9, 21))

_GA4_HEADERS = [
    {"name": n, "type": "TYPE_INTEGER"}
    for n in ("sessions", "screenPageViews", "engagedSessions", "keyEvents", "totalRevenue")
]


def _ga4_totals(*days: tuple[str, list[str]]) -> dict:
    return {
        "dimensionHeaders": [{"name": "date"}],
        "metricHeaders": _GA4_HEADERS,
        "rows": [
            {"dimensionValues": [{"value": day}], "metricValues": [{"value": v} for v in values]}
            for day, values in days
        ],
    }


def _ga4_events(*rows: tuple[str, str, str]) -> dict:
    return {
        "metricHeaders": [{"name": "eventCount", "type": "TYPE_INTEGER"}],
        "rows": [
            {
                "dimensionValues": [{"value": day}, {"value": name}],
                "metricValues": [{"value": count}],
            }
            for day, name, count in rows
        ],
    }


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_ga4_totals_are_read_by_header_name() -> None:
    observations = parse_totals(_ga4_totals(("20260920", ["12", "30", "8", "2", "99.5"])))
    values = {o.metric: o.value for o in observations}
    assert values == {
        "sessions": 12.0,
        "screen_page_views": 30.0,
        "engaged_sessions": 8.0,
        "key_events": 2.0,
        "total_revenue": 99.5,
    }
    assert {o.day for o in observations} == {date(2026, 9, 20)}


def test_ga4_empty_report_gives_no_observation_never_zero() -> None:
    assert parse_totals({"metricHeaders": _GA4_HEADERS}) == []


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"rows": "pas une liste", "metricHeaders": _GA4_HEADERS},
        {"rows": [{"dimensionValues": [{"value": "20260920"}]}], "metricHeaders": _GA4_HEADERS},
        _ga4_totals(("2026-09-20", ["1", "1", "1", "1", "1"])),
        _ga4_totals(("20260920", ["un", "1", "1", "1", "1"])),
        {"rows": _ga4_totals(("20260920", ["1"] * 5))["rows"], "metricHeaders": []},
    ],
)
def test_ga4_unexpected_shapes_are_recoverable_errors(payload) -> None:
    with pytest.raises(SourceError) as excinfo:
        parse_totals(payload)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


def test_ga4_events_are_cleaned_merged_and_capped() -> None:
    observations = parse_events(
        _ga4_events(
            ("20260920", "purchase", "3"),
            ("20260920", "page_view", "40"),
            ("20260920", "nom invalide !", "99"),
            ("20260920", "scroll", "40"),
        ),
        top_n=2,
    )
    assert [(o.dims["event_name"], o.value) for o in observations] == [
        ("page_view", 40.0),
        ("scroll", 40.0),
    ]


async def test_ga4_source_chunks_the_window_and_keeps_only_its_days() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["Authorization"] == "Bearer jeton"
        assert request.url.path == "/v1beta/properties/42:runReport"
        if len(body["dimensions"]) == 1:
            return httpx.Response(200, json=_ga4_totals(("20260920", ["5"] * 5), ("20260101", ["7"] * 5)))
        return httpx.Response(200, json=_ga4_events(("20260920", "purchase", "1")))

    source = Ga4Source(property_id="properties/42", token="jeton", client=_client(handler))
    window = DayRange(date(2026, 8, 1), date(2026, 9, 20))  # 51 jours -> 2 tranches
    observations = await source.collect(SITE, window)
    assert len(seen) == 4
    assert seen[0]["dateRanges"] == [{"startDate": "2026-08-01", "endDate": "2026-08-31"}]
    assert seen[2]["dateRanges"] == [{"startDate": "2026-09-01", "endDate": "2026-09-20"}]
    assert all(window.contains(o.day) for o in observations)
    assert any(o.metric == "event_count" for o in observations)


async def test_ga4_source_without_property_is_not_applicable() -> None:
    with pytest.raises(SourceError) as excinfo:
        await Ga4Source(property_id=None, token=None).collect(SITE, WINDOW)
    assert excinfo.value.reason == "ga4_not_connected" and excinfo.value.not_applicable


@pytest.mark.parametrize(
    ("status", "reason", "recoverable"),
    [
        (401, "token_unavailable", False),
        (403, "permission_or_api_disabled", False),
        (404, "not_found", False),
        (429, "quota", True),
        (503, "api_error", True),
    ],
)
async def test_ga4_http_errors_are_classified(status: int, reason: str, recoverable: bool) -> None:
    source = Ga4Source(
        property_id="properties/42",
        token="jeton",
        client=_client(lambda request: httpx.Response(status, json={"error": {}})),
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, WINDOW)
    assert (excinfo.value.reason, excinfo.value.recoverable) == (reason, recoverable)


async def test_ga4_network_error_is_recoverable_and_hides_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    source = Ga4Source(property_id="properties/42", token="jeton-secret", client=_client(handler))
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, WINDOW)
    assert excinfo.value.reason == "network" and excinfo.value.recoverable
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__
    assert "jeton-secret" not in repr(excinfo.value)


def _gsc(*rows: dict) -> dict:
    return {"rows": list(rows), "responseAggregationType": "byProperty"}


def test_gsc_dimension_rows_are_cleaned_merged_and_capped() -> None:
    payload = _gsc(
        {"keys": ["2026-09-20", "https://exemple.fr/a?utm=1"], "clicks": 2, "impressions": 10, "ctr": 0.2, "position": 3},
        {"keys": ["2026-09-20", "http://exemple.fr/a"], "clicks": 3, "impressions": 20, "ctr": 0.15, "position": 4},
        {"keys": ["2026-09-20", "https://exemple.fr/b"], "clicks": 1, "impressions": 90, "ctr": 0.01, "position": 9},
        {"keys": ["2026-09-20", "https://exemple.fr/c"], "clicks": 0, "impressions": 5, "ctr": 0, "position": 30},
    )
    observations = parse_dimension(payload, "page", top_n=2)
    assert observations == [
        Observation("clicks", date(2026, 9, 20), 5.0, {"page": "/a"}),
        Observation("impressions", date(2026, 9, 20), 30.0, {"page": "/a"}),
        Observation("clicks", date(2026, 9, 20), 1.0, {"page": "/b"}),
        Observation("impressions", date(2026, 9, 20), 90.0, {"page": "/b"}),
    ]


def test_gsc_personal_queries_are_dropped() -> None:
    payload = _gsc(
        {"keys": ["2026-09-20", "jean.dupont@gmail.com"], "clicks": 9, "impressions": 9, "ctr": 1, "position": 1},
        {"keys": ["2026-09-20", "chaise chêne"], "clicks": 1, "impressions": 4, "ctr": 0.25, "position": 2},
    )
    queries = {o.dims["query"] for o in parse_dimension(payload, "query", top_n=25)}
    assert queries == {"chaise chêne"}


async def test_gsc_source_reads_totals_pages_and_queries() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        assert "sc-domain%3Aexemple.fr" in str(request.url)
        if body["dimensions"] == ["date"]:
            return httpx.Response(
                200,
                json=_gsc({"keys": ["2026-09-20"], "clicks": 4, "impressions": 40, "ctr": 0.1, "position": 7.5}),
            )
        return httpx.Response(200, json=_gsc())

    source = GscSource(site_url="sc-domain:exemple.fr", token="jeton", client=_client(handler))
    observations = await source.collect(SITE, WINDOW)
    assert [b["dimensions"] for b in bodies] == [["date"], ["date", "page"], ["date", "query"]]
    assert all(b["dataState"] == "final" and b["rowLimit"] == 25000 for b in bodies)
    assert {o.metric: o.value for o in observations} == {
        "clicks": 4.0, "impressions": 40.0, "ctr": 0.1, "position": 7.5,
    }


async def test_gsc_unexpected_shape_is_recoverable() -> None:
    source = GscSource(
        site_url="sc-domain:exemple.fr",
        token="jeton",
        client=_client(lambda request: httpx.Response(200, json={"rows": [{"keys": "x"}]})),
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, WINDOW)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


async def test_gsc_without_site_is_not_applicable() -> None:
    with pytest.raises(SourceError) as excinfo:
        await GscSource(site_url=None, token=None).collect(SITE, WINDOW)
    assert excinfo.value.reason == "gsc_not_connected" and excinfo.value.not_applicable


async def test_credentials_come_from_the_site_links(db_session: AsyncSession, make_user) -> None:
    user = await make_user(sub="cred-owner")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain="cred.test", display_name="cred")
    db_session.add(site)
    await db_session.flush()
    cipher = load_token_cipher(get_settings())
    connection = await upsert_google_connection(
        db_session,
        workspace_id=workspace_id,
        userinfo=GoogleUserInfo(sub="g-cred", email="cred@gmail.com"),
        token=GoogleTokenResponse(
            access_token="a", expires_in=3600, scopes=("openid",), refresh_token="r"
        ),
        cipher=cipher,
    )
    db_session.add_all(
        [
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=connection.id,
                resource_type=ResourceType.GA4_PROPERTY,
                resource_id="properties/42",
            ),
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=connection.id,
                resource_type=ResourceType.GSC_SITE,
                resource_id="sc-domain:cred.test",
            ),
        ]
    )
    await db_session.flush()
    oauth = FakeOAuth(DiscoveredResources(ga4_properties=(), gsc_sites=()))
    credentials = await resolve_google_credentials(db_session, site, oauth=oauth, cipher=cipher)
    assert credentials.ga4_property == "properties/42" and credentials.ga4_token == "tok"
    assert credentials.gsc_site == "sc-domain:cred.test" and credentials.gsc_token == "tok"
    assert "tok" not in repr(credentials)


async def test_credentials_of_an_unlinked_site_are_empty(db_session: AsyncSession, make_user) -> None:
    user = await make_user(sub="cred-none")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain="cred-none.test", display_name="x")
    db_session.add(site)
    await db_session.flush()
    oauth = FakeOAuth(DiscoveredResources(ga4_properties=(), gsc_sites=()))
    credentials = await resolve_google_credentials(
        db_session, site, oauth=oauth, cipher=load_token_cipher(get_settings())
    )
    assert credentials.ga4_property is None and credentials.gsc_site is None


# -- Unicité de (métrique, jour, dimensions brutes) : une ligne répétée ne double pas ----


def test_ga4_repeated_total_row_is_not_doubled() -> None:
    row = ("20260920", ["12", "30", "8", "2", "99.5"])
    observations = parse_totals(_ga4_totals(row, row))
    assert len(observations) == 5
    assert {o.metric: o.value for o in observations}["sessions"] == 12.0


def test_ga4_repeated_event_row_is_not_doubled_but_cleaning_collisions_are_summed() -> None:
    observations = parse_events(
        _ga4_events(
            ("20260920", "purchase", "3"),
            ("20260920", "purchase", "3"),  # répétée par Google : comptée une fois
            ("20260920", " scroll", "4"),  # nettoyée en « scroll », collision
            ("20260920", "scroll", "5"),
        ),
        top_n=25,
    )
    assert {o.dims["event_name"]: o.value for o in observations} == {"purchase": 3.0, "scroll": 9.0}


def test_gsc_repeated_rows_are_not_doubled() -> None:
    total = {"keys": ["2026-09-20"], "clicks": 4, "impressions": 40, "ctr": 0.1, "position": 7.5}
    totals = parse_gsc_totals(_gsc(total, total))
    assert len(totals) == 4
    assert {o.metric: o.value for o in totals} == {
        "clicks": 4.0, "impressions": 40.0, "ctr": 0.1, "position": 7.5,
    }
    page = {"keys": ["2026-09-20", "https://exemple.fr/a"], "clicks": 2, "impressions": 10,
            "ctr": 0.2, "position": 3}
    other = {"keys": ["2026-09-20", "https://exemple.fr/a?x=1"], "clicks": 3, "impressions": 20,
             "ctr": 0.15, "position": 4}
    observations = parse_dimension(_gsc(page, page, other), "page", top_n=25)
    # Le doublon brut est ignoré ; l'URL distincte qui donne le même chemin est additionnée.
    assert [(o.metric, o.value) for o in observations] == [("clicks", 5.0), ("impressions", 30.0)]


async def test_ga4_source_does_not_double_a_day_returned_by_two_chunks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if len(body["dimensions"]) == 1:
            # Chaque tranche renvoie aussi le 20 : seule la tranche qui le contient le garde.
            return httpx.Response(200, json=_ga4_totals(("20260920", ["5"] * 5)))
        return httpx.Response(200, json=_ga4_events(("20260920", "purchase", "1")))

    source = Ga4Source(property_id="42", token="jeton", client=_client(handler))
    observations = await source.collect(SITE, DayRange(date(2026, 8, 1), date(2026, 9, 20)))
    sessions = [o for o in observations if o.metric == "sessions"]
    assert len(sessions) == 1 and sessions[0].value == 5.0


# -- Pagination : jamais de collecte silencieusement partielle ----------------------------


def _ga4_page(rows: list[tuple[str, str, str]], *, row_count: int | None) -> dict:
    payload = _ga4_events(*rows)
    if row_count is not None:
        payload["rowCount"] = row_count
    return payload


async def test_ga4_events_follow_row_count_with_offset(monkeypatch) -> None:
    monkeypatch.setattr(ga4_module, "_EVENTS_LIMIT", 2)
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if len(body["dimensions"]) == 1:
            return httpx.Response(200, json=_ga4_totals(("20260920", ["5"] * 5)))
        offsets.append(body["offset"])
        assert body["limit"] == 2
        pages = {
            0: [("20260920", "purchase", "3"), ("20260920", "scroll", "4")],
            2: [("20260920", "click", "1"), ("20260920", "scroll", "4")],  # doublon identique
            4: [("20260920", "search", "2")],
        }
        return httpx.Response(200, json=_ga4_page(pages[body["offset"]], row_count=5))

    source = Ga4Source(property_id="42", token="jeton", client=_client(handler))
    observations = await source.collect(SITE, DayRange(date(2026, 9, 20), date(2026, 9, 20)))
    assert offsets == [0, 2, 4]
    events = {o.dims["event_name"]: o.value for o in observations if o.metric == "event_count"}
    assert events == {"purchase": 3.0, "scroll": 4.0, "click": 1.0, "search": 2.0}


async def test_ga4_full_page_without_row_count_requests_the_next_page(monkeypatch) -> None:
    monkeypatch.setattr(ga4_module, "_EVENTS_LIMIT", 2)
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if len(body["dimensions"]) == 1:
            return httpx.Response(200, json=_ga4_totals(("20260920", ["5"] * 5)))
        offsets.append(body["offset"])
        if body["offset"] == 0:
            rows = [("20260920", "a", "1"), ("20260920", "b", "2")]
        else:
            rows = [("20260920", "c", "3")]
        return httpx.Response(200, json=_ga4_page(rows, row_count=None))

    source = Ga4Source(property_id="42", token="jeton", client=_client(handler))
    observations = await source.collect(SITE, DayRange(date(2026, 9, 20), date(2026, 9, 20)))
    assert offsets == [0, 2]
    names = {o.dims["event_name"] for o in observations if o.metric == "event_count"}
    assert names == {"a", "b", "c"}


async def test_ga4_page_cap_raises_instead_of_returning_partial_data(monkeypatch) -> None:
    monkeypatch.setattr(ga4_module, "_EVENTS_LIMIT", 1)
    monkeypatch.setattr(ga4_module, "_MAX_PAGES", 3)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        body = json.loads(request.content)
        if len(body["dimensions"]) == 1:
            return httpx.Response(200, json=_ga4_totals(("20260920", ["5"] * 5)))
        calls += 1
        return httpx.Response(
            200, json=_ga4_page([("20260920", f"e{body['offset']}", "1")], row_count=100)
        )

    source = Ga4Source(property_id="42", token="jeton", client=_client(handler))
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, DayRange(date(2026, 9, 20), date(2026, 9, 20)))
    assert calls == 3
    assert excinfo.value.reason == "truncated" and excinfo.value.recoverable


def _gsc_row(day: str, key: str, clicks: int) -> dict:
    return {"keys": [day, key], "clicks": clicks, "impressions": 10, "ctr": 0.1, "position": 2}


async def test_gsc_full_page_requests_the_next_page_without_double_counting(monkeypatch) -> None:
    monkeypatch.setattr(gsc_module, "_ROW_LIMIT", 2)
    starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["dimensions"] != ["date", "page"]:
            return httpx.Response(200, json=_gsc())
        starts.append(body["startRow"])
        pages = {
            0: [
                _gsc_row("2026-09-20", "https://exemple.fr/a", 5),
                _gsc_row("2026-09-20", "https://exemple.fr/b", 4),
            ],
            2: [
                _gsc_row("2026-09-20", "https://exemple.fr/c", 3),
                _gsc_row("2026-09-20", "https://exemple.fr/b", 4),  # doublon identique
            ],
            4: [_gsc_row("2026-09-20", "https://exemple.fr/d", 1)],
        }
        return httpx.Response(200, json=_gsc(*pages[body["startRow"]]))

    source = GscSource(site_url="sc-domain:exemple.fr", token="jeton", client=_client(handler))
    observations = await source.collect(SITE, DayRange(date(2026, 9, 20), date(2026, 9, 20)))
    assert starts == [0, 2, 4]
    clicks = {o.dims["page"]: o.value for o in observations if o.metric == "clicks" and o.dims}
    assert clicks == {"/a": 5.0, "/b": 4.0, "/c": 3.0, "/d": 1.0}


async def test_gsc_page_cap_raises_instead_of_returning_partial_data(monkeypatch) -> None:
    monkeypatch.setattr(gsc_module, "_ROW_LIMIT", 1)
    monkeypatch.setattr(gsc_module, "_MAX_PAGES", 3)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        body = json.loads(request.content)
        if body["dimensions"] == ["date"]:
            return httpx.Response(200, json=_gsc())
        calls += 1
        return httpx.Response(
            200, json=_gsc(_gsc_row("2026-09-20", f"https://exemple.fr/p{calls}", 1))
        )

    source = GscSource(site_url="sc-domain:exemple.fr", token="jeton", client=_client(handler))
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, DayRange(date(2026, 9, 20), date(2026, 9, 20)))
    assert calls == 3
    assert excinfo.value.reason == "truncated" and excinfo.value.recoverable


async def test_gsc_source_does_not_double_a_day_returned_by_two_chunks() -> None:
    total = {"keys": ["2026-09-20"], "clicks": 4, "impressions": 40, "ctr": 0.1, "position": 7}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["dimensions"] == ["date"]:
            return httpx.Response(200, json=_gsc(total))
        return httpx.Response(200, json=_gsc(_gsc_row("2026-09-20", "https://exemple.fr/a", 2)))

    source = GscSource(site_url="sc-domain:exemple.fr", token="jeton", client=_client(handler))
    observations = await source.collect(SITE, DayRange(date(2026, 8, 1), date(2026, 9, 20)))
    assert len([o for o in observations if o.metric == "clicks" and not o.dims]) == 1
    assert len([o for o in observations if o.metric == "clicks" and "page" in o.dims]) == 1


# -- Erreurs HTTP 400, formes de réponse, doublons conflictuels ---------------------------


async def test_http_400_is_a_definitive_error() -> None:
    source = Ga4Source(
        property_id="properties/42",
        token="jeton",
        client=_client(lambda request: httpx.Response(400, json={"error": {}})),
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, WINDOW)
    assert (excinfo.value.reason, excinfo.value.recoverable) == ("bad_request", False)


@pytest.mark.parametrize("payload", [{}, {"x": 1}])
def test_ga4_response_without_metric_headers_is_not_read_as_no_data(payload) -> None:
    for parser in (parse_totals, lambda p: parse_events(p, top_n=25)):
        with pytest.raises(SourceError) as excinfo:
            parser(payload)
        assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


def test_gsc_response_shapes() -> None:
    assert parse_gsc_totals({"x": 1}) == []
    assert parse_dimension({"x": 1}, "page", top_n=25) == []
    for payload in ([], "texte"):
        for parser in (parse_gsc_totals, lambda p: parse_dimension(p, "page", top_n=25)):
            with pytest.raises(SourceError) as excinfo:
                parser(payload)
            assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


def test_conflicting_duplicate_rows_are_an_api_error() -> None:
    parsers = [
        lambda: parse_totals(_ga4_totals(("20260920", ["1"] * 5), ("20260920", ["2"] * 5))),
        lambda: parse_events(
            _ga4_events(("20260920", "purchase", "3"), ("20260920", "purchase", "4")), top_n=25
        ),
        lambda: parse_gsc_totals(
            _gsc(
                {"keys": ["2026-09-20"], "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 1},
                {"keys": ["2026-09-20"], "clicks": 9, "impressions": 2, "ctr": 0.5, "position": 1},
            )
        ),
        lambda: parse_dimension(
            _gsc(
                _gsc_row("2026-09-20", "https://exemple.fr/a", 1),
                _gsc_row("2026-09-20", "https://exemple.fr/a", 2),
            ),
            "page",
            top_n=25,
        ),
    ]
    for parse in parsers:
        with pytest.raises(SourceError) as excinfo:
            parse()
        assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


# -- Jetons : échec temporaire ou connexion à reconnecter ---------------------------------


class _FailingOAuth(FakeOAuth):
    def __init__(self, error: Exception) -> None:
        super().__init__(DiscoveredResources(ga4_properties=(), gsc_sites=()))
        self._error = error

    async def refresh_access_token(self, *, refresh_token: str):
        raise self._error


async def _linked_site(db_session: AsyncSession, make_user, sub: str):
    user = await make_user(sub=sub)
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=f"{sub}.test", display_name=sub)
    db_session.add(site)
    await db_session.flush()
    cipher = load_token_cipher(get_settings())
    connection = await upsert_google_connection(
        db_session,
        workspace_id=workspace_id,
        userinfo=GoogleUserInfo(sub=f"g-{sub}", email=f"{sub}@gmail.com"),
        token=GoogleTokenResponse(
            access_token="a", expires_in=3600, scopes=("openid",), refresh_token="r"
        ),
        cipher=cipher,
    )
    db_session.add_all(
        [
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=connection.id,
                resource_type=ResourceType.GA4_PROPERTY,
                resource_id="properties/42",
            ),
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=connection.id,
                resource_type=ResourceType.GSC_SITE,
                resource_id=f"sc-domain:{sub}.test",
            ),
        ]
    )
    await db_session.flush()
    return site, connection, cipher


async def test_invalid_grant_is_a_definitive_error(db_session: AsyncSession, make_user) -> None:
    site, connection, cipher = await _linked_site(db_session, make_user, "cred-revoked")
    credentials = await resolve_google_credentials(
        db_session, site, oauth=_FailingOAuth(InvalidGrantError()), cipher=cipher
    )
    assert connection.status == ConnectionStatus.NEEDS_REAUTH
    assert credentials.ga4_token is None and credentials.gsc_token is None
    assert credentials.ga4_problem == "token_unavailable"
    assert credentials.gsc_problem == "token_unavailable"
    with pytest.raises(SourceError) as excinfo:
        await Ga4Source(
            property_id=credentials.ga4_property,
            token=credentials.ga4_token,
            token_problem=credentials.ga4_problem,
        ).collect(SITE, WINDOW)
    assert (excinfo.value.reason, excinfo.value.recoverable) == ("token_unavailable", False)


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("boom"), GoogleOAuthError("5xx")],
    ids=["network", "google-5xx"],
)
async def test_temporary_refresh_failure_is_recoverable(
    db_session: AsyncSession, make_user, error: Exception
) -> None:
    site, connection, cipher = await _linked_site(db_session, make_user, "cred-flaky")
    credentials = await resolve_google_credentials(
        db_session, site, oauth=_FailingOAuth(error), cipher=cipher
    )
    assert connection.status == ConnectionStatus.ACTIVE
    assert credentials.ga4_token is None and credentials.gsc_token is None
    assert credentials.ga4_problem == "token_refresh_failed"
    assert credentials.gsc_problem == "token_refresh_failed"
    for source in (
        Ga4Source(
            property_id=credentials.ga4_property,
            token=credentials.ga4_token,
            token_problem=credentials.ga4_problem,
        ),
        GscSource(
            site_url=credentials.gsc_site,
            token=credentials.gsc_token,
            token_problem=credentials.gsc_problem,
        ),
    ):
        with pytest.raises(SourceError) as excinfo:
            await source.collect(SITE, WINDOW)
        assert (excinfo.value.reason, excinfo.value.recoverable) == ("token_refresh_failed", True)


async def test_healthy_credentials_have_no_problem(db_session: AsyncSession, make_user) -> None:
    site, _, cipher = await _linked_site(db_session, make_user, "cred-ok")
    oauth = FakeOAuth(DiscoveredResources(ga4_properties=(), gsc_sites=()))
    credentials = await resolve_google_credentials(db_session, site, oauth=oauth, cipher=cipher)
    assert credentials.ga4_problem is None and credentials.gsc_problem is None
