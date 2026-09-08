"""Verification du certificat HTTPS d'un domaine.

`check_certificate` fait le handshake TLS (verifie, puis non-verifie en repli
pour recuperer les dates meme sur un certificat expire / non fiable) ;
`classify_certificate` est pur et testable. Aucun appel reseau si un `probe`
est injecte.
"""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_TIMEOUT = 8.0
_EXPIRING_SOON_DAYS = 30

# valid | expiring_soon | expired | self_signed | hostname_mismatch | untrusted | unreachable
Status = str


@dataclass(frozen=True, slots=True)
class TlsStatus:
    host: str
    status: Status
    checked_at: datetime
    expires_at: datetime | None = None
    days_remaining: int | None = None
    issuer: str | None = None
    error: str | None = None

    @property
    def is_healthy(self) -> bool:
        return self.status == "valid"


@dataclass(frozen=True, slots=True)
class TlsProbe:
    """Resultat brut d'un handshake : le certificat pair + l'erreur de verif."""

    cert: dict[str, Any] | None
    verified: bool
    verify_error: str | None
    transport_error: str | None


ProbeFn = Callable[[str, int, float], Awaitable[TlsProbe]]


def _parse_cert_time(value: str) -> datetime | None:
    # Format OpenSSL : "Aug 30 11:40:21 2026 GMT"
    try:
        return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _issuer_cn(cert: dict[str, Any]) -> str | None:
    for rdn in cert.get("issuer", ()):
        for key, val in rdn:
            if key in ("organizationName", "commonName"):
                return str(val)
    return None


def classify_certificate(host: str, probe: TlsProbe, *, now: datetime | None = None) -> TlsStatus:
    moment = now or datetime.now(UTC)
    base = {"host": host, "checked_at": moment}

    if probe.cert is None and probe.transport_error is not None:
        return TlsStatus(**base, status="unreachable", error=probe.transport_error)

    expires_at = _parse_cert_time(probe.cert.get("notAfter", "")) if probe.cert else None
    issuer = _issuer_cn(probe.cert) if probe.cert else None
    days = (expires_at - moment).days if expires_at is not None else None

    common = {**base, "expires_at": expires_at, "days_remaining": days, "issuer": issuer}

    if days is not None and days < 0:
        return TlsStatus(**common, status="expired", error=probe.verify_error)

    if not probe.verified:
        reason = (probe.verify_error or "").lower()
        if "hostname mismatch" in reason or "doesn't match" in reason:
            status = "hostname_mismatch"
        elif "self-signed" in reason or "self signed" in reason:
            status = "self_signed"
        elif "expired" in reason:
            status = "expired"
        else:
            status = "untrusted"
        return TlsStatus(**common, status=status, error=probe.verify_error)

    if days is not None and days <= _EXPIRING_SOON_DAYS:
        return TlsStatus(**common, status="expiring_soon")

    return TlsStatus(**common, status="valid")


async def _default_probe(host: str, port: int, timeout: float) -> TlsProbe:
    async def _handshake(context: ssl.SSLContext) -> dict[str, Any] | None:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host),
            timeout=timeout,
        )
        try:
            ssl_object = writer.get_extra_info("ssl_object")
            return ssl_object.getpeercert() if ssl_object is not None else None
        finally:
            writer.close()
            with contextlib.suppress(ssl.SSLError, OSError):
                await writer.wait_closed()

    verified_ctx = ssl.create_default_context()
    try:
        cert = await _handshake(verified_ctx)
        return TlsProbe(cert=cert, verified=True, verify_error=None, transport_error=None)
    except ssl.SSLCertVerificationError as exc:
        verify_error = exc.verify_message or str(exc)
    except (TimeoutError, ssl.SSLError, OSError) as exc:
        return TlsProbe(
            cert=None,
            verified=False,
            verify_error=None,
            transport_error=str(exc) or type(exc).__name__,
        )

    # Repli non-verifie : on veut quand meme la date d'expiration.
    permissive = ssl.create_default_context()
    permissive.check_hostname = False
    permissive.verify_mode = ssl.CERT_NONE
    try:
        cert = await _handshake(permissive)
        return TlsProbe(cert=cert, verified=False, verify_error=verify_error, transport_error=None)
    except (TimeoutError, ssl.SSLError, OSError) as exc:
        return TlsProbe(
            cert=None, verified=False, verify_error=verify_error, transport_error=str(exc)
        )


async def check_certificate(
    domain: str,
    *,
    port: int = 443,
    timeout: float = _TIMEOUT,
    now: datetime | None = None,
    probe: ProbeFn | None = None,
) -> TlsStatus:
    host = domain.strip().lower().removeprefix("www.")
    runner = probe or _default_probe
    try:
        result = await runner(host, port, timeout)
    except Exception as exc:  # un check TLS ne doit jamais casser l'audit
        return TlsStatus(
            host=host,
            status="unreachable",
            checked_at=now or datetime.now(UTC),
            error=str(exc) or type(exc).__name__,
        )
    return classify_certificate(host, result, now=now)
