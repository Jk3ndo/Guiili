"""Dépendance des routes internes : jeton OIDC Google obligatoire (Cloud Scheduler,
Cloud Tasks ou compte de service de l'API). Le vérificateur est porté par
l'application worker (`app.state.oidc_verifier`)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.security.oidc import OidcError, OidcIdentity, OidcVerifier

logger = logging.getLogger(__name__)


async def require_internal_caller(request: Request) -> OidcIdentity:
    verifier: OidcVerifier | None = getattr(request.app.state, "oidc_verifier", None)
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentification interne non configurée",
        )
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="jeton d'appel interne requis"
        )
    try:
        return await verifier.verify(header[7:].strip())
    except OidcError as exc:
        logger.warning("appel interne refusé", extra={"event": "internal_denied", "reason": exc.reason})
        if exc.reason == "caller_not_allowed":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="appelant interne non autorisé"
            ) from None
        if exc.reason in ("not_configured", "jwks_unavailable"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="authentification interne indisponible",
            ) from None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="jeton d'appel interne invalide"
        ) from None


def _route_caller(role: str) -> Callable[..., Awaitable[OidcIdentity]]:
    """Restriction propre à une route, en plus de la liste globale. Liste vide = aucune
    restriction supplémentaire. Le jeton n'est vérifié qu'une fois : FastAPI met en cache
    le résultat de `require_internal_caller`, déjà dépendance du routeur."""

    async def check(
        request: Request, identity: Annotated[OidcIdentity, Depends(require_internal_caller)]
    ) -> OidcIdentity:
        allowed = request.app.state.route_invokers.get(role)
        if allowed and identity.email not in allowed:
            logger.warning(
                "appel interne refusé pour cette route",
                extra={
                    "event": "internal_denied",
                    "reason": "caller_not_allowed_for_route",
                    "route_role": role,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="appelant interne non autorisé"
            )
        return identity

    return check


require_scheduler_caller = _route_caller("scheduler")
require_tasks_caller = _route_caller("tasks")
require_headless_caller = _route_caller("headless")
