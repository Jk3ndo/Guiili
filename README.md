# Control Center Marketing Agentique

Plateforme d'audit marketing (SEO / GA4 / Core Web Vitals) multi-comptes Google,
en lecture seule. Voir `docs/reference/plan-v3.md` pour la vision produit et
`docs/superpowers/specs/` pour les specs techniques.

## Prérequis

- Docker + Docker Compose
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node 20+

## Démarrage local (commande unique)

```bash
./scripts/dev.sh          # Postgres + Redis, backend :8020, frontend :4000
./scripts/dev.sh stop     # arrête backend + frontend (laisse Docker)
```

Puis ouvrir **http://127.0.0.1:4000** (pas `localhost` — voir plus bas).

Première utilisation, préparer les dépendances :

```bash
docker compose up -d                     # PostgreSQL (host 55432) + Redis (6380)
cd backend  && cp .env.example .env && uv sync && cd ..
cd frontend && cp .env.example .env.local && npm install && cd ..
```

### Ce que fait `scripts/dev.sh`

| Service   | Adresse                          | Notes |
|-----------|----------------------------------|-------|
| PostgreSQL | `127.0.0.1:55432`               | `docker compose up -d` |
| Redis      | `127.0.0.1:6380`                | idem |
| Backend    | `http://127.0.0.1:8020/api/v1`  | `uvicorn --reload` ; `alembic upgrade head` en amont |
| Frontend   | `http://127.0.0.1:4000`         | `next dev` (host+port figés dans le script `dev`) |

> Le port **8020** (au lieu de 8000) évite un conflit courant ; ajustez
> `API_PORT` dans `scripts/dev.sh` **et** `NEXT_PUBLIC_API_BASE_URL` dans
> `frontend/.env.local` si besoin.

### Loopback partagé (important)

Le backend pose un cookie de session `SameSite=Lax`. Pour qu'il soit transmis
du front vers l'API, **les deux doivent être servis sur le même hostname** :
soit tout en `127.0.0.1`, soit tout en `localhost` — jamais un mélange, sinon
les appels API renvoient 401 et l'UI bascule sur ses données mockées
(bandeau « Mode démo — API hors-ligne »).

La config par défaut est **`127.0.0.1`** partout : ouvrez le front sur
`http://127.0.0.1:4000` et gardez `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8020/api/v1`.

### Mode démo

`backend/.env` contient `GOOGLE_OAUTH_MOCK=true` : pas de credentials Google
requis. Le backend expose alors `GET /api/v1/dev/workspaces` qui amorce un
utilisateur de dev + 4 sites de démo (déjà scannés) et pose le cookie de
session — c'est ce que le front appelle au chargement pour résoudre
`domaine → website_id`.

## Tests

```bash
cd backend  && uv run pytest -W error     # suite complète (Postgres requis)
cd frontend && npm run build && npm run lint
```
