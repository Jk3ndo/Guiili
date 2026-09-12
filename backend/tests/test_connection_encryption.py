"""Le refresh token est chiffre au repos, AAD strictement liee a l'identite."""

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.google_connection import GoogleConnection
from app.security.token_crypto import (
    EncryptedToken,
    TokenCipher,
    TokenDecryptionError,
)
from app.services.connections import (
    connection_aad,
    decrypt_refresh_token,
    upsert_google_connection,
)
from app.services.google_oauth.base import GoogleTokenResponse, GoogleUserInfo
from tests.conftest import UserFactory, owner_workspace_id

_KEY = os.urandom(32)


def _cipher() -> TokenCipher:
    return TokenCipher(keys={1: _KEY}, active_version=1)


def _token(refresh: str = "1//real-looking-refresh") -> GoogleTokenResponse:
    return GoogleTokenResponse(
        access_token="at",
        refresh_token=refresh,
        expires_in=3599,
        scopes=("openid", "email"),
    )


def _userinfo(sub: str = "sub-abc") -> GoogleUserInfo:
    return GoogleUserInfo(sub=sub, email=f"{sub}@example.com")


async def test_refresh_token_stored_encrypted(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="enc-user")
    cipher = _cipher()
    conn = await upsert_google_connection(
        db_session,
        workspace_id=await owner_workspace_id(db_session, user),
        userinfo=_userinfo("g-1"),
        token=_token("1//SECRET"),
        cipher=cipher,
    )
    assert b"SECRET" not in conn.refresh_token_encrypted
    assert conn.refresh_token_encrypted[:2] == b"\x00\x01"  # version 1 en-tete
    assert decrypt_refresh_token(conn, cipher=cipher) == "1//SECRET"


async def test_aad_bound_to_user_and_sub(db_session: AsyncSession, make_user: UserFactory) -> None:
    user = await make_user(sub="aad-user")
    workspace_id = await owner_workspace_id(db_session, user)
    cipher = _cipher()
    conn = await upsert_google_connection(
        db_session,
        workspace_id=workspace_id,
        userinfo=_userinfo("g-aad"),
        token=_token("1//AAD"),
        cipher=cipher,
    )
    blob = conn.refresh_token_encrypted

    # bon AAD -> ok
    good = connection_aad(workspace_id, "g-aad")
    assert cipher.decrypt(EncryptedToken.unpack(blob), aad=good) == "1//AAD"

    # AAD d'un autre sub -> echec
    with pytest.raises(TokenDecryptionError):
        cipher.decrypt(EncryptedToken.unpack(blob), aad=connection_aad(workspace_id, "autre-sub"))
    # AAD d'un autre workspace -> echec
    other_user = await make_user(sub="aad-user-2")
    other_workspace_id = await owner_workspace_id(db_session, other_user)
    with pytest.raises(TokenDecryptionError):
        cipher.decrypt(
            EncryptedToken.unpack(blob),
            aad=connection_aad(other_workspace_id, "g-aad"),
        )


async def test_moving_blob_between_rows_fails_to_decrypt(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user_a = await make_user(sub="mv-a")
    user_b = await make_user(sub="mv-b")
    cipher = _cipher()

    conn_a = await upsert_google_connection(
        db_session,
        workspace_id=await owner_workspace_id(db_session, user_a),
        userinfo=_userinfo("g-mv-a"),
        token=_token("1//A"),
        cipher=cipher,
    )
    conn_b = await upsert_google_connection(
        db_session,
        workspace_id=await owner_workspace_id(db_session, user_b),
        userinfo=_userinfo("g-mv-b"),
        token=_token("1//B"),
        cipher=cipher,
    )

    # on copie le blob de A dans la ligne de B et on tente de le lire comme B
    conn_b.refresh_token_encrypted = conn_a.refresh_token_encrypted
    await db_session.flush()
    stolen = await db_session.get(GoogleConnection, conn_b.id)
    with pytest.raises(TokenDecryptionError):
        decrypt_refresh_token(stolen, cipher=cipher)


async def test_upsert_rejects_missing_refresh_token(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="no-refresh")
    token = GoogleTokenResponse(access_token="at", refresh_token=None, expires_in=1, scopes=())
    with pytest.raises(ValueError, match="refresh_token"):
        await upsert_google_connection(
            db_session,
            workspace_id=await owner_workspace_id(db_session, user),
            userinfo=_userinfo("g-nr"),
            token=token,
            cipher=_cipher(),
        )
