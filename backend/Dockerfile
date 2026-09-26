# Image de l'API publique (Cloud Run `backend-guiili`).
#
# Sans Chromium depuis le lot B : la verification GTM headless s'execute sur le
# service worker (Dockerfile.worker), que l'API appelle avec un jeton d'identite
# (app/services/worker_client.py). Image plus legere, demarrage a froid plus court.
# Le PAQUET Python `playwright` reste installe (dependance normale de pyproject.toml :
# app.services.gtm_headless l'importe au chargement) ; seul le binaire du navigateur
# est absent. Sans WORKER_BASE_URL, le bouton headless renverrait une erreur geree
# proprement (voir app/services/gtm_headless.py) : le script de deploiement l'exige.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /usr/local/bin/

WORKDIR /app

# Couche dependances seule d'abord (cache Docker : ne se reinvalide que si
# pyproject.toml/uv.lock changent, pas a chaque edition de code).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8080

# Cloud Run injecte $PORT (8080 par defaut). Les migrations ne tournent PLUS au
# demarrage : avec plusieurs instances, deux `alembic upgrade head` simultanes se
# marchent dessus. Elles sont executees par un Cloud Run Job avant chaque
# deploiement (voir scripts/deploy-backend.sh et docs/ops/runbook.md).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
