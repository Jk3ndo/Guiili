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
from app.services.advisor.llm import AdvisorLLM, MockAdvisorLLM, RealAdvisorLLM
from app.services.audit_engine import Detector, GtmChecker, TlsChecker
from app.services.audit_probe import AuditProbe, MockAuditProbe, RealAuditProbe
from app.services.email import ConsoleEmailSender, EmailSender
from app.services.google_oauth import GoogleOAuthClient, get_google_oauth_client
from app.services.gtm_check import check_gtm
from app.services.gtm_headless import GtmHeadlessVerifier, verify_gtm
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


def get_gtm_checker() -> GtmChecker:
    # Toujours le vrai check : il n'est cable que sur les vraies routes
    # (create/scan d'un site reel) ; le seed de demo ne le passe jamais.
    # `check_gtm` ne leve jamais et degrade proprement si le site est injoignable.
    return check_gtm


def get_gtm_headless_verifier() -> GtmHeadlessVerifier:
    # Jamais gate sur un flag mock : c'est une action explicite (bouton /
    # outil agent), jamais declenchee automatiquement par un scan. Les tests
    # overrident cette dependance pour ne jamais lancer de vrai navigateur.
    return verify_gtm


def get_advisor_llm(settings: SettingsDep) -> AdvisorLLM:
    key = settings.anthropic_api_key.get_secret_value()
    if settings.advisor_mock or not key:
        return MockAdvisorLLM()
    return RealAdvisorLLM(
        api_key=key,
        brief_model=settings.advisor_brief_model,
        chat_model=settings.advisor_chat_model,
    )


def get_email_sender(settings: SettingsDep) -> EmailSender:
    # Aucun fournisseur reel configure pour l'instant (choix differe, voir spec §6/§9).
    # Meme garde-fou que le flag `secure` du cookie de session (auth.py) : ne
    # jamais laisser tourner le ConsoleEmailSender (qui logge les tokens de
    # reset/invitation en clair) hors dev local.
    if settings.environment == "local":
        return ConsoleEmailSender()
    raise RuntimeError(
        "Aucun fournisseur d'email reel configure — RealEmailSender n'est pas "
        "implemente dans cet increment (voir spec §6/§9)."
    )


TokenCipherDep = Annotated[TokenCipher, Depends(get_token_cipher)]
GoogleClientDep = Annotated[GoogleOAuthClient, Depends(get_google_client)]
AuditProbeDep = Annotated[AuditProbe, Depends(get_audit_probe)]
StackDetectorDep = Annotated[Detector, Depends(get_stack_detector)]
LiveStackDetectorDep = Annotated[LiveDetector, Depends(get_live_stack_detector)]
TlsCheckerDep = Annotated[TlsChecker, Depends(get_tls_checker)]
GtmCheckerDep = Annotated[GtmChecker, Depends(get_gtm_checker)]
GtmHeadlessVerifierDep = Annotated[GtmHeadlessVerifier, Depends(get_gtm_headless_verifier)]
AdvisorLLMDep = Annotated[AdvisorLLM, Depends(get_advisor_llm)]
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]


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
