#!/usr/bin/env bash
# Démarrage local complet : Postgres + Redis, backend FastAPI (8020),
# frontend Next.js (4000). Les deux services parlent sur le MÊME loopback
# (127.0.0.1) — indispensable pour que le cookie de session (SameSite=Lax)
# soit transmis du front vers l'API.
#
#   ./scripts/dev.sh          démarre tout
#   ./scripts/dev.sh stop     arrête backend + frontend (laisse Docker)
#
# Prérequis : docker compose, backend/.venv (uv sync), frontend/node_modules,
# Chromium pour Playwright (backend/.venv : python -m playwright install
# chromium) — requis par la vérification GTM headless (bouton "/audit" +
# outil conseiller run_gtm_headless_probe), jamais lancé automatiquement.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_HOST=127.0.0.1
API_PORT=8020
WEB_PORT=4000
PID_DIR="$ROOT/.dev"
mkdir -p "$PID_DIR"

_python() { echo "$ROOT/backend/.venv/Scripts/python.exe"; }

stop() {
  for name in api web; do
    pf="$PID_DIR/$name.pid"
    [ -f "$pf" ] || continue
    pid="$(cat "$pf")"
    taskkill //F //T //PID "$pid" >/dev/null 2>&1 || kill "$pid" 2>/dev/null || true
    rm -f "$pf"
    echo "stopped $name ($pid)"
  done
}

if [ "${1:-start}" = "stop" ]; then stop; exit 0; fi

stop  # repart propre

echo "▸ docker compose up -d (Postgres 55432 / Redis 6380)"
docker compose -f "$ROOT/docker-compose.yml" up -d

echo "▸ alembic upgrade head"
( cd "$ROOT/backend" && "$(_python)" -m alembic upgrade head )

echo "▸ backend  → http://$API_HOST:$API_PORT/api/v1  (GOOGLE_OAUTH_MOCK requis)"
( cd "$ROOT/backend" && "$(_python)" -m uvicorn app.main:app \
    --host "$API_HOST" --port "$API_PORT" --reload \
    > "$PID_DIR/api.log" 2>&1 & echo $! > "$PID_DIR/api.pid" )

echo "▸ frontend → http://$API_HOST:$WEB_PORT  (NEXT_PUBLIC_API_BASE_URL doit pointer sur $API_HOST:$API_PORT)"
( cd "$ROOT/frontend" && npm run dev \
    > "$PID_DIR/web.log" 2>&1 & echo $! > "$PID_DIR/web.pid" )

echo
echo "Logs : $PID_DIR/{api,web}.log   — arrêt : ./scripts/dev.sh stop"
echo "Ouvrez http://$API_HOST:$WEB_PORT (et non « localhost », pour partager le loopback avec l'API)."
