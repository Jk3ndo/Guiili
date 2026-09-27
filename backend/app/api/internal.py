"""Routes internes du service worker. Jamais montées dans l'API publique (`app.main`),
jamais dans le schéma OpenAPI, toutes protégées par `require_internal_caller`."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, Self
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.api.internal_auth import require_internal_caller
from app.config import Settings
from app.models.website import Website
from app.services.gcp_metadata import MetadataTokenProvider
from app.services.gtm_headless import GtmHeadlessVerifier, headless_result_to_dict, verify_gtm
from app.services.jobs.cloud_tasks import CloudTasksQueue
from app.services.jobs.handlers import JobServices, build_handlers
from app.services.jobs.health import compute_jobs_health
from app.services.jobs.kinds import BACKFILL_SOURCES, KINDS, RunSpec
from app.services.jobs.queue import InlineQueue, TaskQueue
from app.services.jobs.runner import JobLimits, RunResult, execute_run
from app.services.jobs.scheduler import tick
from app.services.metrics.types import utc_now

logger = logging.getLogger(__name__)

# `GET /internal/jobs/health` ne renvoie que les plus anciens échecs (le total reste dans
# `failing_total`) : seule la RÉPONSE est bornée (`compute_jobs_health` lit toutes les
# lignes concernées).
HEALTH_FAILING_LIMIT = 100
# Vérification headless : borne globale d'une vérification (lancement du navigateur,
# navigation et évaluations comprises) et attente maximale du créneau. Au-delà, 503 : un
# site client qui boucle ne doit jamais geler la vérification de l'instance.
HEADLESS_TIMEOUT_SECONDS = 60.0
HEADLESS_SLOT_WAIT_SECONDS = 5.0
RETRY_AFTER_SECONDS = "60"

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_internal_caller)])

_WINDOW = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
# Un seul navigateur à la fois par instance du worker (file « lourde »).
_HEADLESS_SLOT = asyncio.Semaphore(1)
_METADATA_TOKENS = MetadataTokenProvider()


def get_worker_settings(request: Request) -> Settings:
    return request.app.state.settings


WorkerSettingsDep = Annotated[Settings, Depends(get_worker_settings)]


def get_job_limits(settings: WorkerSettingsDep) -> JobLimits:
    return JobLimits.from_settings(settings)


def get_job_services(request: Request) -> JobServices:
    """Services construits une seule fois au démarrage (`create_worker_app`) : une clé de
    chiffrement invalide fait échouer le démarrage, pas chaque requête."""
    return request.app.state.job_services


JobLimitsDep = Annotated[JobLimits, Depends(get_job_limits)]
JobServicesDep = Annotated[JobServices, Depends(get_job_services)]


def get_task_queue(
    settings: WorkerSettingsDep,
    session: SessionDep,
    services: JobServicesDep,
    limits: JobLimitsDep,
) -> TaskQueue:
    if settings.task_queue_backend == "cloud_tasks":
        return CloudTasksQueue(
            project=settings.gcp_project,
            location=settings.cloud_tasks_location,
            queue_prefix=settings.cloud_tasks_queue_prefix,
            target_url=f"{settings.worker_base_url.rstrip('/')}/internal/tasks/run",
            invoker_email=settings.tasks_invoker_service_account,
            audience=settings.internal_oidc_audience,
            tokens=_METADATA_TOKENS,
        )
    handlers = build_handlers(services)

    async def execute(spec: RunSpec) -> RunResult:
        return await execute_run(session, spec, handlers=handlers, limits=limits)

    return InlineQueue(execute)


def get_headless_runner() -> GtmHeadlessVerifier:
    return verify_gtm


TaskQueueDep = Annotated[TaskQueue, Depends(get_task_queue)]
HeadlessRunnerDep = Annotated[GtmHeadlessVerifier, Depends(get_headless_runner)]


class TickOut(BaseModel):
    materialized: int
    enqueued: int
    capped: int
    failed_enqueue: int
    expired_queued: int


class RunTaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    website_id: UUID | None = None
    workspace_id: UUID | None = None
    window: str
    params: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        kind = KINDS.get(self.kind)
        if kind is None:
            raise ValueError("type de tâche inconnu")
        if not _WINDOW.match(self.window):
            raise ValueError("fenêtre invalide")
        has_site = self.website_id is not None and self.workspace_id is not None
        if kind.per_site and not has_site:
            raise ValueError("site et workspace obligatoires pour ce type de tâche")
        if not kind.per_site and (self.website_id is not None or self.workspace_id is not None):
            raise ValueError("tâche globale : ni site ni workspace")
        allowed = {"source"} if self.kind == "backfill" else set()
        if set(self.params) - allowed:
            raise ValueError("paramètres non autorisés pour ce type de tâche")
        if self.kind == "backfill" and self.params.get("source") not in BACKFILL_SOURCES:
            raise ValueError("source de rattrapage invalide (ga4 ou gsc)")
        return self

    def to_spec(self) -> RunSpec:
        return RunSpec(self.kind, self.website_id, self.workspace_id, self.window, dict(self.params))


class RunTaskOut(BaseModel):
    claim: str
    status: str | None


class FailingOut(BaseModel):
    website_id: UUID | None
    kind: str
    failing_since: datetime
    error_code: str | None
    client_action: bool


class JobsHealthOut(BaseModel):
    ok: bool
    checked_at: datetime
    failing: list[FailingOut]
    failing_total: int
    overdue: int
    stuck_running: int
    stuck_queued: int
    maintenance_stale: bool


class HeadlessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str

    @field_validator("url")
    @classmethod
    def _https_site(cls, value: str) -> str:
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError:
            raise ValueError("URL https d'un site attendue") from None
        # Même cible que l'audit public : `https://{domaine}` exactement (pas de chemin,
        # de requête ni de fragment).
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or port not in (None, 443)
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError("URL https d'un site attendue")
        return value


@router.post("/tick", response_model=TickOut)
async def tick_endpoint(
    session: SessionDep,
    settings: WorkerSettingsDep,
    queue: TaskQueueDep,
    limits: JobLimitsDep,
) -> TickOut:
    try:
        result = await tick(
            session,
            queue,
            now=utc_now(),
            batch=settings.jobs_tick_batch,
            daily_cap=settings.jobs_workspace_daily_cap,
            max_attempts=limits.max_attempts,
        )
    except Exception as exc:
        # Cloud Scheduler doit voir l'échec (statut 503, il retentera au passage suivant) ;
        # on ne journalise que le type : le message peut embarquer une URL ou un identifiant.
        await session.rollback()
        logger.error(
            "passage du planificateur en échec",
            extra={"event": "tick_failed", "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="passage en échec"
        ) from None
    return TickOut(**asdict(result))


@router.post("/tasks/run", response_model=RunTaskOut)
async def run_task(
    body: RunTaskIn,
    response: Response,
    session: SessionDep,
    services: JobServicesDep,
    limits: JobLimitsDep,
) -> RunTaskOut:
    spec = body.to_spec()
    try:
        if spec.website_id is not None:
            website = await session.get(Website, spec.website_id)
            if website is None:
                # Site supprimé entre le dépôt et l'exécution : rien à faire, pas de reprise.
                await session.commit()
                return RunTaskOut(claim="gone", status=None)
            if website.workspace_id != spec.workspace_id:
                raise HTTPException(status_code=422, detail="workspace incohérent avec le site")
        result = await execute_run(session, spec, handlers=build_handlers(services), limits=limits)
    except HTTPException:
        raise
    except Exception as exc:
        # Erreur inattendue (base, réclamation…) : la file doit réessayer, sans trace ni
        # message dans les journaux (le message peut embarquer une URL ou un identifiant).
        await session.rollback()
        logger.error(
            "exécution de tâche en échec",
            extra={"event": "task_run_failed", "job_kind": spec.kind,
                   "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="exécution en échec",
            headers={"Retry-After": RETRY_AFTER_SECONDS},
        ) from None
    if result.retry:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        response.headers["Retry-After"] = RETRY_AFTER_SECONDS
    return RunTaskOut(claim=result.claim, status=result.status)


@router.get("/jobs/health", response_model=JobsHealthOut)
async def jobs_health(session: SessionDep) -> JobsHealthOut:
    health = await compute_jobs_health(session, now=utc_now())
    return JobsHealthOut(
        ok=health.ok,
        checked_at=health.checked_at,
        failing=[FailingOut(**asdict(item)) for item in health.failing[:HEALTH_FAILING_LIMIT]],
        failing_total=len(health.failing),
        overdue=health.overdue,
        stuck_running=health.stuck_running,
        stuck_queued=health.stuck_queued,
        maintenance_stale=health.maintenance_stale,
    )


@router.post("/headless/verify")
async def headless_verify(
    body: HeadlessIn, session: SessionDep, verifier: HeadlessRunnerDep
) -> dict[str, Any]:
    host = (urlsplit(body.url).hostname or "").lower()
    known = await session.scalar(
        select(func.count()).select_from(Website).where(func.lower(Website.domain) == host)
    )
    # Fin de la transaction de lecture (commit, pas rollback : rien n'est écrit, et un
    # rollback annulerait aussi le SAVEPOINT des tests) : aucune connexion n'est tenue
    # pendant le navigateur.
    await session.commit()
    if not known:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site inconnu")
    try:
        await asyncio.wait_for(_HEADLESS_SLOT.acquire(), HEADLESS_SLOT_WAIT_SECONDS)
    except TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="vérification headless occupée",
            headers={"Retry-After": RETRY_AFTER_SECONDS},
        ) from None
    try:
        # L'annulation par `wait_for` se propage jusqu'au `finally` de `verify_gtm`, qui
        # ferme le navigateur ; le créneau est libéré dans tous les cas.
        result = await asyncio.wait_for(verifier(body.url), HEADLESS_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("vérification headless trop longue", extra={"event": "headless_timeout"})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="vérification headless trop longue",
            headers={"Retry-After": RETRY_AFTER_SECONDS},
        ) from None
    finally:
        _HEADLESS_SLOT.release()
    return headless_result_to_dict(result)
