"""Files de tâches.

- `TaskQueue` : contrat commun ; `enqueue` lève `EnqueueError` si la tâche n'a pas pu
  être déposée (un doublon déjà présent n'est pas une erreur).
- `InlineQueue` : développement et tests. Exécute la tâche immédiatement dans le
  processus : aucun réseau, aucune nouvelle tentative, aucune limite de débit.
- `CloudTasksQueue` (production) : `app/services/jobs/cloud_tasks.py`."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from app.services.jobs.kinds import QueueName, RunSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TaskMessage:
    spec: RunSpec
    queue: QueueName


class EnqueueError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TaskQueue(Protocol):
    async def enqueue(self, message: TaskMessage) -> None: ...


class InlineQueue:
    def __init__(self, execute: Callable[[RunSpec], Awaitable[object]]) -> None:
        self._execute = execute
        self.executed: list[str] = []
        # Types des exceptions levées par les tâches : un test ne doit pas passer sur un
        # exécuteur qui plante.
        self.failed: list[str] = []

    async def enqueue(self, message: TaskMessage) -> None:
        self.executed.append(message.spec.key)
        try:
            await self._execute(message.spec)
        except Exception as exc:  # une tâche en échec ne casse pas le passage du planificateur
            # Type seul : le message d'une exception peut embarquer une URL ou un jeton.
            self.failed.append(type(exc).__name__)
            logger.error(
                "tâche exécutée en ligne en échec",
                extra={
                    "event": "job_inline_failed",
                    "job_key": message.spec.key,
                    "error_type": type(exc).__name__,
                },
            )
