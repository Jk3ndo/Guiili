from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import (
    GoogleClientDep,
    OptionalUserDep,
    SessionDep,
    SettingsDep,
    TokenCipherDep,
)
from app.models.user import User
from app.security.session import issue_session
from app.services.connections import upsert_google_connection
from app.services.google_oauth import InvalidGrantError
from app.services.oauth_state import consume_oauth_state, create_oauth_transaction

router = APIRouter(prefix="/auth/google", tags=["auth"])

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
