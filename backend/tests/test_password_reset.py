import secrets
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User


async def test_reset_request_always_returns_200(db_client: AsyncClient) -> None:
    resp = await db_client.post("/api/v1/auth/password-reset/request", json={"email": "unknown@example.com"})
    assert resp.status_code == 200  # ne revele pas si le compte existe


async def test_reset_confirm_updates_password(db_client: AsyncClient, db_session) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "reset@example.com", "password": "old password here", "display_name": "R"},
    )
    await db_client.post("/api/v1/auth/password-reset/request", json={"email": "reset@example.com"})
    token_row = (
        await db_session.execute(
            select(PasswordResetToken).order_by(PasswordResetToken.created_at.desc())
        )
    ).scalars().first()

    resp = await db_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token_row.token, "new_password": "new password here"},
    )
    assert resp.status_code == 200

    db_client.cookies.clear()
    login = await db_client.post(
        "/api/v1/auth/login", json={"email": "reset@example.com", "password": "new password here"}
    )
    assert login.status_code == 200


async def test_reset_confirm_rejects_expired_token(db_client: AsyncClient, db_session) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "expired@example.com", "password": "old password here", "display_name": "E"},
    )
    user = (
        await db_session.execute(select(User).where(User.email == "expired@example.com"))
    ).scalar_one()
    db_session.add(
        PasswordResetToken(
            user_id=user.id, token=secrets.token_urlsafe(32),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.flush()
    token_row = (
        await db_session.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )
    ).scalars().first()

    resp = await db_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token_row.token, "new_password": "new password here"},
    )
    assert resp.status_code == 400


async def test_reset_confirm_rejects_reused_token(db_client: AsyncClient, db_session) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "reused@example.com", "password": "old password here", "display_name": "U"},
    )
    await db_client.post("/api/v1/auth/password-reset/request", json={"email": "reused@example.com"})
    token_row = (
        await db_session.execute(
            select(PasswordResetToken).order_by(PasswordResetToken.created_at.desc())
        )
    ).scalars().first()
    await db_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token_row.token, "new_password": "new password here"},
    )
    resp = await db_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token_row.token, "new_password": "yet another one"},
    )
    assert resp.status_code == 400
