"""Limiteur à fenêtre glissante, en mémoire, par instance.

Choix assumé : pas de dépendance externe. Avec plusieurs instances Cloud Run la limite
effective est multipliée par leur nombre ; elle suffit contre la force brute et les
boucles clientes. `X-Forwarded-For` est pris tel quel (meilleur effort : derrière le
proxy Vercel, le premier maillon est l'IP annoncée du client et peut être forgé) ; la
clé « e-mail » sur les routes d'authentification est le frein fiable.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol

from fastapi import HTTPException, status


class _RequestLike(Protocol):
    headers: dict[str, str]
    client: object | None


class SlidingWindowLimiter:
    def __init__(
        self, *, clock: Callable[[], float] = time.monotonic, max_keys: int = 50_000
    ) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._max_window = 0.0
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, hits: deque[float], now: float, window: float) -> None:
        cutoff = now - window
        while hits and hits[0] <= cutoff:
            hits.popleft()

    def retry_after(self, key: str, *, limit: int, window: float) -> float:
        """Secondes avant qu'une requête soit permise (0.0 si permise), sans rien noter."""
        hits = self._hits.get(key)
        if not hits:
            return 0.0
        now = self._clock()
        self._prune(hits, now, window)
        if len(hits) < limit:
            return 0.0
        return max(hits[0] + window - now, 0.001)

    def record(self, key: str) -> None:
        self._hits.setdefault(key, deque()).append(self._clock())
        self._collect_garbage()

    def check(self, key: str, *, limit: int, window: float) -> float:
        """Note la requête si elle est permise ; sinon renvoie le délai d'attente."""
        self._max_window = max(self._max_window, window)
        wait = self.retry_after(key, limit=limit, window=window)
        if wait == 0.0:
            self.record(key)
        return wait

    def _collect_garbage(self) -> None:
        if len(self._hits) <= self._max_keys:
            return
        cutoff = self._clock() - self._max_window
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]
        if len(self._hits) > self._max_keys:
            # Saturation (attaque par clés distinctes) : on repart de zéro plutôt que de
            # croître sans borne ; la limite se rétablit aussitôt.
            self._hits.clear()

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindowLimiter()


def _too_many(wait: float) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="trop de tentatives, réessaie dans quelques instants",
        headers={"Retry-After": str(max(1, math.ceil(wait)))},
    )


def enforce(key: str, *, limit: int, window: float, enabled: bool = True) -> None:
    """Note et contrôle : lève 429 si la limite est atteinte."""
    if not enabled:
        return
    wait = limiter.check(key, limit=limit, window=window)
    if wait > 0:
        raise _too_many(wait)


def enforce_not_blocked(key: str, *, limit: int, window: float, enabled: bool = True) -> None:
    """Contrôle sans noter (l'appelant note lui-même les seuls échecs)."""
    if not enabled:
        return
    wait = limiter.retry_after(key, limit=limit, window=window)
    if wait > 0:
        raise _too_many(wait)


def client_ip(request: _RequestLike) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    host = getattr(request.client, "host", None)
    return host or "unknown"
