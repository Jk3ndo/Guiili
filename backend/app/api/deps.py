from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.models.user import User
from app.security.session import read_session
from app.security.token_crypto import TokenCipher, load_token_cipher
from app.services.audit_engine import Detector
from app.services.audit_probe import AuditProbe, MockAuditProbe, RealAuditProbe
from app.services.google_oauth import GoogleOAuthClient, get_google_oauth_client
from app.services.stack_detector import detect_stack

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_token_cipher(settings: SettingsDep) -> TokenCipher:
    return load_token_cipher(settings)


def get_google_client(settings: SettingsDep) -> GoogleOAuthClient:
    return get_google_oauth_client(settings)


def get_audit_probe(settings: SettingsDep) -> AuditProbe:
    return MockAuditProbe() if settings.audit_probe_mock else RealAuditProbe()


def get_stack_detector() -> Detector:
    return detect_stack


TokenCipherDep = Annotated[TokenCipher, Depends(get_token_cipher)]
GoogleClientDep = Annotated[GoogleOAuthClient, Depends(get_google_client)]
AuditProbeDep = Annotated[AuditProbe, Depends(get_audit_probe)]
StackDetectorDep = Annotated[Detector, Depends(get_stack_detector)]


def _session_user_id(request: Request, settings: Settings):
    cookie = request.cookies.get(settings.session_cookie_name)
    return read_session(cookie, secret=settings.app_secret_key.get_secret_value())


async def get_current_user(request: Request, session: SessionDep, settings: SettingsDep) -> User:
    user_id = _session_user_id(request, settings)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentification requise"
        )
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session invalide")
    return user


async def get_optional_user(
    request: Request, session: SessionDep, settings: SettingsDep
) -> User | None:
    user_id = _session_user_id(request, settings)
    if user_id is None:
        return None
    return await session.get(User, user_id)


CurrentUserDep = Annotated[User, Depends(get_current_user)]
OptionalUserDep = Annotated[User | None, Depends(get_optional_user)]
