import json
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_gtm_headless_verifier
from app.api.internal import get_headless_runner
from app.config import get_settings
from app.db.session import get_session
from app.security.oidc import OidcVerifier
from app.services.gcp_metadata import MetadataError
from app.services.gtm_check import GtmFinding
from app.services.gtm_headless import (
    HEADLESS_FAILED,
    GtmHeadlessResult,
    headless_result_from_dict,
    headless_result_to_dict,
    verify_gtm,
)
from app.services.worker_client import RemoteHeadlessVerifier
from app.worker_main import create_worker_app
from tests.jobs_fakes import SIGNING_KEY, google_id_token, jwks_for, make_site

WORKER = "https://worker.example.run.app"
API_ACCOUNT = "backend-guiili@guiili.iam.gserviceaccount.com"
RESULT = GtmHeadlessResult(
    gtm_js_loaded=True,
    containers_initialised=("GTM-ABC1234",),
    datalayer_present=True,
    gtm_events=("gtm.js", "gtm.dom"),
    requests_before_consent=True,
    csp_console_errors=("Refused to load 'https://www.googletagmanager.com/gtm.js'",),
    findings=(GtmFinding(code="headless_csp_blocks_gtm", severity="high", title="t", detail="d"),),
    checked_at=datetime(2026, 9, 26, 6, 0, tzinfo=UTC),
    ga4_measurement_ids=("G-ABCDEF12",),
    ads_requests=2,
    consent_default_seen=True,
)


class _Tokens:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.audiences: list[str] = []

    async def identity_token(self, audience: str) -> str:
        self.audiences.append(audience)
        if self.fail:
            raise MetadataError("hors Cloud Run")
        return google_id_token(audience=audience, email=API_ACCOUNT)


def test_the_result_survives_the_round_trip() -> None:
    assert headless_result_from_dict(headless_result_to_dict(RESULT)) == RESULT


@pytest.mark.parametrize(
    "payload",
    [[], {}, {**headless_result_to_dict(RESULT), "gtm_js_loaded": "oui"},
     {**headless_result_to_dict(RESULT), "findings": ["x"]}],
)
def test_an_unexpected_shape_is_rejected(payload) -> None:
    with pytest.raises(ValueError):
        headless_result_from_dict(payload)


async def test_the_remote_verifier_calls_the_worker_with_an_identity_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=headless_result_to_dict(RESULT))

    tokens = _Tokens()
    verifier = RemoteHeadlessVerifier(
        base_url=WORKER, audience=WORKER, tokens=tokens,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await verifier("https://exemple.fr") == RESULT
    assert str(seen[0].url) == f"{WORKER}/internal/headless/verify"
    assert json.loads(seen[0].content) == {"url": "https://exemple.fr"}
    assert seen[0].headers["Authorization"].startswith("Bearer ")
    assert tokens.audiences == [WORKER]


@pytest.mark.parametrize("status", [401, 404, 503])
async def test_a_worker_error_becomes_a_failed_result(status: int) -> None:
    verifier = RemoteHeadlessVerifier(
        base_url=WORKER, audience=WORKER, tokens=_Tokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status))),
    )
    result = await verifier("https://exemple.fr")
    assert result.error == HEADLESS_FAILED and result.gtm_js_loaded is False


async def test_network_and_token_failures_become_failed_results() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lent", request=request)

    network = RemoteHeadlessVerifier(
        base_url=WORKER, audience=WORKER, tokens=_Tokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(boom)),
    )
    assert (await network("https://exemple.fr")).error == HEADLESS_FAILED
    no_token = RemoteHeadlessVerifier(base_url=WORKER, audience=WORKER, tokens=_Tokens(fail=True))
    assert (await no_token("https://exemple.fr")).error == HEADLESS_FAILED


def test_the_api_delegates_only_when_a_worker_is_configured() -> None:
    local = get_settings().model_copy(update={"worker_base_url": ""})
    assert get_gtm_headless_verifier(local) is verify_gtm
    deployed = get_settings().model_copy(
        update={"worker_base_url": WORKER, "internal_oidc_audience": WORKER}
    )
    assert isinstance(get_gtm_headless_verifier(deployed), RemoteHeadlessVerifier)


async def test_the_remote_verifier_speaks_the_real_worker_contract(
    db_session: AsyncSession, make_user
) -> None:
    await make_site(db_session, make_user, "delegation.test")

    async def fetch_jwks() -> dict:
        return jwks_for(SIGNING_KEY)

    async def fake_browser(url: str) -> GtmHeadlessResult:
        return RESULT

    async def _session():
        yield db_session

    worker = create_worker_app(
        get_settings(),
        oidc_verifier=OidcVerifier(
            audience=WORKER, allowed_emails={API_ACCOUNT}, fetch_jwks=fetch_jwks
        ),
    )
    worker.dependency_overrides[get_session] = _session
    worker.dependency_overrides[get_headless_runner] = lambda: fake_browser
    verifier = RemoteHeadlessVerifier(
        base_url=WORKER, audience=WORKER, tokens=_Tokens(),
        client=httpx.AsyncClient(transport=ASGITransport(app=worker), base_url=WORKER),
    )
    assert await verifier("https://delegation.test") == RESULT
