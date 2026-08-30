from __future__ import annotations

from app.config import Settings
from app.services.google_oauth.base import GoogleOAuthClient
from app.services.google_oauth.mock import MockGoogleOAuthClient
from app.services.google_oauth.real import RealGoogleOAuthClient


def get_google_oauth_client(settings: Settings) -> GoogleOAuthClient:
    if settings.google_oauth_mock:
        return MockGoogleOAuthClient(redirect_uri=settings.google_oauth_redirect_uri)
    return RealGoogleOAuthClient(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        redirect_uri=settings.google_oauth_redirect_uri,
    )
