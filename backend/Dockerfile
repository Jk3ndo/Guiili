# Image de production pour Cloud Run.
#
# Inclut Chromium (Playwright) pour la verification GTM headless — une
# fonctionnalite reellement livree (voir app/services/gtm_headless.py) ;
# la retirer casserait silencieusement ce bouton sans qu'on l'ait demande.
# Contrepartie assumee : image plus lourde (~500 Mo de plus), cold start un
# peu plus long sur Cloud Run (scale-to-zero). A retirer plus tard si le
# cout/la latence pese trop pour l'usage reel (retirer les 2 lignes
# `playwright install` et le service continue de fonctionner, ce bouton
# renverra juste une erreur geree proprement, cf. gtm_headless.py).
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

# Chromium + dependances systeme (fonts, libgtk, libnss...) necessaires au
# rendu headless reel utilise par verify_gtm().
RUN uv run playwright install --with-deps chromium

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8080

# Cloud Run injecte $PORT (8080 par defaut). Les migrations ne tournent PLUS au
# demarrage : avec plusieurs instances, deux `alembic upgrade head` simultanes se
# marchent dessus. Elles sont executees par un Cloud Run Job avant chaque
# deploiement (voir scripts/deploy-backend.sh et docs/ops/runbook.md).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
