from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.oauth_state import OAuthState
from app.services.pkce import generate_pkce_pair


@dataclass(frozen=True, slots=True)
class OAuthTransaction:
    state: str
    code_challenge: str


@dataclass(frozen=True, slots=True)
class ConsumedOAuthState:
    code_verifier: str
    user_id: UUID | None
    redirect_to: str | None


async def create_oauth_transaction(
    session: AsyncSession,
    *,
    user_id: UUID | None,
    redirect_to: str | None,
    ttl_seconds: int,
) -> OAuthTransaction:
    state = secrets.token_urlsafe(32)
    verifier, challenge = generate_pkce_pair()
    session.add(
        OAuthState(
            state=state,
            code_verifier=verifier,
            user_id=user_id,
            redirect_to=redirect_to,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
    )
    await session.flush()
    return OAuthTransaction(state=state, code_challenge=challenge)


async def consume_oauth_state(session: AsyncSession, state: str) -> ConsumedOAuthState | None:
    """Lit et SUPPRIME la transaction (usage unique). Renvoie ``None`` si absente
    ou expiree — la ligne est quand meme supprimee pour bloquer tout rejeu."""
    row = (
        await session.execute(select(OAuthState).where(OAuthState.state == state))
    ).scalar_one_or_none()
    if row is None:
        return None
    snapshot = ConsumedOAuthState(
        code_verifier=row.code_verifier,
        user_id=row.user_id,
        redirect_to=row.redirect_to,
    )
    expired = row.expires_at < datetime.now(UTC)
    await session.delete(row)
    await session.flush()
    return None if expired else snapshot
