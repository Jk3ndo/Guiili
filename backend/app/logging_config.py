"""Journalisation structurée et contexte de requête.

Objectifs :
- une ligne JSON par événement en production (Cloud Logging la structure seule) ;
- un identifiant de requête (`request_id`) présent dans toutes les lignes émises
  pendant la requête ;
- une ligne d'accès par requête, **sans chaîne de requête ni chemin brut** (les
  codes OAuth, jetons d'invitation et de réinitialisation y figureraient).
Les exceptions non gérées sont journalisées en ERROR avec leur traceback dans le
message : Cloud Error Reporting les regroupe sans configuration supplémentaire.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}

_ACCESS = logging.getLogger("app.access")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")
_TRACE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_QUIET_PATHS = frozenset({"/health", "/health/db"})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": message,
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def configure_logging(settings: Settings) -> None:
    """Installe le handler applicatif ; sans effet sur les handlers étrangers
    (pytest, uvicorn) et sans doublon si appelée plusieurs fois."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_cc_managed", False)]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler._cc_managed = True  # type: ignore[attr-defined]
    handler.addFilter(_RequestIdFilter())
    if settings.json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # uvicorn journalise le chemin COMPLET, chaîne de requête comprise (codes OAuth) :
    # la ligne d'accès de `RequestContextMiddleware` la remplace.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _incoming_request_id(headers: list[tuple[bytes, bytes]]) -> str:
    trace: str | None = None
    for name, value in headers:
        text = value.decode("latin-1")
        if name == b"x-request-id" and _ID_PATTERN.match(text):
            return text
        if name == b"x-cloud-trace-context":
            candidate = text.split("/", 1)[0]
            if _TRACE_PATTERN.match(candidate):
                trace = candidate
    return trace or uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope.get("headers", []))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            _ACCESS.exception("exception non gérée")
            raise
        finally:
            route = scope.get("route")
            path = getattr(route, "path", None) or "unmatched"
            level = logging.DEBUG if path in _QUIET_PATHS else logging.INFO
            _ACCESS.log(
                level,
                "request",
                extra={
                    "method": scope["method"],
                    "path": path,
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)
