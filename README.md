# Control Center Marketing Agentique

Plateforme d'audit marketing (SEO / GA4 / Core Web Vitals) multi-comptes Google,
en lecture seule. Voir `docs/reference/plan-v3.md` pour la vision produit et
`docs/superpowers/specs/` pour les specs techniques.

## Prérequis

- Docker + Docker Compose
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node 20+

## Démarrage local

```bash
docker compose up -d                 # PostgreSQL + Redis
cd backend
cp .env.example .env                 # puis renseigner les valeurs
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload  # http://localhost:8000/health
```

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev                           # http://localhost:3000
```

## Tests

```bash
cd backend && uv run pytest
```
