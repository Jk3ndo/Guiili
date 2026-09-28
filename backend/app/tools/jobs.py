"""Un passage du planificateur en local, sans Cloud Tasks ni OIDC (développement) :

    cd backend && .venv/Scripts/python.exe -m app.tools.jobs tick

Les tâches dues sont exécutées dans le processus (`InlineQueue`) avec les vraies
sources (réseau). Refusé hors `ENVIRONMENT=local`."""

from __future__ import annotations

import asyncio
import sys

from app.config import Settings, get_settings
from app.db.session import AsyncSessionLocal, engine
from app.services.jobs.handlers import build_handlers, default_job_services
from app.services.jobs.kinds import RunSpec
from app.services.jobs.queue import InlineQueue
from app.services.jobs.runner import JobLimits, RunResult, execute_run
from app.services.jobs.scheduler import TickResult, tick
from app.services.metrics.types import utc_now

_USAGE = "usage: python -m app.tools.jobs tick"


async def _run_tick(settings: Settings) -> TickResult:
    limits = JobLimits.from_settings(settings)
    handlers = build_handlers(default_job_services(settings))
    try:
        async with AsyncSessionLocal() as session:

            async def execute(spec: RunSpec) -> RunResult:
                return await execute_run(session, spec, handlers=handlers, limits=limits)

            return await tick(
                session,
                InlineQueue(execute),
                now=utc_now(),
                batch=settings.jobs_tick_batch,
                daily_cap=settings.jobs_workspace_daily_cap,
                max_attempts=limits.max_attempts,
            )
    finally:
        await engine.dispose()


def main(argv: list[str], *, settings: Settings | None = None) -> int:
    if argv[1:] != ["tick"]:
        print(_USAGE, file=sys.stderr)
        return 2
    settings = settings or get_settings()
    if settings.environment != "local":
        print("outil réservé au développement local (ENVIRONMENT=local)", file=sys.stderr)
        return 2
    result = asyncio.run(_run_tick(settings))
    print(
        f"tick : {result.enqueued} tâche(s) exécutée(s), {result.materialized} planning(s) créé(s), "
        f"{result.capped} retenue(s) par la limite quotidienne, {result.failed_enqueue} échec(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
