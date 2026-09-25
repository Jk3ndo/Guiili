from __future__ import annotations

from fastapi import Depends, Request

from app.api.deps import CurrentUserDep, SettingsDep
from app.security.rate_limit import client_ip, enforce


def limit_by_ip(name: str, *, limit: int, window: float):
    async def _dependency(request: Request, settings: SettingsDep) -> None:
        enforce(
            f"{name}:ip:{client_ip(request)}",
            limit=limit,
            window=window,
            enabled=settings.rate_limit_enabled,
        )

    return Depends(_dependency)


def limit_by_user(name: str, *, limit: int, window: float):
    async def _dependency(user: CurrentUserDep, settings: SettingsDep) -> None:
        enforce(
            f"{name}:user:{user.id}",
            limit=limit,
            window=window,
            enabled=settings.rate_limit_enabled,
        )

    return Depends(_dependency)
