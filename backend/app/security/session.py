"""Cookie de session signe HMAC-SHA256.

Format : ``<payload_b64url>.<sig_b64url>`` ou ``payload = "<user_id>:<issued_at>"``.
La signature couvre le payload complet ; toute alteration invalide le cookie.
Aucune donnee sensible n'est stockee cote client — seulement l'UUID utilisateur.
"""

from __future__ import annotations

import base64
import hmac
import time
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

_SEP = "."
_MAX_AGE = int(timedelta(days=30).total_seconds())


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(payload: str, secret: bytes) -> str:
    mac = hmac.new(secret, payload.encode("utf-8"), sha256).digest()
    return _b64e(mac)


def issue_session(user_id: UUID, *, secret: str) -> str:
    payload = f"{user_id}:{int(time.time())}"
    payload_b64 = _b64e(payload.encode("utf-8"))
    return payload_b64 + _SEP + _sign(payload_b64, secret.encode("utf-8"))


def read_session(cookie: str | None, *, secret: str, max_age: int = _MAX_AGE) -> UUID | None:
    if not cookie or cookie.count(_SEP) != 1:
        return None
    payload_b64, sig = cookie.split(_SEP)
    expected = _sign(payload_b64, secret.encode("utf-8"))
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        user_raw, issued_raw = _b64d(payload_b64).decode("utf-8").split(":", 1)
        issued_at = int(issued_raw)
        user_id = UUID(user_raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if issued_at + max_age < int(time.time()):
        return None
    return user_id
