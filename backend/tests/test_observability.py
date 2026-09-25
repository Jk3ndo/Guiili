import pytest
import sentry_sdk

from app.config import Settings
from app.observability import init_sentry, scrub_event


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@h/db",
        token_enc_keys={1: "a" * 44},
        token_enc_active_version=1,
        app_secret_key="x" * 40,
        **overrides,
    )


def test_scrub_event_drops_request_payloads_and_secrets() -> None:
    event = {
        "request": {
            "url": "https://api.example.com/api/v1/auth/google/callback?code=abc&state=def",
            "query_string": "code=abc&state=def",
            "cookies": {"cc_session": "SESSION"},
            "headers": {"Authorization": "Bearer X", "Cookie": "cc_session=SESSION"},
            "data": {"password": "hunter2"},
        },
        "extra": {"refresh_token": "R", "access_token": "A", "status_code": 500, "code": "C"},
        "contexts": {"auth": {"api_key": "K", "note": "ok"}},
        "message": "ok",
    }
    cleaned = scrub_event(event, {})
    assert cleaned is not None
    request = cleaned["request"]
    assert "query_string" not in request and "cookies" not in request
    assert "headers" not in request and "data" not in request
    assert "code=abc" not in request["url"] and request["url"].endswith("/callback")
    assert cleaned["extra"]["refresh_token"] == "[Filtered]"
    assert cleaned["extra"]["access_token"] == "[Filtered]"
    assert cleaned["extra"]["code"] == "[Filtered]"
    assert cleaned["extra"]["status_code"] == 500  # « code » exact seulement
    assert cleaned["contexts"]["auth"]["api_key"] == "[Filtered]"
    assert cleaned["contexts"]["auth"]["note"] == "ok"
    assert cleaned["message"] == "ok"


def test_scrub_event_tolerates_events_without_request() -> None:
    assert scrub_event({"message": "x"}, {}) == {"message": "x"}


def test_scrub_event_masks_url_query_strings_in_exceptions_and_messages() -> None:
    leaky = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=x&key=SECRET123"
    event = {
        "exception": {
            "values": [
                {"type": "HTTPStatusError", "value": f"Client error '403' for url '{leaky}'"},
                {"type": "RuntimeError", "value": None},
                {"type": "ValueError", "value": "no url here"},
            ]
        },
        "message": f"appel echoue: {leaky} (retry)",
        "logentry": {"message": f"GET {leaky}", "formatted": f"GET {leaky}"},
        "breadcrumbs": {
            "values": [
                {"message": f"HTTP {leaky}", "data": {"url": leaky, "status_code": 403}},
            ]
        },
    }
    cleaned = scrub_event(event, {})
    assert cleaned is not None
    assert "SECRET123" not in repr(cleaned)
    values = cleaned["exception"]["values"]
    assert values[0]["value"] == (
        "Client error '403' for url "
        "'https://www.googleapis.com/pagespeedonline/v5/runPagespeed?[Filtered]'"
    )
    assert values[1]["value"] is None
    assert values[2]["value"] == "no url here"
    assert cleaned["message"] == (
        "appel echoue: https://www.googleapis.com/pagespeedonline/v5/runPagespeed?[Filtered] (retry)"
    )
    assert cleaned["logentry"]["message"].endswith("runPagespeed?[Filtered]")
    assert cleaned["logentry"]["formatted"].endswith("runPagespeed?[Filtered]")
    crumb = cleaned["breadcrumbs"]["values"][0]
    assert crumb["data"]["url"].endswith("runPagespeed?[Filtered]")
    assert crumb["data"]["status_code"] == 403


def test_init_is_a_no_op_without_dsn() -> None:
    assert init_sentry(_settings()) is False


def test_init_configures_a_private_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setenv("K_REVISION", "backend-guiili-00042-abc")
    settings = _settings(
        sentry_dsn="https://public@example.ingest.sentry.io/1",
        sentry_traces_sample_rate=0.1,
        environment="staging",
        google_oauth_mock=False,  # garde non-local ; tests/conftest.py force true via l'env
        frontend_base_url="https://app.example.com",
        cors_origins=["https://app.example.com"],
    )
    assert init_sentry(settings) is True
    assert captured["dsn"] == "https://public@example.ingest.sentry.io/1"
    assert captured["environment"] == "staging"
    assert captured["release"] == "backend-guiili-00042-abc"
    assert captured["send_default_pii"] is False
    assert captured["traces_sample_rate"] == 0.1
    assert captured["max_request_body_size"] == "never"
    assert captured["include_local_variables"] is False
    assert captured["before_send"] is scrub_event
