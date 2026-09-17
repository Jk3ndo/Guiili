from app.services.google_oauth.base import GOOGLE_DATA_SCOPES, GOOGLE_LOGIN_SCOPES


def test_data_scopes_include_identity_and_readonly_apis() -> None:
    assert "openid" in GOOGLE_DATA_SCOPES
    assert "email" in GOOGLE_DATA_SCOPES
    assert "https://www.googleapis.com/auth/analytics.readonly" in GOOGLE_DATA_SCOPES
    assert "https://www.googleapis.com/auth/webmasters.readonly" in GOOGLE_DATA_SCOPES
    assert not any("tagmanager" in scope for scope in GOOGLE_DATA_SCOPES)


def test_data_scopes_distinct_from_login_scopes() -> None:
    assert GOOGLE_DATA_SCOPES != GOOGLE_LOGIN_SCOPES
