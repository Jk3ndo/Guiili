"""L'adaptateur mock : fixtures deterministes, aucun reseau, alignees front."""

import pytest

from app.services.google_oauth import InvalidGrantError
from app.services.google_oauth.mock import MOCK_FIXTURES, MockGoogleOAuthClient


@pytest.fixture
def client() -> MockGoogleOAuthClient:
    return MockGoogleOAuthClient()


def test_authorization_url_carries_pkce_and_state(client: MockGoogleOAuthClient) -> None:
    url = client.build_authorization_url(state="st-123", code_challenge="ch-abc")
    assert "state=st-123" in url
    assert "code_challenge=ch-abc" in url
    assert "code_challenge_method=S256" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


async def test_exchange_code_selects_fixture(client: MockGoogleOAuthClient) -> None:
    token = await client.exchange_code(code="mock:client_perso", code_verifier="v")
    assert token.refresh_token == "mock-refresh|google-sub-client-perso"
    info = await client.fetch_userinfo(access_token=token.access_token)
    assert info.email == "client.perso@gmail.com"
    assert info.sub == "google-sub-client-perso"


async def test_default_fixture_is_dev_agence(client: MockGoogleOAuthClient) -> None:
    token = await client.exchange_code(code="whatever", code_verifier="v")
    info = await client.fetch_userinfo(access_token=token.access_token)
    assert info.email == "dev.agence@gmail.com"


async def test_discover_resources_matches_frontend_mock(
    client: MockGoogleOAuthClient,
) -> None:
    token = await client.exchange_code(code="mock:dev_agence", code_verifier="v")
    res = await client.discover_resources(access_token=token.access_token)
    gtm_ids = {c.resource_id for c in res.gtm_containers}
    gsc_ids = {s.resource_id for s in res.gsc_sites}
    assert "GTM-PK2X9QM" in gtm_ids
    assert "sc-domain:boutique-verte.fr" in gsc_ids

    token2 = await client.exchange_code(code="mock:client_perso", code_verifier="v")
    res2 = await client.discover_resources(access_token=token2.access_token)
    ga4_ids = {p.resource_id for p in res2.ga4_properties}
    assert "properties/447213908" in ga4_ids
    assert res2.gtm_containers == ()


async def test_refresh_access_token_round_trips(client: MockGoogleOAuthClient) -> None:
    sub = MOCK_FIXTURES["dev_agence"].sub
    token = await client.refresh_access_token(refresh_token=f"mock-refresh|{sub}")
    info = await client.fetch_userinfo(access_token=token.access_token)
    assert info.sub == sub
    assert token.refresh_token is None  # pas de nouveau refresh au rafraichissement


async def test_refresh_rejects_revoked_and_unknown(
    client: MockGoogleOAuthClient,
) -> None:
    with pytest.raises(InvalidGrantError):
        await client.refresh_access_token(refresh_token="mock-refresh|xyz|revoked")
    with pytest.raises(InvalidGrantError):
        await client.refresh_access_token(refresh_token="mock-refresh|ghost")
