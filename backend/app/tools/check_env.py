"""Vérifie un fichier d'environnement de déploiement AVANT de le pousser sur Cloud Run.

    python -m app.tools.check_env deploy/env.production.yaml

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

from app.config import Settings

_JSON_KEYS = {"token_enc_keys", "cors_origins"}
_CLOUD_RUN_MANAGED = {"PORT", "K_SERVICE", "K_REVISION", "K_CONFIGURATION"}


def validate_env(mapping: dict[str, str]) -> list[str]:
    """Liste de problèmes (vide si la configuration est valide)."""
    values: dict[str, object] = {}
    for key, raw in mapping.items():
        if key in _CLOUD_RUN_MANAGED:
            continue
        name = key.lower()
        values[name] = json.loads(raw) if name in _JSON_KEYS else raw
    try:
        # On isole le processus de l'environnement réel : seul le fichier compte.
        with mock.patch.dict(os.environ, {}, clear=True):
            Settings(_env_file=None, **values)  # type: ignore[arg-type]
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        return [line.strip() for line in str(exc).splitlines() if line.strip()]
    return []


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.tools.check_env FICHIER.yaml", file=sys.stderr)
        return 2

    data = yaml.safe_load(Path(argv[1]).read_text(encoding="utf-8")) or {}
    problems = validate_env({str(k): str(v) for k, v in data.items()})
    if problems:
        print("Fichier d'environnement invalide :", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"{argv[1]} : OK ({len(data)} variables)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
