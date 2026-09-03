from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.models.user import User
from app.security.session import read_session
from app.security.token_crypto import TokenCipher, load_token_cipher
from app.services.audit_engine import Detector, TlsChecker
from app.services.audit_probe import AuditProbe, MockAuditProbe, RealAuditProbe
from app.services.google_oauth import GoogleOAuthClient, get_google_oauth_client
from app.services.stack_detector import StackDetection, demo_detector, detect_stack
from app.services.tls_check import check_certificate

# Detecteur qui accepte `allow_insecure=` (contrairement a `Detector`, 1-arg).
LiveDetector = Callable[..., Awaitable[StackDetection]]

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_token_cipher(settings: SettingsDep) -> TokenCipher:
    return load_token_cipher(settings)


def get_google_client(settings: SettingsDep) -> GoogleOAuthClient:
    return get_google_oauth_client(settings)


def get_audit_probe(settings: SettingsDep) -> AuditProbe:
    if settings.audit_probe_mock:
        return MockAuditProbe()
    return RealAuditProbe(
        api_key=settings.pagespeed_api_key.get_secret_value() or None,
        oauth_client=get_google_oauth_client(settings),
        cipher=load_token_cipher(settings),
    )


def get_stack_detector(settings: SettingsDep) -> Detector:
    # En mode mock les domaines de démo n'ont pas de vrai site à sonder.
    return demo_detector if settings.google_oauth_mock else detect_stack


def get_live_stack_detector() -> LiveDetector:
    # Toujours la vraie detection HTTP : l'ajout d'un domaine par l'utilisateur
    # sonde reellement le site, meme quand la demo tourne en mode mock.
    return detect_stack


def get_tls_checker() -> TlsChecker:
    return check_certificate


TokenCipherDep = Annotated[TokenCipher, Depends(get_token_cipher)]
GoogleClientDep = Annotated[GoogleOAuthClient, Depends(get_google_client)]
AuditProbeDep = Annotated[AuditProbe, Depends(get_audit_probe)]
StackDetectorDep = Annotated[Detector, Depends(get_stack_detector)]
LiveStackDetectorDep = Annotated[LiveDetector, Depends(get_live_stack_detector)]
TlsCheckerDep = Annotated[TlsChecker, Depends(get_tls_checker)]


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
