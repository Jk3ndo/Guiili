"""Nettoyage des valeurs de dimension AVANT stockage : aucune donnée personnelle.

- page : chemin seul (ni domaine, ni requête, ni fragment, ni identifiant de session
  `;jsessionid=`) ; écartée si elle contient une adresse e-mail ou commence par `//` ;
- query (Search Console) : minuscules ; écartée si elle ressemble à un e-mail, un numéro
  de téléphone ou un identifiant (longue suite de chiffres) ;
- event_name (GA4) : uniquement un nom d'événement GA4 valide.

Chaque fonction est idempotente (f(f(x)) == f(x)) : la même valeur ne peut donner qu'une
seule `dim_key`. Elle renvoie None, sans jamais lever d'exception, pour une valeur à
écarter : non-texte, caractère de contrôle (dont NUL), caractère non encodable en UTF-8
(substitut isolé). L'entrée est plafonnée avant toute expression régulière ; on coupe
d'abord, on normalise ensuite, et les filtres personnels sont appliqués sur la valeur
complète (avant la coupe) pour qu'un fragment d'adresse ne survive pas à la troncature."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from urllib.parse import unquote, urlsplit

_MAX_INPUT = 2048
_MAX_PAGE = 200
_MAX_QUERY = 100
# Le lookbehind limite le départ d'un essai au début d'un mot : recherche linéaire.
_EMAIL = re.compile(r"(?<![^\s@/])[^\s@/]+@[^\s@/]+\.[a-z]{2,}", re.IGNORECASE)
_LONG_DIGITS = re.compile(r"\d(?:[\s.\-]?\d){6,}")
_GA4_EVENT = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
_SESSION_ID = re.compile(r";jsessionid=[^/;?#]*", re.IGNORECASE)
_QUERY_START = re.compile(r"[?#]")


def _has_control(value: str, *, keep_whitespace: bool) -> bool:
    return any(
        unicodedata.category(char) == "Cc" and not (keep_whitespace and char.isspace())
        for char in value
    )


def _prepare(raw: object, *, keep_whitespace: bool) -> str | None:
    """Plafonne, vérifie l'encodage, normalise en NFC et retire les blancs de bord."""
    if not isinstance(raw, str):
        return None
    value = raw[:_MAX_INPUT]
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    value = unicodedata.normalize("NFC", value).strip()
    if _has_control(value, keep_whitespace=keep_whitespace):
        return None
    return value or None


def _cut_path(path: str) -> str:
    if len(path) > _MAX_PAGE:
        path = path[:_MAX_PAGE]
        # Un échappement %XX coupé en deux est retiré en entier.
        cut = path.rfind("%", _MAX_PAGE - 2)
        if cut != -1:
            path = path[:cut]
    return path.rstrip()


def clean_page(raw: str) -> str | None:
    value = _prepare(raw, keep_whitespace=False)
    if value is None or value.startswith("//"):
        return None
    try:
        path = urlsplit(value).path if "://" in value else _QUERY_START.split(value, 1)[0]
    except ValueError:
        return None
    path = _SESSION_ID.sub("", path)
    path = path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith("//"):
        return None
    decoded = unquote(path)
    if _EMAIL.search(decoded) or _has_control(decoded, keep_whitespace=False):
        return None
    return _cut_path(path)


def clean_query(raw: str) -> str | None:
    value = _prepare(raw, keep_whitespace=True)
    if value is None:
        return None
    value = unicodedata.normalize("NFC", " ".join(value.lower().split()))
    if not value or _EMAIL.search(value) or _LONG_DIGITS.search(value):
        return None
    return value[:_MAX_QUERY].rstrip()


def clean_event(raw: str) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw[:_MAX_INPUT].strip()
    return value if _GA4_EVENT.fullmatch(value) else None


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
