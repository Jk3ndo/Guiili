"""File Cloud Tasks (API REST v2). Une file par source (quotas Google) : le débit, les
nouvelles tentatives et le backoff sont réglés sur la file (runbook). Chaque tâche porte
un jeton OIDC du compte `tasks_invoker_service_account`, vérifié par le worker. Le nom
de la tâche dérive de la clé d'idempotence : Cloud Tasks refuse un doublon (409)."""

from __future__ import annotations

import base64
import hashlib
import json

import httpx

from app.services.gcp_metadata import AccessTokenProvider, MetadataError
from app.services.jobs.queue import EnqueueError, TaskMessage

_API = "https://cloudtasks.googleapis.com/v2/{parent}/tasks"
_TIMEOUT = httpx.Timeout(10.0)


def task_id_for(key: str) -> str:
    return "t-" + hashlib.sha256(key.encode("utf-8")).hexdigest()


def _is_already_exists(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    return isinstance(error, dict) and error.get("status") == "ALREADY_EXISTS"


class CloudTasksQueue:
    def __init__(
        self,
        *,
        project: str,
        location: str,
        queue_prefix: str,
        target_url: str,
        invoker_email: str,
        audience: str,
        tokens: AccessTokenProvider,
        client: httpx.AsyncClient | None = None,
        dispatch_deadline_seconds: int = 900,
    ) -> None:
        self._project = project
        self._location = location
        self._prefix = queue_prefix
        self._target_url = target_url
        self._invoker_email = invoker_email
        self._audience = audience
        self._tokens = tokens
        self._client = client
        self._deadline = dispatch_deadline_seconds

    async def enqueue(self, message: TaskMessage) -> None:
        parent = (
            f"projects/{self._project}/locations/{self._location}"
            f"/queues/{self._prefix}-{message.queue}"
        )
        body = json.dumps(message.spec.to_payload(), separators=(",", ":")).encode("utf-8")
        task = {
            "name": f"{parent}/tasks/{task_id_for(message.spec.key)}",
            "dispatchDeadline": f"{self._deadline}s",
            "httpRequest": {
                "httpMethod": "POST",
                "url": self._target_url,
                "headers": {"Content-Type": "application/json"},
                "body": base64.b64encode(body).decode("ascii"),
                "oidcToken": {
                    "serviceAccountEmail": self._invoker_email,
                    "audience": self._audience,
                },
            },
        }
        try:
            token = await self._tokens.access_token()
        except MetadataError:
            raise EnqueueError("credentials") from None
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            response = await http.post(
                _API.format(parent=parent),
                json={"task": task},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError:
            raise EnqueueError("network") from None
        finally:
            if owns:
                await http.aclose()
        if response.status_code == 409:
            if _is_already_exists(response):  # déjà déposée : c'est le but de la clé
                return
            raise EnqueueError("http_409")
        if response.status_code >= 400:
            raise EnqueueError(f"http_{response.status_code}")
