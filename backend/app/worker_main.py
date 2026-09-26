"""Service `worker` : même code que l'API, autre point d'entrée.

Porte uniquement les routes internes (`/internal/*`, OIDC) et les sondes de santé.
Tourne dans l'image avec Chromium (`Dockerfile.worker`) ; l'API publique (`app.main`)
n'expose aucune de ces routes. Hors `local`, refuse de démarrer si la configuration du
worker est incomplète (`worker_problems`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.internal import router as internal_router
from app.config import Settings, get_settings, worker_problems
from app.db.session import engine, get_session
from app.logging_config import RequestContextMiddleware, configure_logging
from app.observability import init_sentry
from app.security.oidc import OidcVerifier


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """422 sans écho de la charge utile : seulement l'emplacement et le message de chaque
    erreur (jamais `input` ni `ctx`, qui reprendraient les valeurs reçues)."""
    detail = [
        {"loc": [str(part) for part in error["loc"]], "msg": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


def create_worker_app(
    settings: Settings | None = None, *, oidc_verifier: OidcVerifier | None = None
) -> FastAPI:
    settings = settings or get_settings()
    problems = worker_problems(settings)
    if problems:
        raise RuntimeError("Configuration du worker invalide : " + " ; ".join(problems))
    configure_logging(settings)
    init_sentry(settings)
    application = FastAPI(
        title="Guiili worker",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = settings
    if oidc_verifier is None and settings.internal_oidc_audience:
        oidc_verifier = OidcVerifier(
            audience=settings.internal_oidc_audience,
            allowed_emails=settings.internal_allowed_invokers,
        )
    application.state.oidc_verifier = oidc_verifier
    application.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    application.add_middleware(RequestContextMiddleware)
    application.include_router(internal_router, prefix="/internal")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/db", response_model=None)
    async def health_db(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, str] | JSONResponse:
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"database": "error"})
        return {"database": "ok"}

    return application


app = create_worker_app()
