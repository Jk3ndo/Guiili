"""Dépendance des routes internes : jeton OIDC Google obligatoire (Cloud Scheduler,
Cloud Tasks ou compte de service de l'API). Le vérificateur est porté par
l'application worker (`app.state.oidc_verifier`)."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status

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
