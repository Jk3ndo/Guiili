"""Vérifie un fichier d'environnement de déploiement AVANT de le pousser sur Cloud Run.

    python -m app.tools.check_env deploy/env.production.yaml [--expect production] [--service worker]

`--expect ENV` refuse un fichier dont ENVIRONMENT (défaut `local` s'il est absent) diffère de
la cible du déploiement : sans cela, un fichier sans ENVIRONMENT passe toutes les règles de
production sans qu'aucune ne s'applique.

Le fichier remplace l'ensemble des variables du service : un fichier incomplet ou
dangereux (mock activé, secret court…) doit être refusé ici, pas en production.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import yaml
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.config import Settings, worker_problems
from app.security.token_crypto import TokenCryptoConfigError, load_token_cipher

_JSON_KEYS = {
    "token_enc_keys",
    "cors_origins",
    "internal_allowed_invokers",
    "internal_scheduler_invokers",
    "internal_tasks_invokers",
    "internal_headless_invokers",
}
_JSON_NAMES = ", ".join(sorted(key.upper() for key in _JSON_KEYS))
_CLOUD_RUN_MANAGED = {"PORT", "K_SERVICE", "K_REVISION", "K_CONFIGURATION"}
_ENVIRONMENTS = ("local", "staging", "production")
_SERVICES = ("api", "worker")


def validate_env(
    mapping: dict[str, str], *, expect: str | None = None, service: str = "api"
) -> list[str]:
    """Liste de problèmes (vide si la configuration est valide).

    Les messages ne contiennent JAMAIS de valeur du fichier (secrets) : uniquement
    des noms de variables et des messages de validation. `expect` : environnement cible
    du déploiement, que le fichier doit déclarer. `service="worker"` ajoute les exigences du
    service worker (`worker_problems`).
    """
    problems = _check_expected_environment(mapping, expect) if expect else []
    try:
        values: dict[str, object] = {}
        for key, raw in mapping.items():
            if key in _CLOUD_RUN_MANAGED:
                continue
            name = key.lower()
            values[name] = json.loads(raw) if name in _JSON_KEYS else raw
        # On isole le processus de l'environnement réel : seul le fichier compte.
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None, **values)  # type: ignore[arg-type]
    except ValidationError as exc:
        # Jamais str(exc) : il contient `input_value=` (extrait des valeurs brutes,
        # donc des secrets). On ne garde que le nom du champ et le message.
        return [
            *problems,
            *(_describe(e) for e in exc.errors(include_input=False, include_url=False)),
        ]
    except json.JSONDecodeError as exc:
        # Ne cite que la position, jamais le contenu.
        return [
            *problems,
            f"une variable JSON ({_JSON_NAMES}) est illisible : {exc.msg}",
        ]
    # Settings ne valide pas le contenu des clés : l'API, elle, les charge à chaque requête
    # (deps.py) et répondrait 500 partout. Les messages ne citent que des numéros de version
    # et des longueurs, jamais le matériel de clé.
    try:
        load_token_cipher(settings)
    except TokenCryptoConfigError as exc:
        problems.append(f"TOKEN_ENC_KEYS / TOKEN_ENC_ACTIVE_VERSION : {exc}")
    if service == "worker":
        problems.extend(worker_problems(settings))
    return problems


def _check_expected_environment(mapping: dict[str, str], expect: str) -> list[str]:
    declared = next((v for k, v in mapping.items() if k.upper() == "ENVIRONMENT"), None)
    if declared == expect:
        return []
    # Les noms d'environnement ne sont pas des secrets ; une valeur inattendue est tout de
    # même signalée par Settings (Literal), on ne la recopie donc pas ici.
    found = "absente (défaut : local)" if declared is None else "différente"
    return [f"ENVIRONMENT : {expect!r} attendu pour cette cible, variable {found}"]


def check_string_values(data: dict[object, object]) -> list[str]:
    """`gcloud --env-vars-file` n'accepte que des chaînes : `true`, `42` ou `null` non
    quotés dans le YAML sont refusés (ou pire, convertis en « None »). On nomme la clé,
    jamais la valeur."""
    return [
        f"{key} : la valeur doit être une chaîne entre guillemets (type {type(value).__name__})"
        for key, value in data.items()
        if not isinstance(value, str)
    ]


def _describe(error: ErrorDetails) -> str:
    where = ".".join(str(part).upper() for part in error["loc"])
    message = error["msg"]
    return f"{where} : {message}" if where else message


def _parse_args(args: list[str]) -> tuple[str, str | None, str] | None:
    """(fichier, environnement attendu, service) ou None si l'usage est incorrect."""
    if not args:
        return None
    path, rest = args[0], args[1:]
    expect: str | None = None
    service = "api"
    seen: set[str] = set()
    while rest:
        if len(rest) < 2 or rest[0] in seen:
            return None
        flag, value = rest[0], rest[1]
        rest = rest[2:]
        seen.add(flag)
        if flag == "--expect" and value in _ENVIRONMENTS:
            expect = value
        elif flag == "--service" and value in _SERVICES:
            service = value
        else:
            return None
    return path, expect, service


def main(argv: list[str]) -> int:
    usage = (
        "usage: python -m app.tools.check_env FICHIER.yaml "
        "[--expect local|staging|production] [--service api|worker]"
    )
    parsed = _parse_args(argv[1:])
    if parsed is None:
        print(usage, file=sys.stderr)
        return 2
    path, expect, service = parsed

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        print("Fichier d'environnement invalide : un mapping CLE: \"valeur\" est attendu", file=sys.stderr)
        return 1
    problems = check_string_values(data)
    if not problems:
        problems = validate_env(
            {str(k): v for k, v in data.items()}, expect=expect, service=service
        )
    if problems:
        print("Fichier d'environnement invalide :", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"{path} : OK ({len(data)} variables, service {service})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
