import json
import logging
import sys

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.logging_config import (
    JsonFormatter,
    RequestContextMiddleware,
    configure_logging,
    request_id_var,
)


def _record(message: str = "bonjour", level: int = logging.INFO, **extra) -> logging.LogRecord:
    record = logging.LogRecord("app.test", level, __file__, 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_cloud_logging_fields() -> None:
    line = JsonFormatter().format(_record("bonjour", logging.WARNING))
    payload = json.loads(line)
    assert payload["severity"] == "WARNING"
    assert payload["message"] == "bonjour"
    assert payload["logger"] == "app.test"
    assert "time" in payload


def test_json_formatter_adds_request_id_and_extra_fields() -> None:
    token = request_id_var.set("req-12345678")
    try:
        payload = json.loads(JsonFormatter().format(_record(status=201, path="/x")))
    finally:
        request_id_var.reset(token)
    assert payload["request_id"] == "req-12345678"
    assert payload["status"] == 201
    assert payload["path"] == "/x"


def test_json_formatter_includes_the_traceback_in_the_message() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record("échec", logging.ERROR)
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))
    assert payload["severity"] == "ERROR"
    assert "Traceback" in payload["message"] and "ValueError: boom" in payload["message"]


def _app() -> FastAPI:
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)

    @application.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"id": item_id, "rid": request_id_var.get() or ""}

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


def _client(application: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=application, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://t")


async def test_request_id_is_generated_and_returned(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(_app()) as client:
        response = await client.get("/items/abc")
    rid = response.headers["x-request-id"]
    assert len(rid) >= 8
    assert response.json()["rid"] == rid  # visible dans le contexte du handler


async def test_valid_incoming_request_id_is_kept_and_invalid_one_replaced() -> None:
    async with _client(_app()) as client:
        kept = await client.get("/items/a", headers={"X-Request-ID": "trace-abcdef123"})
        bad = await client.get("/items/a", headers={"X-Request-ID": "x y\tz"})
    assert kept.headers["x-request-id"] == "trace-abcdef123"
    assert bad.headers["x-request-id"] != "x y\tz"


async def test_cloud_trace_header_becomes_the_request_id() -> None:
    trace = "105445aa7843bc8bf206b12000100000"
    async with _client(_app()) as client:
        response = await client.get(
            "/items/a", headers={"X-Cloud-Trace-Context": f"{trace}/1;o=1"}
        )
    assert response.headers["x-request-id"] == trace


async def test_access_log_uses_the_route_template_and_never_the_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(_app()) as client:
        await client.get("/items/SECRET-TOKEN-VALUE?code=OAUTH-CODE&state=abc")
    records = [r for r in caplog.records if r.name == "app.access"]
    assert len(records) == 1
    record = records[0]
    assert record.path == "/items/{item_id}"
    assert record.status == 200 and record.method == "GET"
    assert record.duration_ms >= 0
    everything = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "SECRET-TOKEN-VALUE" not in everything
    assert "OAUTH-CODE" not in everything


async def test_unmatched_routes_are_logged_without_the_raw_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(_app()) as client:
        response = await client.get("/secret/path/with-token-123")
    assert response.status_code == 404
    record = next(r for r in caplog.records if r.name == "app.access")
    assert record.path == "unmatched"
    assert "with-token-123" not in str(record.__dict__)


async def test_unhandled_exception_is_logged_as_error_with_the_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(_app()) as client:
        response = await client.get("/boom")
    assert response.status_code == 500
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and errors[0].exc_info is not None
    assert any(r.__dict__.get("status") == 500 for r in caplog.records)


async def test_health_checks_are_logged_at_debug_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(_app()) as client:
        await client.get("/health")
    assert [r for r in caplog.records if r.name == "app.access"] == []


def test_configure_logging_is_idempotent_and_leaves_foreign_handlers() -> None:
    foreign = logging.NullHandler()
    root = logging.getLogger()
    root.addHandler(foreign)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@h/db",
        token_enc_keys={1: "a" * 44},
        token_enc_active_version=1,
        app_secret_key="x" * 40,
    )
    try:
        configure_logging(settings)
        configure_logging(settings)
        managed = [h for h in root.handlers if getattr(h, "_cc_managed", False)]
        assert len(managed) == 1
        assert foreign in root.handlers
    finally:
        root.removeHandler(foreign)
        for handler in [h for h in root.handlers if getattr(h, "_cc_managed", False)]:
            root.removeHandler(handler)


def test_configure_logging_silences_loggers_that_print_full_urls() -> None:
    names = ("uvicorn.access", "httpx", "httpcore")
    previous = {n: logging.getLogger(n).level for n in names}
    root = logging.getLogger()
    try:
        for n in names:
            logging.getLogger(n).setLevel(logging.NOTSET)
        configure_logging(get_settings())
        for n in names:
            assert logging.getLogger(n).level == logging.WARNING, n
        assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    finally:
        for n, level in previous.items():
            logging.getLogger(n).setLevel(level)
        for handler in [h for h in root.handlers if getattr(h, "_cc_managed", False)]:
            root.removeHandler(handler)
