from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.deps import CurrentUserDep, GoogleClientDep, SessionDep, SettingsDep, TokenCipherDep
from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.services.connections import decrypt_refresh_token, upsert_google_connection
from app.services.google_oauth import InvalidGrantError
from app.services.google_oauth.base import GOOGLE_DATA_SCOPES
from app.services.oauth_state import consume_oauth_state, create_oauth_transaction
from app.services.workspaces import require_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


class ConnectionStartResponse(BaseModel):
    authorization_url: str


@router.get("/google/start", response_model=ConnectionStartResponse)
async def connections_google_start(
    workspace_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    client: GoogleClientDep,
) -> ConnectionStartResponse:
    await require_owner(session, workspace_id=workspace_id, user_id=user.id)
    transaction = await create_oauth_transaction(
        session,
        user_id=user.id,
        workspace_id=workspace_id,
        # URL absolue : ce callback est appele sur l'origine du BACKEND, un
        # chemin relatif se resoudrait donc contre elle (404) au lieu du
        # frontend — contrairement au login qui ne passe pas de redirect_to
        # et retombe sur `settings.frontend_base_url` (deja absolu).
        redirect_to=f"{settings.frontend_base_url}/connections",
        ttl_seconds=settings.oauth_state_ttl_seconds,
    )
    await session.commit()
    url = client.build_authorization_url(
        state=transaction.state,
        code_challenge=transaction.code_challenge,
        scopes=GOOGLE_DATA_SCOPES,
        # Sans ca, le consentement reviendrait sur le callback de LOGIN
        # (`/auth/google/callback`) : l'utilisateur serait silencieusement
        # reconnecte et aucune connexion de donnees ne serait creee.
        redirect_uri=settings.google_data_redirect_uri,
    )
    return ConnectionStartResponse(authorization_url=url)


@router.get("/google/callback")
async def connections_google_callback(
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
    if consumed.workspace_id is None:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="transaction OAuth invalide pour une connexion de donnees",
        )
    try:
        token = await client.exchange_code(
            code=code,
            code_verifier=consumed.code_verifier,
            # Doit refleter exactement le redirect_uri de l'autorisation.
            redirect_uri=settings.google_data_redirect_uri,
        )
    except InvalidGrantError:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="code d'autorisation invalide"
        ) from None
    if token.refresh_token is None:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google n'a pas fourni de refresh token — reconsentement requis",
        )
    userinfo = await client.fetch_userinfo(access_token=token.access_token)
    await upsert_google_connection(
        session,
        workspace_id=consumed.workspace_id,
        userinfo=userinfo,
        token=token,
        cipher=cipher,
    )
    await session.commit()
    return RedirectResponse(
        url=consumed.redirect_to or settings.frontend_base_url,
        status_code=status.HTTP_302_FOUND,
    )


class DisconnectResponse(BaseModel):
    status: str


@router.delete("/{connection_id}", response_model=DisconnectResponse)
async def disconnect_connection(
    connection_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    client: GoogleClientDep,
    cipher: TokenCipherDep,
) -> DisconnectResponse:
    connection = await session.get(GoogleConnection, connection_id)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="connexion introuvable"
        )
    await require_owner(session, workspace_id=connection.workspace_id, user_id=user.id)
    if connection.status == ConnectionStatus.ACTIVE:
        try:
            refresh_token = decrypt_refresh_token(connection, cipher=cipher)
            await client.revoke(token=refresh_token)
        except Exception:  # best-effort, l'intention locale prime (voir spec)
            # Jamais bloquant, mais jamais silencieux non plus : une revocation
            # qui echoue systematiquement (cle de chiffrement, reseau, API
            # Google) laisserait sinon des refresh tokens vivants cote Google
            # sans aucune trace.
            logger.warning(
                "revocation Google best-effort echouee pour la connexion %s",
                connection.id,
                exc_info=True,
            )
    connection.status = ConnectionStatus.REVOKED
    await session.commit()
    return DisconnectResponse(status="revoked")
