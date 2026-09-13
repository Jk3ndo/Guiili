from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.security.token_crypto import EncryptedToken, TokenCipher
from app.services.google_oauth.base import GoogleTokenResponse, GoogleUserInfo


def connection_aad(workspace_id: UUID, google_sub: str) -> bytes:
    """AAD stricte : lie le blob chiffre au couple (workspace, identite Google).

    Deplacer une ligne `refresh_token_encrypted` vers un autre workspace_id ou
    un autre google_sub fait echouer le dechiffrement (`TokenDecryptionError`).
    """
    return f"gconn|user:{workspace_id}|sub:{google_sub}".encode()


async def upsert_google_connection(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    userinfo: GoogleUserInfo,
    token: GoogleTokenResponse,
    cipher: TokenCipher,
) -> GoogleConnection:
    if token.refresh_token is None:
        raise ValueError("upsert_google_connection appele sans refresh_token")

    aad = connection_aad(workspace_id, userinfo.sub)
    encrypted = cipher.encrypt(token.refresh_token, aad=aad)
    blob = encrypted.pack()
    now = datetime.now(UTC)

    existing = (
        await session.execute(
            select(GoogleConnection).where(
                GoogleConnection.workspace_id == workspace_id,
                GoogleConnection.google_sub == userinfo.sub,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        connection = GoogleConnection(
            workspace_id=workspace_id,
            google_account_email=userinfo.email,
            google_sub=userinfo.sub,
            granted_scopes=list(token.scopes),
            refresh_token_encrypted=blob,
            encryption_key_version=encrypted.key_version,
            status=ConnectionStatus.ACTIVE,
            last_refreshed_at=now,
        )
        session.add(connection)
        await session.flush()
        return connection

    existing.google_account_email = userinfo.email
    existing.granted_scopes = list(token.scopes)
    existing.refresh_token_encrypted = blob
    existing.encryption_key_version = encrypted.key_version
    existing.status = ConnectionStatus.ACTIVE
    existing.last_refreshed_at = now
    await session.flush()
    return existing


def decrypt_refresh_token(connection: GoogleConnection, *, cipher: TokenCipher) -> str:
    aad = connection_aad(connection.workspace_id, connection.google_sub)
    return cipher.decrypt(EncryptedToken.unpack(connection.refresh_token_encrypted), aad=aad)
