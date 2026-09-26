"""Nettoyage des valeurs de dimension AVANT stockage : aucune donnée personnelle.

- page : chemin seul (ni domaine, ni requête, ni fragment) ; écartée si elle contient
  une adresse e-mail ;
- query (Search Console) : minuscules ; écartée si elle ressemble à un e-mail, un numéro
  de téléphone ou un identifiant (longue suite de chiffres) ;
- event_name (GA4) : uniquement un nom d'événement GA4 valide.
Chaque fonction est idempotente et renvoie None pour une valeur à écarter."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from urllib.parse import unquote, urlsplit

_MAX_PAGE = 200
_MAX_QUERY = 100
_EMAIL = re.compile(r"[^\s@/]+@[^\s@/]+\.[a-z]{2,}", re.IGNORECASE)
_LONG_DIGITS = re.compile(r"\d(?:[\s.\-]?\d){6,}")
_GA4_EVENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def clean_page(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    path = urlsplit(value).path if "://" in value else value.split("?", 1)[0].split("#", 1)[0]
    path = path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if _EMAIL.search(unquote(path)):
        return None
    return path[:_MAX_PAGE]


def clean_query(raw: str) -> str | None:
    value = " ".join(raw.split()).lower()
    if not value or _EMAIL.search(value) or _LONG_DIGITS.search(value):
        return None
    return value[:_MAX_QUERY]


def clean_event(raw: str) -> str | None:
    value = raw.strip()
    return value if _GA4_EVENT.match(value) else None


CLEANERS: dict[str, Callable[[str], str | None]] = {
    "page": clean_page,
    "query": clean_query,
    "event_name": clean_event,
}


def dim_key(dims: Mapping[str, str]) -> str:
    """Empreinte stable des dimensions ("" pour le total) : même entrée, même clé."""
    if not dims:
        return ""
    canonical = json.dumps(sorted(dims.items()), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
