from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app.api.deps import (
    CurrentUserDep,
    GoogleClientDep,
    OptionalUserDep,
    SessionDep,
    SettingsDep,
    TokenCipherDep,
)
from app.models.user import User
from app.security.password import hash_password, verify_password
from app.security.session import issue_session
from app.services.connections import upsert_google_connection
from app.services.google_oauth import InvalidGrantError
from app.services.oauth_state import consume_oauth_state, create_oauth_transaction
from app.services.workspaces import create_workspace_for_user

router = APIRouter(prefix="/auth/google", tags=["auth"])
# Routes email + mot de passe (register/login/logout/me) : prefix "/auth" distinct de
# celui du router ci-dessus ("/auth/google", dedie a l'OAuth Google) pour ne pas toucher
# aux routes google_start/google_callback (leur corps est modifie par une tache
# ulterieure). Cable en plus de `router` dans app/api/v1/router.py.
auth_router = APIRouter(prefix="/auth", tags=["auth"])

_SESSION_MAX_AGE = int(timedelta(days=30).total_seconds())


class StartResponse(BaseModel):
    authorization_url: str


@router.get("/start", response_model=StartResponse)
async def google_start(
    session: SessionDep,
    settings: SettingsDep,
    client: GoogleClientDep,
    current_user: OptionalUserDep,
    redirect_to: str | None = None,
) -> StartResponse:
    transaction = await create_oauth_transaction(
        session,
        user_id=current_user.id if current_user else None,
        redirect_to=redirect_to,
        ttl_seconds=settings.oauth_state_ttl_seconds,
    )
    await session.commit()
    url = client.build_authorization_url(
        state=transaction.state,
        code_challenge=transaction.code_challenge,
        login_hint=current_user.email if current_user else None,
    )
    return StartResponse(authorization_url=url)


@router.get("/callback")
async def google_callback(
    session: SessionDep,
    settings: SettingsDep,
    client: GoogleClientDep,
    cipher: TokenCipherDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"consentement Google refuse : {error}",
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="code ou state manquant"
        )

    consumed = await consume_oauth_state(session, state)
    if consumed is None:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state OAuth invalide, expire ou deja utilise",
        )

    try:
        token = await client.exchange_code(code=code, code_verifier=consumed.code_verifier)
    except InvalidGrantError:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="code d'autorisation invalide",
        ) from None

    userinfo = await client.fetch_userinfo(access_token=token.access_token)

    if token.refresh_token is None:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google n'a pas fourni de refresh token — reconsentement requis",
        )

    if consumed.user_id is not None:
        user = await session.get(User, consumed.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="utilisateur de session introuvable",
            )
    else:
        user = (
            await session.execute(select(User).where(User.google_sub == userinfo.sub))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email=userinfo.email,
                google_sub=userinfo.sub,
                display_name=userinfo.name,
            )
            session.add(user)
            await session.flush()

    await upsert_google_connection(
        session,
        user_id=user.id,
        userinfo=userinfo,
        token=token,
        cipher=cipher,
    )
    await session.commit()

    response = RedirectResponse(
        url=consumed.redirect_to or settings.frontend_base_url,
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        settings.session_cookie_name,
        issue_session(user.id, secret=settings.app_secret_key.get_secret_value()),
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "local",
    )
    return response


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _set_session_cookie(response: Response, user_id, settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        issue_session(user_id, secret=settings.app_secret_key.get_secret_value()),
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "local",
    )


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    existing = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if existing is not None:
        detail = (
            "ce compte utilise deja Google, connecte-toi avec Google"
            if existing.google_sub is not None
            else "email deja utilise"
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        google_sub=None,
        display_name=body.display_name,
    )
    session.add(user)
    await session.flush()
    await create_workspace_for_user(session, user=user)
    await session.commit()
    _set_session_cookie(response, user.id, settings)


@auth_router.post("/login")
async def login(
    body: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if user is None or user.password_hash is None:
        detail = (
            "ce compte utilise Google, pas de mot de passe"
            if user is not None
            else "email ou mot de passe incorrect"
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email ou mot de passe incorrect")
    _set_session_cookie(response, user.id, settings)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep) -> None:
    response.delete_cookie(settings.session_cookie_name)


class MeOut(BaseModel):
    id: UUID
    email: str
    display_name: str | None


@auth_router.get("/me", response_model=MeOut)
async def me(user: CurrentUserDep) -> MeOut:
    return MeOut(id=user.id, email=user.email, display_name=user.display_name)
