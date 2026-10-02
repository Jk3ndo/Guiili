import base64
import json

import httpx
import pytest

from app.services.gcp_metadata import MetadataError, MetadataTokenProvider
from app.services.jobs.cloud_tasks import CloudTasksQueue, task_id_for
from app.services.jobs.kinds import RunSpec
from app.services.jobs.queue import EnqueueError, TaskMessage

TARGET = "https://worker.example.run.app/internal/tasks/run"


class _Tokens:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def access_token(self) -> str:
        if self.fail:
            raise MetadataError("indisponible")
        return "jeton-acces"


def _queue(handler, tokens: _Tokens | None = None) -> CloudTasksQueue:
    return CloudTasksQueue(
        project="guiili",
        location="us-central1",
        queue_prefix="guiili",
        target_url=TARGET,
        invoker_email="guiili-tasks@guiili.iam.gserviceaccount.com",
        audience="https://worker.example.run.app",
        tokens=tokens or _Tokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


SPEC = RunSpec("backfill", None, None, "ga4-20260926T0000", {"source": "ga4"})


def test_task_ids_are_stable_and_valid() -> None:
    first = task_id_for(SPEC.key)
    assert first == task_id_for(SPEC.key)
    assert first.startswith("t-") and len(first) == 66
    assert all(c.isalnum() or c in "-_" for c in first)


async def test_a_task_is_created_in_its_source_queue_with_an_oidc_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"name": "ok"})

    await _queue(handler).enqueue(TaskMessage(SPEC, SPEC.queue))
    request = seen[0]
    assert request.url.path == "/v2/projects/guiili/locations/us-central1/queues/guiili-ga4/tasks"
    assert request.headers["Authorization"] == "Bearer jeton-acces"
    task = json.loads(request.content)["task"]
    assert task["name"].endswith(f"/tasks/{task_id_for(SPEC.key)}")
    assert task["dispatchDeadline"] == "900s"
    http_request = task["httpRequest"]
    assert http_request["url"] == TARGET and http_request["httpMethod"] == "POST"
    assert http_request["oidcToken"] == {
        "serviceAccountEmail": "guiili-tasks@guiili.iam.gserviceaccount.com",
        "audience": "https://worker.example.run.app",
    }
    assert json.loads(base64.b64decode(http_request["body"])) == SPEC.to_payload()


async def test_a_409_already_exists_is_a_silent_duplicate() -> None:
    body = {"error": {"code": 409, "status": "ALREADY_EXISTS", "message": "x"}}
    queue = _queue(lambda request: httpx.Response(409, json=body))
    await queue.enqueue(TaskMessage(SPEC, "ga4"))  # ne lève pas


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(409, json={}),
        httpx.Response(409, json={"error": {"code": 409, "status": "ABORTED"}}),
        httpx.Response(409, content=b"<html>conflict</html>"),
    ],
)
async def test_any_other_409_is_an_enqueue_error(response: httpx.Response) -> None:
    queue = _queue(lambda request: response)
    with pytest.raises(EnqueueError) as excinfo:
        await queue.enqueue(TaskMessage(SPEC, "ga4"))
    assert excinfo.value.reason == "http_409"


@pytest.mark.parametrize("status", [400, 403, 429, 500])
async def test_other_http_errors_raise_enqueue_error(status: int) -> None:
    with pytest.raises(EnqueueError) as excinfo:
        await _queue(lambda request: httpx.Response(status, json={})).enqueue(
            TaskMessage(SPEC, "ga4")
        )
    assert excinfo.value.reason == f"http_{status}"


async def test_network_and_credential_failures_raise_enqueue_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(EnqueueError) as network:
        await _queue(boom).enqueue(TaskMessage(SPEC, "ga4"))
    assert network.value.reason == "network"
    with pytest.raises(EnqueueError) as credentials:
        await _queue(lambda r: httpx.Response(200), _Tokens(fail=True)).enqueue(
            TaskMessage(SPEC, "ga4")
        )
    assert credentials.value.reason == "credentials"


async def test_metadata_tokens_are_cached_until_near_expiry() -> None:
    calls: list[str] = []
    clock = [1000.0]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Metadata-Flavor"] == "Google"
        calls.append(request.url.path)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": f"a{len(calls)}", "expires_in": 3599})
        assert request.url.params["audience"] == "https://worker.example.run.app"
        return httpx.Response(200, text=f"id{len(calls)}")

    provider = MetadataTokenProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), clock=lambda: clock[0]
    )
    assert await provider.access_token() == "a1"
    assert await provider.access_token() == "a1"
    clock[0] += 3599 - 30  # moins de 60 s avant l'expiration : renouvelé
    assert await provider.access_token() == "a2"
    assert await provider.identity_token("https://worker.example.run.app") == "id3"
    assert await provider.identity_token("https://worker.example.run.app") == "id3"


async def test_metadata_failure_raises_metadata_error() -> None:
    provider = MetadataTokenProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    )
    with pytest.raises(MetadataError):
        await provider.access_token()
