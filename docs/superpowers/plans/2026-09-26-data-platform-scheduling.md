# Lot B : socle de données et suivi planifié — plan d'exécution

> **Pour les agents d'exécution :** SOUS-COMPÉTENCE OBLIGATOIRE : utiliser
> superpowers:subagent-driven-development (recommandé) ou
> superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes
> utilisent la syntaxe à cases (`- [ ]`) pour le suivi.

**Objectif :** faire entrer toute donnée de mesure (GA4, Search Console, Core Web Vitals
des visiteurs réels, sondes TLS et disponibilité) par une abstraction `MetricSource`,
la stocker de façon idempotente dans une série temporelle partitionnée par mois avec
des cumuls semaine/mois, la collecter automatiquement selon un planning choisi par site
(Cloud Scheduler → Cloud Tasks → service `worker`), relancer la vérification légère du
plan de mesure, exposer une API de séries temporelles unique et alerter l'équipe
avant le client quand une collecte échoue.

**Architecture :** un paquet `app/services/metrics/` (types, registre de métriques en
code, nettoyage des dimensions, agrégation pure, stockage idempotent + cumuls,
partitions, adaptateurs de sources) et un paquet `app/services/jobs/` (types de tâches
et fréquences, exécuteur avec clé d'idempotence/bail/nouvelles tentatives/limites par
workspace, santé et alertes, planificateur `tick`, files `InlineQueue` et
`CloudTasksQueue`, gestionnaires par type de tâche). Une seconde application FastAPI,
`app/worker_main.py`, porte les seules routes internes (`/internal/tick`,
`/internal/tasks/run`, `/internal/jobs/health`, `/internal/headless/verify`),
authentifiées par jeton OIDC Google ; elle tourne dans une image avec Chromium, l'image
de l'API n'en a plus et lui délègue la vérification headless. L'API publique gagne
`GET /websites/{id}/metrics/series` et `GET/PUT /websites/{id}/schedules` ; le
frontend gagne une carte « Suivi automatique » sur la page Plan de mesure.

**Stack :** Python 3.12 / FastAPI / SQLAlchemy 2.1 (asyncpg) / Alembic 1.20 /
PostgreSQL 16 (partitionnement déclaratif) / httpx / PyJWT[crypto] (nouvelle
dépendance) / Cloud Run (2 services) + Cloud Tasks + Cloud Scheduler (API REST via
httpx, jetons du serveur de métadonnées) ; Next.js 16 / React 19 / Tailwind v4.

**Spec :** `docs/superpowers/specs/2026-09-25-roadmap-v3-architecture-design.md`
(§3 architecture cible, §4 modèle de données, §5 exécution et planification, §6
mesures 3, 6 et 8, §8 lot B, §9 point 8, §10 risques). Faits sur les concurrents :
`docs/superpowers/specs/2026-09-25-benchmark-amplitude-matomo.md`. La spec est
l'autorité ; ce plan en est l'argumentation.

**Prérequis :** lots 0 et A mergés dans `main` (HEAD `dfb82cb` au moment de la
rédaction, 809 tests backend verts). Le lot 0 apporte `create_app`, la journalisation
JSON (`app/logging_config.py`), Sentry (`app/observability.py`), la limitation de
débit (`app/api/rate_limit.py`), la suite d'isolation (`tests/test_tenant_isolation.py`),
`check_env`, `scripts/deploy-backend.sh` et le Job de migration. Le lot A apporte
`refresh_plan`, `lock_site`, `build_reader` et `GoogleReadError`.

## Contraintes globales (valables pour toutes les tâches)

- **Google en lecture seule, aucun nouveau scope OAuth** : `GOOGLE_DATA_SCOPES`
  (`analytics.readonly`, `webmasters.readonly`) ne change pas ; aucune écriture GA4,
  GTM, Search Console ni Ads.
- **Le code décide, jamais un LLM** : statuts, criticités, seuils et alertes viennent
  du code et du registre de métriques.
- **Jamais « fait » ou « reçu » sans preuve** : une source en erreur produit *zéro
  observation* et un `job_run` en échec (ou « ignoré » si la source n'est pas
  reliée), jamais une valeur inventée ni un zéro de remplacement. Un jour sans ligne
  dans la réponse Google reste absent ; l'API de séries renvoie `null` pour une
  période sans donnée.
- **Additif** : aucun changement de comportement des endpoints existants ; les tests
  existants restent verts sans modification, hors ajouts explicitement listés
  (`EXPECTED_TABLES` et un test dans `tests/test_migrations.py`, `CASES` et une
  assertion dans `tests/test_tenant_isolation.py`, nouveaux tests dans
  `tests/test_deploy_assets.py`). La seule évolution d'infrastructure visible est
  l'image de l'API sans Chromium : la vérification headless y est alors déléguée au
  worker (même réponse, Tâche 14).
- **Aucun appel réseau en test** : `httpx.MockTransport`, fonctions factices, jamais de
  vrai Chromium, jamais le serveur de métadonnées, jamais Google.
- **Multi-clients** : toute route par site charge le site via le workspace de
  l'appelant (`owned_website`), porte `limit_by_user(...)` et un cas dans
  `tests/test_tenant_isolation.py::CASES` ; les écritures de planning sont réservées au
  propriétaire (`require_owner`). Les routes internes n'existent **que** dans
  l'application worker (`app/worker_main.py`), avec `include_in_schema=False`, et
  exigent un jeton OIDC Google (audience et e-mail du compte de service vérifiés).
- **Verrous avant lecture** : un verrou consultatif (`pg_advisory_xact_lock`) sur la
  clé d'idempotence, le workspace ou le couple (site, source) est pris AVANT de lire
  puis d'écrire ; aucune transaction ne reste ouverte pendant les appels réseau quand
  on peut l'éviter (on committe avant de collecter).
- **Validation stricte** des corps et paramètres d'API : 422 avec message en français ;
  une réponse Google de forme inattendue devient une `SourceError("api_error",
  recoverable=True)`, jamais une valeur par défaut silencieuse.
- **Pas de données personnelles dans les dimensions stockées** : pages réduites au
  chemin sans requête ni fragment, requêtes de recherche contenant un e-mail ou une
  longue suite de chiffres écartées, noms d'événements GA4 validés.
- **Jetons jamais dans les logs ni dans les réponses** (`field(repr=False)`, `raise ...
  from None` quand l'exception réseau porte une URL avec clé).
- **Textes destinés aux utilisateurs en français** ; frontend : erreurs 429, 403, 5xx
  et réseau affichées clairement (jamais « API hors ligne ») ; listes React clés par
  identifiant stable (`kind`).
- **Qualité** : `cd backend && .venv/Scripts/python.exe -m pytest -W error -q` vert
  (809 tests au départ), `uv run ruff check app tests` propre (si `uv` n'est pas sur le
  PATH : `"$APPDATA/Python/Python312/Scripts/uv.exe"`), `alembic check` propre ;
  `cd frontend && npm run build && npm run lint` à 0 erreur / 0 avertissement.
- **Migrations** appliquées par le Cloud Run Job (le conteneur ne migre jamais au
  démarrage).
- **Tests de concurrence** : prouver l'attente d'un verrou par `pg_locks`
  (`locktype = 'advisory' AND NOT granted`), jamais par des durées.
- **Aucune commande `gcloud`, aucun déploiement, aucun push** : les étapes marquées
  **[PROPRIÉTAIRE]** sont décrites dans le runbook et listées dans le compte rendu,
  jamais exécutées.
- Tests : fixtures de `backend/tests/conftest.py` (`db_session`, `make_user`,
  `authed_client`, `db_client`, `engine`) et `owner_workspace_id` ; créer les sites
  directement en base (`Website(workspace_id=…, domain=…, display_name=…)`).
- Conventions git : branche `feat/data-platform` (créée depuis `main` à la Tâche 1), un
  commit par tâche, messages en français terminés par la ligne
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`, jamais de `--no-verify`,
  jamais de push.
- Style Python (ruff) : imports en tête de module (PLC0415), pas de lambda assignée à
  une variable (E731), `zip(..., strict=True)`, `raise ... from ...` dans un `except`,
  `field(default_factory=...)` pour les valeurs par défaut de dataclass, uniquement
  des apostrophes droites `'` dans le code.

## Décisions de cadrage

### Décisions prises avant ce plan (à respecter)

1. **Ce que livre le lot B** : abstraction `MetricSource`
   (`collect(website, day_range) -> list[Observation]`, quotas, fraîcheur, dimensions
   permises, erreurs récupérables) ; tables `metric_points` (clé primaire
   `(website_id, source, metric, dim_key, day)`, `dims` JSONB, `collected_at`, `run_id`,
   partitionnée par mois, dimensions à forte cardinalité plafonnées à un top N par
   jour), `metric_rollups` (semaine et mois, écrits après chaque collecte),
   `schedules`, `job_runs` ; registre de métriques en code ; adaptateurs GA4 Data,
   Search Console, PageSpeed/CrUX (LCP/INP/CLS terrain) et sondes ; stockage
   idempotent ; exécuteur (clé `(site, type, fenêtre)`, bail, nouvelles tentatives,
   erreurs récupérables ou non, limites par workspace, file lourde une à la fois) ;
   planificateur (toutes les heures, 3 fois par jour, quotidien, tous les 3 jours,
   hebdomadaire ; plancher 8 h pour GA4/Search Console, 1 h pour les sondes légères) ;
   `/internal/tick` et exécution de tâche authentifiés OIDC ; `TaskQueue` avec
   `CloudTasksQueue` et `InlineQueue` ; service `worker` (même code, image avec
   Chromium), image API sans Chromium, script de déploiement étendu, runbook ;
   vérification légère planifiée du plan de mesure (§9 point 8) ; API de séries
   `GET /websites/{website_id}/metrics/series` et `GET/PUT …/schedules` ; alertes
   d'exploitation (logs structurés, Sentry, `GET /internal/jobs/health`), pas
   d'e-mail ; suppression en cascade avec le site ; carte frontend « Suivi
   automatique ».
2. **Hors périmètre** : rapports périodiques par e-mail (reportés au lot C), tableau de
   bord multi-sites (lot C), SEO profond et crawler (lot D), pixel et moteur colonne
   (lot F), toute écriture Google, RLS Postgres, Secret Manager.
3. **Infra Google Cloud = [PROPRIÉTAIRE]** : service worker, files Cloud Tasks, comptes
   de service, job Cloud Scheduler, rôles IAM, audience OIDC. Le plan fournit le code,
   les variables, les commandes du runbook et des tests sans réseau.
4. **Partitionnement mensuel** : migration qui crée la table partitionnée, la partition
   par défaut et les partitions de M-4 à M+3 ; tâche `partition_maintenance`
   idempotente ; `alembic check` reste vert grâce à un filtre `include_object` dans
   `alembic/env.py` qui écarte les partitions (vérifié : sans lui, `compare_metadata`
   signale chaque partition comme `remove_table`) ; `tests/test_migrations.py` vérifie
   la forme partitionnée sur la base de migrations.
5. **Rétention** : points journaliers 25 mois, cumuls sans limite, purge idempotente.
6. **Rattrapage initial** de 90 jours pour GA4 et Search Console, découpé par fenêtres
   de 31 jours, exposé comme type de tâche `backfill`.
7. **Multi-clients** : voir « Contraintes globales ».
8. **Contraintes héritées** : voir « Contraintes globales ».
9. **Enseignements du lot A** : voir « Contraintes globales ».
10. **Ordre des tâches** : ajusté ci-dessous (santé des tâches avant le planificateur,
    qui l'appelle ; délégation headless séparée de l'infrastructure).

### Décisions ajoutées par ce plan

11. **Deux applications, un seul code** : `app.main:app` (API publique, inchangée, aucune
    route `/internal`) et `app.worker_main:app` (routes internes uniquement + `/health`).
    Le rôle vient de la commande du conteneur (deux Dockerfiles), pas d'une variable :
    `gcloud run deploy --env-vars-file` est exclusif de `--update-env-vars`, et les deux
    services partagent le même fichier d'environnement. Cloud Scheduler appelle le
    worker (privé, IAM `run.invoker` + OIDC vérifié dans le code).
12. **Headless** : les boutons existants (`/gtm/headless`, `refresh?headless=true`,
    outil du conseiller) gardent leur réponse synchrone ; l'API appelle
    `POST /internal/headless/verify` du worker avec un jeton d'identité de son compte
    de service. Le worker n'exécute qu'un navigateur à la fois par instance
    (sémaphore) et est plafonné à 2 instances. La file Cloud Tasks `heavy`
    (`max-concurrent-dispatches=1`) et le routage `TaskKind.queue` existent, mais aucun
    type planifié n'est lourd au lot B : le lot A a décidé que le navigateur n'est
    jamais lancé automatiquement.
13. **Une file Cloud Tasks par source** (`ga4`, `gsc`, `cwv`, `light`, `heavy`,
    nommées `{CLOUD_TASKS_QUEUE_PREFIX}-{file}`) : la spec §3 demande un débit par
    source pour les quotas Google.
14. **Clé d'idempotence** `"{type}:{site|global}:{fenêtre}"`, la fenêtre étant le début
    du créneau (heure UTC arrondie à l'intervalle effectif depuis l'époque Unix,
    format `AAAAMMJJTHHMM`). Le rattrapage utilise la fenêtre `"{source}-{créneau}"` :
    tant que `schedules.backfill_done_at` est vide, chaque créneau retente le
    rattrapage au lieu de la collecte courte.
15. **Nouvelles tentatives** : confiées à Cloud Tasks (5 tentatives, backoff 60 s → 1 h).
    Le worker répond 503 (avec `Retry-After`) pour une erreur récupérable s'il reste
    des tentatives, pour une tâche « occupée » (bail valide ailleurs) ou « freinée »
    (limite de workspace) ; 200 sinon. `InlineQueue` n'a pas de nouvelle tentative.
16. **« Non concerné » n'est pas un échec** : source non reliée ou site archivé ⇒
    `job_run` `skipped`, jamais d'alerte ; le planning reste actif pour le jour où la
    source sera reliée.
17. **Planchers** : `collect_ga4`, `collect_gsc` et `collect_cwv` 8 h (quotas Google et
    PageSpeed ; CrUX n'évolue qu'une fois par jour) ; `collect_probes` 1 h ;
    `measurement_check` 8 h (il lit GA4 et Search Console). Le plancher est appliqué à
    l'écriture (422) et au calcul du créneau (défense si la base était modifiée).
18. **CWV** : uniquement le 75e centile *origine* de CrUX (`originLoadingExperience`)
    comme valeur terrain ; absent ⇒ aucune observation. Le score Lighthouse est une
    métrique distincte (`performance_score`, labo). `parse_pagespeed` (qui remplace le
    terrain par le labo et met 0 en mode dégradé) n'est pas réutilisé pour le stockage.
19. **Services existants** : `ga4.py`, `gsc.py` et `pagespeed.py` dégradent en silence
    (score 0) et restent inchangés pour l'audit ; les adaptateurs réutilisent leurs URL
    et petits utilitaires, `_raise_for_status` et `GoogleReadError`
    (`measurement/google_reader.py`), `build_reader` (résolution des jetons),
    `check_certificate` et `fetch_page_safe`.
20. **Métriques** : pas d'« utilisateurs » (non additifs d'un jour à l'autre, un cumul
    serait faux) ; dimensions plafonnées à 25 par jour ; le cumul d'une dimension est
    un minorant (jours où elle était dans le top), signalé par `days_covered`.
    Agrégations déclarées dans le registre : somme, moyenne, dernière valeur, ratio
    (`ctr = Σclics / Σimpressions`), moyenne pondérée (`position` par les impressions).
21. **Partitions** : noms `metric_points_pAAAA_MM` et `metric_points_default` ; la base
    de test (créée par `create_all`) reçoit la partition par défaut par un écouteur
    `after_create` ; la maintenance crée M-4..M+3, sort les lignes de la partition par
    défaut vers le nouveau mois (vérifié sur PostgreSQL 16 : créer la partition d'un
    mois dont des lignes sont dans la partition par défaut échoue, d'où `LIKE` +
    déplacement + `ATTACH`), détache et supprime au-delà de 25 mois, et purge les
    `job_runs` de plus de 90 jours.
22. **Disjoncteur** (§6 mesure 8) : par workspace et par source Google, 3 échecs `quota`
    en 30 minutes ⇒ la collecte suivante s'arrête sans appeler Google
    (`circuit_open`, récupérable) pendant 30 minutes.
23. **Dépendances** : `pyjwt[crypto]` pour vérifier les jetons OIDC Google (JWKS lues
    par httpx) ; aucune bibliothèque Google Cloud : Cloud Tasks par REST et jetons par
    le serveur de métadonnées de Cloud Run, via httpx (déjà présent), testables par
    `MockTransport`.
24. **Limites par workspace** : 2 tâches simultanées (vérifié à la réclamation sous
    verrou consultatif du workspace), 300 tâches par jour (vérifié par le `tick`).
25. **Configuration** : les nouveaux réglages sont optionnels dans `Settings` (aucune
    règle ajoutée à `_enforce_environment_rules`, donc aucun test existant touché) ; les
    exigences du worker sont vérifiées par `worker_problems(settings)` au démarrage du
    worker hors `local` et par `check_env --service worker`, que le script de
    déploiement appelle.
26. **Script de déploiement** : garde ses 5 étapes (les tests existants cherchent
    `== 1/5`), construit deux images (le worker via `backend/cloudbuild.worker.yaml`),
    déploie deux services ; `DEPLOY_ENV_FILE` permet un `--dry-run` testé sur un fichier
    temporaire.
27. **API de planning** : `PUT /websites/{website_id}/schedules` avec le corps
    `{kind, frequency, enabled}` (pas de paramètre de chemin supplémentaire) ; `GET`
    renvoie aussi les types pas encore matérialisés (valeurs par défaut), que le `tick`
    matérialise.
28. **API de séries** : paramètres validés *après* le contrôle d'appartenance (un
    étranger reçoit 404, jamais 422) ; période par défaut : les 28 jours finissant
    hier ; au plus 800 jours ; périodes sans donnée ⇒ `value: null`.
29. **Frontend** : la carte « Suivi automatique » vit dans la page Plan de mesure (pas
    de nouvelle route) ; le droit d'écrire vient du backend (`can_edit`).
30. **Tick** toutes les 15 minutes ; il matérialise les plannings, expire les tâches en
    file depuis plus de 2 h (`not_dispatched`), dépose au plus 100 tâches par passage
    et publie la santé des tâches à chaque passage.
31. **Alertes** : ligne de log `jobs_health_alert` (ERROR si un échec relève de nous,
    WARNING si seul le client peut agir), événement Sentry à message fixe (compteurs en
    `extra`), `GET /internal/jobs/health` ; l'alerte Cloud Monitoring sur cette ligne
    de log est [PROPRIÉTAIRE].

## Structure des fichiers

Backend (nouveaux) :
- `app/models/metric_point.py`, `app/models/metric_rollup.py`, `app/models/schedule.py`,
  `app/models/job_run.py`
- `alembic/versions/c3a9e5f1b8d2_data_platform.py`
- `app/services/metrics/` : `__init__.py`, `types.py`, `registry.py`, `dimensions.py`,
  `aggregate.py`, `store.py`, `partitions.py`, `series.py`, `sources/__init__.py`,
  `sources/google_http.py`, `sources/ga4.py`, `sources/gsc.py`,
  `sources/credentials.py`, `sources/cwv.py`, `sources/probes.py`, `sources/factory.py`
- `app/services/jobs/` : `__init__.py`, `kinds.py`, `runner.py`, `health.py`,
  `queue.py`, `scheduler.py`, `cloud_tasks.py`, `handlers.py`, `messages.py`,
  `schedules.py`
- `app/services/gcp_metadata.py`, `app/services/worker_client.py`
- `app/security/oidc.py`, `app/api/internal_auth.py`, `app/api/internal.py`
- `app/api/v1/endpoints/metrics.py`
- `app/worker_main.py`, `app/tools/jobs.py`
- `Dockerfile.worker`, `cloudbuild.worker.yaml`

Backend (modifiés) : `app/models/__init__.py`, `alembic/env.py`, `app/config.py`,
`app/api/deps.py`, `app/api/v1/router.py`, `app/services/gtm_headless.py` (ajout
d'une fonction), `app/tools/check_env.py`, `Dockerfile`, `pyproject.toml`, `uv.lock`,
`tests/test_migrations.py`, `tests/test_tenant_isolation.py`,
`tests/test_deploy_assets.py`.

Tests (nouveaux) : `tests/jobs_fakes.py`, `test_data_platform_models.py`,
`test_metrics_registry.py`, `test_metrics_dimensions.py`, `test_metrics_aggregate.py`,
`test_metrics_store.py`, `test_metrics_partitions.py`,
`test_metrics_sources_google.py`, `test_metrics_sources_cwv_probes.py`,
`test_jobs_runner.py`, `test_jobs_health.py`, `test_jobs_scheduler.py`,
`test_jobs_cloud_tasks.py`, `test_oidc.py`, `test_jobs_handlers.py`,
`test_worker_app.py`, `test_metrics_series.py`, `test_metrics_endpoints.py`,
`test_headless_delegation.py`.

Racine : `scripts/deploy-backend.sh`, `deploy/env.example.yaml`, `docs/ops/runbook.md`.

Frontend (nouveaux) : `lib/api/schedules.ts`, `components/plan/auto-tracking-card.tsx`.
Frontend (modifié) : `components/plan/plan-view.tsx`.

## Ordre des tâches et dépendances

1 Modèles + migration partitionnée → 2 Types, registre, dimensions, agrégation →
3 Stockage idempotent + cumuls + top N → 4 Partitions (création, déplacement, purge) →
5 Adaptateurs GA4 et Search Console → 6 Adaptateurs CWV et sondes → 7 Types de tâches
+ exécuteur (idempotence, bail, reprises, limites) → 8 Santé des tâches et alertes →
9 Planificateur (`tick`) + `TaskQueue`/`InlineQueue` → 10 `CloudTasksQueue`, jetons de
métadonnées, vérification OIDC → 11 Gestionnaires des types de tâches (collecte,
rattrapage, vérification du plan, maintenance, disjoncteur) → 12 Application worker et
routes internes (+ outil `tick` local) → 13 API de séries et de planning → 14
Délégation headless de l'API au worker → 15 Images, déploiement, environnement,
runbook → 16 Frontend « Suivi automatique » → 17 Vérification finale et mémoire.

Chaque tâche dépend des précédentes (interfaces exactes dans son bloc « Interfaces »).
Les Tâches 5 et 6, puis 8 et 10, pourraient être parallélisées ; l'ordre séquentiel
est recommandé (fichiers partagés `app/config.py` et `tests/jobs_fakes.py`).

---
### Tâche 1 : Modèles et migration (dont `metric_points` partitionnée)

**Fichiers :**
- Créer : `backend/app/models/metric_point.py`, `backend/app/models/metric_rollup.py`,
  `backend/app/models/schedule.py`, `backend/app/models/job_run.py`
- Modifier : `backend/app/models/__init__.py`
- Créer : `backend/alembic/versions/c3a9e5f1b8d2_data_platform.py`
- Modifier : `backend/alembic/env.py` (filtre des partitions)
- Modifier : `backend/tests/test_migrations.py` (`EXPECTED_TABLES` + un test)
- Test : `backend/tests/test_data_platform_models.py`

**Interfaces :**
- Consomme : `Base` (`app.db.base`), `UUIDPrimaryKeyMixin`, `TimestampMixin`
  (`app.models.mixins`), tables `websites` et `workspaces`.
- Produit (importables depuis `app.models`) :
  - `MetricPoint` — table `metric_points`, PK `(website_id, source, metric, dim_key,
    day)`, colonnes `value: float`, `dims: dict[str, str]`, `collected_at: datetime`,
    `run_id: UUID | None` ; partitionnée `RANGE (day)`. Constante
    `app.models.metric_point.DEFAULT_PARTITION = "metric_points_default"`.
  - `MetricRollup` — table `metric_rollups`, PK `(website_id, source, metric, dim_key,
    grain, period_start)`, colonnes `value: float`, `days_covered: int`,
    `dims: dict[str, str]`, `updated_at: datetime`. `grain` ∈ `{"week", "month"}`.
  - `Schedule` — table `schedules` (`id`, `website_id`, `kind`, `frequency`, `enabled`,
    `next_due_at`, `last_run_at`, `last_status`, `last_success_at`, `failing_since`,
    `last_error_code`, `backfill_done_at`, `created_at`, `updated_at`), unicité
    `(website_id, kind)` nommée `uq_schedules_website_kind`.
  - `JobRun` — table `job_runs` (`id`, `idempotency_key` unique, `kind`, `website_id`,
    `workspace_id`, `window_label`, `params`, `status`, `attempt`, `max_attempts`,
    `lease_expires_at`, `enqueued_at`, `started_at`, `finished_at`, `duration_ms`,
    `error_code`, `error_detail`, `recoverable`, `observations`). `status` ∈
    `{"queued", "running", "succeeded", "failed", "skipped"}` (chaîne validée par le
    code, pas d'enum SQL).
  - Toutes les lignes portant `website_id` sont supprimées avec le site (FK
    `ON DELETE CASCADE`) ; `job_runs.workspace_id` aussi avec le workspace.

- [ ] **Étape 0 : créer la branche**

```bash
git checkout main
git checkout -b feat/data-platform
```

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_data_platform_models.py
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.metric_point import DEFAULT_PARTITION, MetricPoint
from app.models.metric_rollup import MetricRollup
from app.models.schedule import Schedule
from app.models.website import Website
from tests.conftest import owner_workspace_id

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)


async def _site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"dp-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


def _point(site: Website, **overrides) -> MetricPoint:
    values = {
        "website_id": site.id,
        "source": "ga4",
        "metric": "sessions",
        "dim_key": "",
        "day": date(2026, 9, 20),
        "value": 12.0,
        "dims": {},
        "collected_at": NOW,
    }
    values.update(overrides)
    return MetricPoint(**values)


async def test_a_metric_point_lands_in_the_default_partition(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "dp-default.test")
    db_session.add(_point(site))
    await db_session.flush()
    where = await db_session.scalar(
        text("SELECT tableoid::regclass::text FROM metric_points WHERE website_id = :w"),
        {"w": site.id},
    )
    assert where == DEFAULT_PARTITION
    row = (
        await db_session.execute(select(MetricPoint).where(MetricPoint.website_id == site.id))
    ).scalar_one()
    assert row.value == 12.0 and row.run_id is None and row.dims == {}


async def test_the_primary_key_makes_a_day_unique_per_series(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "dp-unique.test")
    db_session.add(_point(site))
    await db_session.flush()
    db_session.add(_point(site, value=99.0))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_schedule_is_unique_per_site_and_kind(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "dp-schedule.test")
    for _ in range(2):
        db_session.add(
            Schedule(
                website_id=site.id,
                kind="collect_ga4",
                frequency="daily",
                enabled=True,
                next_due_at=NOW,
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_job_run_idempotency_key_is_unique(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "dp-run.test")
    for _ in range(2):
        db_session.add(
            JobRun(
                idempotency_key=f"collect_ga4:{site.id}:20260926T0000",
                kind="collect_ga4",
                website_id=site.id,
                workspace_id=site.workspace_id,
                window_label="20260926T0000",
                params={},
                status="queued",
                attempt=0,
                max_attempts=5,
                observations=0,
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_every_lot_b_row_is_deleted_with_the_website(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "dp-cascade.test")
    db_session.add_all(
        [
            _point(site),
            MetricRollup(
                website_id=site.id,
                source="ga4",
                metric="sessions",
                dim_key="",
                grain="week",
                period_start=date(2026, 9, 14),
                value=40.0,
                days_covered=4,
                dims={},
                updated_at=NOW,
            ),
            Schedule(
                website_id=site.id,
                kind="collect_ga4",
                frequency="daily",
                enabled=True,
                next_due_at=NOW,
            ),
            JobRun(
                idempotency_key=f"collect_ga4:{site.id}:w",
                kind="collect_ga4",
                website_id=site.id,
                workspace_id=site.workspace_id,
                window_label="w",
                params={},
                status="succeeded",
                attempt=1,
                max_attempts=5,
                observations=3,
            ),
        ]
    )
    await db_session.flush()

    await db_session.delete(site)
    await db_session.flush()
    db_session.expunge_all()

    for model in (MetricPoint, MetricRollup, Schedule, JobRun):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0, model
```

Dans `backend/tests/test_migrations.py` :

1. ajouter `from datetime import UTC, datetime` aux imports standard et
   `from sqlalchemy import inspect, text` (remplace `from sqlalchemy import inspect`) ;
2. ajouter `"metric_points"`, `"metric_rollups"`, `"schedules"` et `"job_runs"` à
   `EXPECTED_TABLES` ;
3. ajouter ce test à la fin du fichier :

```python
async def test_metric_points_is_partitioned_by_month_with_a_default(
    clean_migrations_db,
) -> None:
    assert _alembic("upgrade", "head").returncode == 0
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.connect() as conn:
            strategy = await conn.scalar(
                text(
                    "SELECT p.partstrat::text FROM pg_partitioned_table p "
                    "JOIN pg_class c ON c.oid = p.partrelid WHERE c.relname = 'metric_points'"
                )
            )
            children = set(
                (
                    await conn.execute(
                        text(
                            "SELECT c.relname FROM pg_inherits i "
                            "JOIN pg_class c ON c.oid = i.inhrelid "
                            "JOIN pg_class p ON p.oid = i.inhparent "
                            "WHERE p.relname = 'metric_points'"
                        )
                    )
                ).scalars()
            )
    finally:
        await engine.dispose()
    assert strategy == "r"  # RANGE
    assert "metric_points_default" in children
    assert f"metric_points_p{datetime.now(UTC):%Y_%m}" in children
    assert len(children) == 9  # partition par défaut + M-4 .. M+3
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_data_platform_models.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.models.job_run'`).

- [ ] **Étape 2 : créer les modèles**

```python
# backend/app/models/metric_point.py
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    DDL,
    Date,
    DateTime,
    Double,
    ForeignKey,
    PrimaryKeyConstraint,
    String,
    Uuid,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Partition « attrape-tout » : une ligne dont le mois n'a pas encore sa partition y
# atterrit au lieu de faire échouer la collecte ; la maintenance l'en sort ensuite.
DEFAULT_PARTITION = "metric_points_default"


class MetricPoint(Base):
    """Série temporelle étroite : une valeur par (site, source, métrique, dimensions, jour).

    Partitionnée par mois sur `day`. La clé primaire porte les cinq colonnes : rejouer
    un jour réécrit les mêmes lignes (idempotence). `dim_key` vaut "" pour le total et
    une empreinte stable des dimensions sinon ; `dims` garde les valeurs lisibles."""

    __tablename__ = "metric_points"
    __table_args__ = (
        PrimaryKeyConstraint("website_id", "source", "metric", "dim_key", "day"),
        {"postgresql_partition_by": "RANGE (day)"},
    )

    website_id: Mapped[UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(64))
    dim_key: Mapped[str] = mapped_column(String(64))
    day: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    dims: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Exécution (job_runs.id) qui a écrit la ligne. Pas de clé étrangère : l'historique
    # des exécutions est purgé bien avant les points (90 jours contre 25 mois).
    run_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


# `Base.metadata.create_all` (base des tests) crée la table partitionnée SANS aucune
# partition : sans la partition par défaut, toute insertion échouerait. La migration
# crée elle-même cette partition et les partitions mensuelles.
event.listen(
    MetricPoint.__table__,
    "after_create",
    DDL(f"CREATE TABLE {DEFAULT_PARTITION} PARTITION OF metric_points DEFAULT"),
)
```

```python
# backend/app/models/metric_rollup.py
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, Double, ForeignKey, Integer, PrimaryKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MetricRollup(Base):
    """Cumul d'une série sur une semaine (lundi) ou un mois (le 1er), recalculé après
    chaque collecte. `days_covered` = nombre de jours ayant une valeur dans la période :
    un cumul partiel se voit, il n'est jamais présenté comme complet."""

    __tablename__ = "metric_rollups"
    __table_args__ = (
        PrimaryKeyConstraint(
            "website_id", "source", "metric", "dim_key", "grain", "period_start"
        ),
    )

    website_id: Mapped[UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(64))
    dim_key: Mapped[str] = mapped_column(String(64))
    grain: Mapped[str] = mapped_column(String(8))
    period_start: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    days_covered: Mapped[int] = mapped_column(Integer, nullable=False)
    dims: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

```python
# backend/app/models/schedule.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Schedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Planning d'un type de tâche pour un site : fréquence choisie, prochaine échéance,
    dernier passage. `kind` et `frequency` sont des chaînes validées par le code
    (`app.services.jobs.kinds`)."""

    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint("website_id", "kind", name="uq_schedules_website_kind"),
        Index("ix_schedules_next_due_at", "next_due_at"),
    )

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Statut du dernier job_run terminé (succeeded | failed | skipped).
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Début de la série d'échecs en cours (vidé au premier succès) : source des alertes.
    failing_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Rattrapage initial (90 jours) réussi : les passages suivants ne collectent que
    # les jours récents.
    backfill_done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

```python
# backend/app/models/job_run.py
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class JobRun(UUIDPrimaryKeyMixin, Base):
    """Une exécution de tâche. `idempotency_key` = « type:site:fenêtre » : deux
    livraisons de la même tâche partagent la même ligne. Le bail (`lease_expires_at`)
    libère une tâche dont le worker est mort. Source des alertes d'exploitation."""

    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_job_runs_idempotency_key"),
        Index("ix_job_runs_status_lease", "status", "lease_expires_at"),
        Index("ix_job_runs_workspace_enqueued", "workspace_id", "enqueued_at"),
        Index("ix_job_runs_website_kind_enqueued", "website_id", "kind", "enqueued_at"),
    )

    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # Null pour les tâches globales (maintenance des partitions).
    website_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=True
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    window_label: Mapped[str] = mapped_column(String(40), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Code stable (jamais un message d'exception, jamais un jeton).
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Nom de classe d'une exception inattendue, pour le diagnostic.
    error_detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    recoverable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

Dans `backend/app/models/__init__.py`, ajouter (ordre alphabétique des modules) :

```python
from app.models.job_run import JobRun
from app.models.metric_point import MetricPoint
from app.models.metric_rollup import MetricRollup
from app.models.schedule import Schedule
```

et dans `__all__` : `"JobRun"` (après `"IssueItem"`), `"MetricPoint"` et
`"MetricRollup"` (après `"MeasurementItemStatus"`), `"Schedule"` (après
`"PasswordResetToken"`).

- [ ] **Étape 3 : écrire la migration**

```python
# backend/alembic/versions/c3a9e5f1b8d2_data_platform.py
"""lot B : metric_points (partitionnée par mois), metric_rollups, schedules, job_runs

Revision ID: c3a9e5f1b8d2
Revises: 8f2a6c41d7b3
Create Date: 2026-09-26 12:00:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a9e5f1b8d2"
down_revision: str | Sequence[str] | None = "8f2a6c41d7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mois créés d'avance : 4 mois passés (le rattrapage initial couvre 90 jours) et 3 à
# venir. Les suivants sont créés par la tâche planifiée `partition_maintenance`.
_MONTHS_BACK = 4
_MONTHS_AHEAD = 3


def _add_months(month: date, count: int) -> date:
    index = month.year * 12 + (month.month - 1) + count
    return date(index // 12, index % 12 + 1, 1)


def upgrade() -> None:
    op.create_table(
        "metric_points",
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("dim_key", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("dims", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_metric_points_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "website_id", "source", "metric", "dim_key", "day", name=op.f("pk_metric_points")
        ),
        postgresql_partition_by="RANGE (day)",
    )
    op.execute("CREATE TABLE metric_points_default PARTITION OF metric_points DEFAULT")
    current = datetime.now(UTC).date().replace(day=1)
    for offset in range(-_MONTHS_BACK, _MONTHS_AHEAD + 1):
        start = _add_months(current, offset)
        end = _add_months(start, 1)
        op.execute(
            f"CREATE TABLE metric_points_p{start:%Y_%m} PARTITION OF metric_points "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )

    op.create_table(
        "metric_rollups",
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("dim_key", sa.String(length=64), nullable=False),
        sa.Column("grain", sa.String(length=8), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("days_covered", sa.Integer(), nullable=False),
        sa.Column("dims", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_metric_rollups_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "website_id",
            "source",
            "metric",
            "dim_key",
            "grain",
            "period_start",
            name=op.f("pk_metric_rollups"),
        ),
    )

    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("frequency", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("backfill_done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_schedules_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
        sa.UniqueConstraint("website_id", "kind", name="uq_schedules_website_kind"),
    )
    op.create_index("ix_schedules_next_due_at", "schedules", ["next_due_at"])

    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("window_label", sa.String(length=40), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enqueued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.String(length=300), nullable=True),
        sa.Column("recoverable", sa.Boolean(), nullable=True),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_job_runs_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_job_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
        sa.UniqueConstraint("idempotency_key", name="uq_job_runs_idempotency_key"),
    )
    op.create_index("ix_job_runs_status_lease", "job_runs", ["status", "lease_expires_at"])
    op.create_index("ix_job_runs_workspace_enqueued", "job_runs", ["workspace_id", "enqueued_at"])
    op.create_index(
        "ix_job_runs_website_kind_enqueued", "job_runs", ["website_id", "kind", "enqueued_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_job_runs_website_kind_enqueued", table_name="job_runs")
    op.drop_index("ix_job_runs_workspace_enqueued", table_name="job_runs")
    op.drop_index("ix_job_runs_status_lease", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_index("ix_schedules_next_due_at", table_name="schedules")
    op.drop_table("schedules")
    op.drop_table("metric_rollups")
    # Supprimer la table partitionnée supprime aussi toutes ses partitions.
    op.drop_table("metric_points")
```

- [ ] **Étape 4 : écarter les partitions de la comparaison `alembic check`**

Dans `backend/alembic/env.py`, ajouter `import re` aux imports standard, puis après
`AUTOGENERATE_PLUGINS = (...)` :

```python
# Les partitions de metric_points (créées par la migration et par la tâche
# `partition_maintenance`) ne sont pas des modèles : sans ce filtre, `alembic check`
# signale chacune comme une table à supprimer (`remove_table`). La table mère, elle,
# reste comparée (colonnes, clé primaire, clé étrangère). tests/test_migrations.py
# vérifie séparément la forme partitionnée.
_METRIC_PARTITION = re.compile(r"^metric_points_(?:default|p\d{4}_\d{2})$")


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    return not (
        type_ == "table"
        and reflected
        and name is not None
        and _METRIC_PARTITION.match(name) is not None
    )
```

et passer `include_object=include_object,` aux **deux** appels `context.configure(...)`
(`run_migrations_offline` et `do_run_migrations`).

- [ ] **Étape 5 : lancer les tests et le contrôle de schéma**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_data_platform_models.py tests/test_migrations.py -v
uv run ruff check app tests
```

Attendu : tous verts, dont `test_models_match_migration` (il échouerait sans le filtre
`include_object` ou si modèle et migration divergent) et
`test_metric_points_is_partitioned_by_month_with_a_default`. Puis la suite complète :
`.venv/Scripts/python.exe -m pytest -W error -q` (aucune régression).

- [ ] **Étape 6 : commit**

```bash
git add backend/app/models backend/alembic/env.py backend/alembic/versions/c3a9e5f1b8d2_data_platform.py backend/tests/test_data_platform_models.py backend/tests/test_migrations.py
git commit -m "feat(donnees): tables metric_points partitionnee, metric_rollups, schedules et job_runs

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 2 : Types de source, registre de métriques, dimensions et agrégation

**Fichiers :**
- Créer : `backend/app/services/metrics/__init__.py`,
  `backend/app/services/metrics/types.py`, `backend/app/services/metrics/registry.py`,
  `backend/app/services/metrics/dimensions.py`,
  `backend/app/services/metrics/aggregate.py`
- Test : `backend/tests/test_metrics_registry.py`,
  `backend/tests/test_metrics_dimensions.py`, `backend/tests/test_metrics_aggregate.py`

**Interfaces :**
- Consomme : `Website` (`app.models.website`).
- Produit (`app.services.metrics.types`) :
  - `utc_today() -> date`, `utc_now() -> datetime`
  - `DayRange(start: date, end: date)` (bornes incluses, `ValueError` si
    `end < start`) avec `.length -> int`, `.days() -> list[date]`,
    `.chunks(size: int) -> list[DayRange]`, `.contains(day: date) -> bool`
  - `Observation(metric: str, day: date, value: float, dims: dict[str, str] = {})` —
    `metric` est le **nom court** (`"sessions"`), la source est portée par l'adaptateur.
  - `SourceError(reason: str, *, recoverable: bool, not_applicable: bool = False)` avec
    attributs `.reason`, `.recoverable`, `.not_applicable` (`not_applicable` force
    `recoverable = False`).
  - `SourceSpec(name, quota_limited, min_interval, freshness_days, refresh_days,
    max_days_per_call, backfill_days, dimensions)` avec
    `.regular_window(today) -> DayRange` et `.backfill_window(today) -> DayRange | None`.
  - `SOURCE_SPECS: dict[str, SourceSpec]` pour `"ga4"`, `"gsc"`, `"cwv"`, `"probe"`.
  - `MetricSource` (Protocol) : attribut `spec: SourceSpec`, méthode
    `async collect(website: Website, day_range: DayRange) -> list[Observation]`.
- Produit (`app.services.metrics.registry`) : `Thresholds(good, poor, drop_alert_pct)`,
  `MetricDef(key, source, name, label, unit, direction, aggregation, dimensions=(),
  top_n=0, ratio_of=None, weight_by=None, thresholds=Thresholds())`, `METRICS`,
  `METRICS_BY_KEY: dict[str, MetricDef]` (clé `"ga4.sessions"`),
  `metric_def(source: str, name: str) -> MetricDef | None`,
  `metrics_for_source(source: str) -> tuple[MetricDef, ...]`.
- Produit (`app.services.metrics.dimensions`) : `clean_page`, `clean_query`,
  `clean_event` (`(str) -> str | None`), `CLEANERS: dict[str, Callable[[str], str |
  None]]` (clés `"page"`, `"query"`, `"event_name"`), `dim_key(dims: Mapping[str, str])
  -> str` (`""` si vide, sinon 32 caractères hexadécimaux stables).
- Produit (`app.services.metrics.aggregate`) : `Grain = Literal["week", "month"]`,
  `GRAINS = ("week", "month")`, `week_start(day)`, `month_start(day)`,
  `period_start(day, grain)`, `period_end(start, grain)` (inclus),
  `periods_between(start, end, grain) -> list[date]`,
  `siblings_needed(defn) -> tuple[str, ...]`,
  `aggregate(defn, values: Mapping[date, float], siblings: Mapping[str, Mapping[date,
  float]] | None = None) -> float | None`.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_metrics_registry.py
from datetime import date, timedelta

import pytest

from app.services.metrics.registry import METRICS, METRICS_BY_KEY, metric_def, metrics_for_source
from app.services.metrics.types import SOURCE_SPECS, DayRange, SourceError


def test_keys_are_unique_and_qualified() -> None:
    assert len(METRICS_BY_KEY) == len(METRICS)
    for metric in METRICS:
        assert metric.key == f"{metric.source}.{metric.name}"
        assert metric.label


def test_dimensions_are_allowed_by_the_source_and_capped() -> None:
    for metric in METRICS:
        spec = SOURCE_SPECS[metric.source]
        assert set(metric.dimensions) <= set(spec.dimensions), metric.key
        assert (metric.top_n > 0) == bool(metric.dimensions), metric.key


def test_ratio_and_weighted_metrics_point_to_sibling_metrics() -> None:
    for metric in METRICS:
        if metric.aggregation == "ratio":
            assert metric.ratio_of is not None
            assert all(metric_def(metric.source, name) for name in metric.ratio_of)
        else:
            assert metric.ratio_of is None
        if metric.aggregation == "weighted_mean":
            assert metric.weight_by is not None
            assert metric_def(metric.source, metric.weight_by) is not None
        else:
            assert metric.weight_by is None


def test_thresholds_follow_the_direction_of_improvement() -> None:
    for metric in METRICS:
        good, poor = metric.thresholds.good, metric.thresholds.poor
        if good is None or poor is None:
            continue
        if metric.direction == "lower_is_better":
            assert good < poor, metric.key
        else:
            assert good > poor, metric.key


def test_lookup_helpers() -> None:
    sessions = metric_def("ga4", "sessions")
    assert sessions is not None and sessions.key == "ga4.sessions"
    assert metric_def("ga4", "inconnue") is None
    assert {m.name for m in metrics_for_source("gsc")} >= {"clicks", "impressions", "ctr", "position"}
    # Les utilisateurs ne s'additionnent pas d'un jour à l'autre : pas de métrique « users ».
    assert not any("user" in m.name for m in METRICS)


def test_source_specs_carry_the_floors_and_backfill() -> None:
    assert SOURCE_SPECS["ga4"].min_interval == timedelta(hours=8)
    assert SOURCE_SPECS["gsc"].min_interval == timedelta(hours=8)
    assert SOURCE_SPECS["cwv"].min_interval == timedelta(hours=8)
    assert SOURCE_SPECS["probe"].min_interval == timedelta(hours=1)
    assert SOURCE_SPECS["ga4"].backfill_days == 90
    assert SOURCE_SPECS["gsc"].backfill_days == 90
    assert SOURCE_SPECS["cwv"].backfill_window(date(2026, 9, 26)) is None


def test_day_range_helpers() -> None:
    window = DayRange(date(2026, 9, 1), date(2026, 9, 3))
    assert window.length == 3
    assert window.days() == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    assert window.chunks(2) == [
        DayRange(date(2026, 9, 1), date(2026, 9, 2)),
        DayRange(date(2026, 9, 3), date(2026, 9, 3)),
    ]
    assert window.contains(date(2026, 9, 2)) and not window.contains(date(2026, 9, 4))
    with pytest.raises(ValueError):
        DayRange(date(2026, 9, 3), date(2026, 9, 1))


def test_regular_and_backfill_windows_respect_freshness() -> None:
    today = date(2026, 9, 26)
    assert SOURCE_SPECS["ga4"].regular_window(today) == DayRange(date(2026, 9, 23), date(2026, 9, 25))
    assert SOURCE_SPECS["gsc"].regular_window(today) == DayRange(date(2026, 9, 21), date(2026, 9, 23))
    assert SOURCE_SPECS["probe"].regular_window(today) == DayRange(today, today)
    backfill = SOURCE_SPECS["ga4"].backfill_window(today)
    assert backfill is not None and backfill.length == 90 and backfill.end == date(2026, 9, 25)


def test_not_applicable_is_never_recoverable() -> None:
    error = SourceError("ga4_not_connected", recoverable=True, not_applicable=True)
    assert error.reason == "ga4_not_connected"
    assert error.not_applicable is True and error.recoverable is False
```

```python
# backend/tests/test_metrics_dimensions.py
import pytest

from app.services.metrics.dimensions import CLEANERS, clean_event, clean_page, clean_query, dim_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://boutique.fr/produits/chaise?utm_source=x#avis", "/produits/chaise"),
        ("https://boutique.fr", "/"),
        ("/panier?id=42", "/panier"),
        ("contact", "/contact"),
        ("https://boutique.fr/compte/jean.dupont%40gmail.com", None),
        ("   ", None),
    ],
)
def test_clean_page_keeps_only_the_path(raw: str, expected: str | None) -> None:
    assert clean_page(raw) == expected


def test_clean_page_truncates_long_paths() -> None:
    cleaned = clean_page("/" + "a" * 500)
    assert cleaned is not None and len(cleaned) == 200


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Chaise EN Chêne ", "chaise en chêne"),
        ("jean.dupont@gmail.com", None),
        ("appeler 06 12 34 56 78", None),
        ("commande 123456789", None),
        ("", None),
    ],
)
def test_clean_query_drops_personal_data(raw: str, expected: str | None) -> None:
    assert clean_query(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("purchase", "purchase"), ("generate_lead", "generate_lead"), ("nom invalide !", None), ("", None)],
)
def test_clean_event_accepts_only_ga4_names(raw: str, expected: str | None) -> None:
    assert clean_event(raw) == expected


def test_cleaners_are_idempotent() -> None:
    for name, cleaner in CLEANERS.items():
        sample = {"page": "https://x.fr/a/b?q=1", "query": " Chaise ", "event_name": "purchase"}[name]
        once = cleaner(sample)
        assert once is not None and cleaner(once) == once


def test_dim_key_is_stable_and_empty_for_totals() -> None:
    assert dim_key({}) == ""
    first = dim_key({"page": "/a"})
    assert first == dim_key({"page": "/a"}) and len(first) == 32
    assert first != dim_key({"page": "/b"})
    assert dim_key({"page": "/a"}) != dim_key({"query": "/a"})
```

```python
# backend/tests/test_metrics_aggregate.py
from datetime import date

import pytest

from app.services.metrics.aggregate import (
    aggregate,
    month_start,
    period_end,
    period_start,
    periods_between,
    siblings_needed,
    week_start,
)
from app.services.metrics.registry import METRICS_BY_KEY

D1, D2, D3 = date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)


def test_periods() -> None:
    assert week_start(date(2026, 9, 24)) == date(2026, 9, 21)  # un lundi
    assert month_start(date(2026, 9, 24)) == date(2026, 9, 1)
    assert period_start(date(2026, 9, 24), "week") == date(2026, 9, 21)
    assert period_end(date(2026, 9, 21), "week") == date(2026, 9, 27)
    assert period_end(date(2026, 2, 1), "month") == date(2026, 2, 28)
    assert period_end(date(2026, 12, 1), "month") == date(2026, 12, 31)
    assert periods_between(date(2026, 9, 25), date(2026, 10, 6), "week") == [
        date(2026, 9, 21),
        date(2026, 9, 28),
        date(2026, 10, 5),
    ]
    assert periods_between(date(2026, 9, 25), date(2026, 11, 2), "month") == [
        date(2026, 9, 1),
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]


def test_sum_mean_and_last() -> None:
    values = {D1: 2.0, D2: 4.0, D3: 9.0}
    assert aggregate(METRICS_BY_KEY["ga4.sessions"], values) == 15.0
    assert aggregate(METRICS_BY_KEY["probe.page_up"], {D1: 1.0, D2: 0.0}) == 0.5
    assert aggregate(METRICS_BY_KEY["cwv.lcp_p75_ms"], values) == 9.0
    assert aggregate(METRICS_BY_KEY["ga4.sessions"], {}) is None


def test_ratio_is_computed_from_the_sums() -> None:
    ctr = METRICS_BY_KEY["gsc.ctr"]
    assert siblings_needed(ctr) == ("clicks", "impressions")
    siblings = {"clicks": {D1: 10.0, D2: 30.0}, "impressions": {D1: 100.0, D2: 300.0, D3: 50.0}}
    # Seuls les jours présents des deux côtés comptent : 40 / 400.
    assert aggregate(ctr, {D1: 0.1, D2: 0.1}, siblings) == pytest.approx(0.1)
    assert aggregate(ctr, {}, {"clicks": {D1: 1.0}, "impressions": {D1: 0.0}}) is None


def test_weighted_mean_uses_the_weight_metric() -> None:
    position = METRICS_BY_KEY["gsc.position"]
    assert siblings_needed(position) == ("impressions",)
    values = {D1: 10.0, D2: 20.0}
    siblings = {"impressions": {D1: 100.0, D2: 300.0}}
    assert aggregate(position, values, siblings) == pytest.approx(17.5)
    assert aggregate(position, values, {"impressions": {}}) is None
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_metrics_registry.py tests/test_metrics_dimensions.py tests/test_metrics_aggregate.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.services.metrics'`).

- [ ] **Étape 2 : écrire les types**

```python
# backend/app/services/metrics/__init__.py
"""Socle de données : sources de métriques, registre, stockage idempotent, cumuls,
partitions et lecture des séries temporelles (lot B)."""
```

```python
# backend/app/services/metrics/types.py
"""Contrat commun des sources de métriques (`MetricSource`) et de leurs observations.

Une observation est `(métrique, jour, valeur, dimensions)` ; le site et la source sont
portés par l'appelant. Une source en erreur lève `SourceError` : elle ne renvoie jamais
une valeur inventée ni un zéro de remplacement."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.models.website import Website


def utc_today() -> date:
    return datetime.now(UTC).date()


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DayRange:
    """Fenêtre de jours, bornes incluses."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("fenêtre vide : la fin précède le début")

    @property
    def length(self) -> int:
        return (self.end - self.start).days + 1

    def days(self) -> list[date]:
        return [self.start + timedelta(days=offset) for offset in range(self.length)]

    def chunks(self, size: int) -> list[DayRange]:
        if size < 1:
            raise ValueError("le pas de découpage doit être positif")
        parts: list[DayRange] = []
        cursor = self.start
        while cursor <= self.end:
            last = min(cursor + timedelta(days=size - 1), self.end)
            parts.append(DayRange(cursor, last))
            cursor = last + timedelta(days=1)
        return parts

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True, slots=True)
class Observation:
    metric: str
    day: date
    value: float
    dims: dict[str, str] = field(default_factory=dict)


class SourceError(Exception):
    """Échec typé d'une source.

    - `not_applicable` : rien à collecter (source non reliée, site archivé). La tâche est
      « ignorée », jamais une alerte, jamais retentée.
    - `recoverable` : une nouvelle tentative a du sens (quota, réseau, 5xx, réponse de
      forme inattendue). Sinon l'échec est définitif pour cette exécution (droits, jeton).
    """

    def __init__(self, reason: str, *, recoverable: bool, not_applicable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.not_applicable = not_applicable
        self.recoverable = recoverable and not not_applicable


@dataclass(frozen=True, slots=True)
class SourceSpec:
    name: str
    # Source à quota (Google) : plancher de fréquence de 8 h.
    quota_limited: bool
    min_interval: timedelta
    # Retard des données : dernier jour fiable = aujourd'hui - freshness_days.
    freshness_days: int
    # Jours récents recollectés à chaque passage (GA4 révise les 48 dernières heures).
    refresh_days: int
    # Pas de découpage d'une fenêtre (une requête par tranche).
    max_days_per_call: int
    # Rattrapage initial en jours ; 0 = aucun.
    backfill_days: int
    # Dimensions permises (une seule par observation).
    dimensions: tuple[str, ...]

    def _last_day(self, today: date) -> date:
        return today - timedelta(days=self.freshness_days)

    def regular_window(self, today: date) -> DayRange:
        end = self._last_day(today)
        return DayRange(end - timedelta(days=self.refresh_days - 1), end)

    def backfill_window(self, today: date) -> DayRange | None:
        if self.backfill_days <= 0:
            return None
        end = self._last_day(today)
        return DayRange(end - timedelta(days=self.backfill_days - 1), end)


SOURCE_SPECS: dict[str, SourceSpec] = {
    "ga4": SourceSpec(
        name="ga4",
        quota_limited=True,
        min_interval=timedelta(hours=8),
        freshness_days=1,
        refresh_days=3,
        max_days_per_call=31,
        backfill_days=90,
        dimensions=("event_name",),
    ),
    "gsc": SourceSpec(
        name="gsc",
        quota_limited=True,
        min_interval=timedelta(hours=8),
        freshness_days=3,
        refresh_days=3,
        max_days_per_call=31,
        backfill_days=90,
        dimensions=("page", "query"),
    ),
    # PageSpeed a un quota et CrUX n'évolue qu'une fois par jour : plancher de 8 h.
    "cwv": SourceSpec(
        name="cwv",
        quota_limited=True,
        min_interval=timedelta(hours=8),
        freshness_days=0,
        refresh_days=1,
        max_days_per_call=1,
        backfill_days=0,
        dimensions=(),
    ),
    "probe": SourceSpec(
        name="probe",
        quota_limited=False,
        min_interval=timedelta(hours=1),
        freshness_days=0,
        refresh_days=1,
        max_days_per_call=1,
        backfill_days=0,
        dimensions=(),
    ),
}


class MetricSource(Protocol):
    spec: SourceSpec

    async def collect(self, website: Website, day_range: DayRange) -> list[Observation]: ...
```

- [ ] **Étape 3 : écrire le registre de métriques**

```python
# backend/app/services/metrics/registry.py
"""Registre de métriques en code : unité, sens d'amélioration, dimensions permises,
agrégation et seuils de chaque métrique stockée. Le code décide : aucun seuil ni statut
ne vient d'un modèle de langage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Unit = Literal["count", "currency", "ratio", "position", "ms", "score", "days", "unitless"]
Direction = Literal["higher_is_better", "lower_is_better", "neutral"]
Aggregation = Literal["sum", "mean", "last", "ratio", "weighted_mean"]

# Plafond de valeurs de dimension conservées par jour (pages, requêtes, événements).
TOP_N = 25


@dataclass(frozen=True, slots=True)
class Thresholds:
    # Seuil « bon » (inclus) et seuil « mauvais » (au-delà, dans le sens défavorable).
    good: float | None = None
    poor: float | None = None
    # Baisse relative (en %) par rapport à la période précédente jugée anormale.
    drop_alert_pct: float | None = None


@dataclass(frozen=True, slots=True)
class MetricDef:
    key: str
    source: str
    name: str
    label: str
    unit: Unit
    direction: Direction
    aggregation: Aggregation
    dimensions: tuple[str, ...] = ()
    top_n: int = 0
    # Ratio : (numérateur, dénominateur), noms courts de la même source.
    ratio_of: tuple[str, str] | None = None
    # Moyenne pondérée : nom court de la métrique servant de poids.
    weight_by: str | None = None
    thresholds: Thresholds = field(default_factory=Thresholds)


def _metric(source: str, name: str, label: str, unit: Unit, direction: Direction,
            aggregation: Aggregation, **extra: object) -> MetricDef:
    return MetricDef(
        key=f"{source}.{name}",
        source=source,
        name=name,
        label=label,
        unit=unit,
        direction=direction,
        aggregation=aggregation,
        **extra,  # type: ignore[arg-type]
    )


METRICS: tuple[MetricDef, ...] = (
    _metric("ga4", "sessions", "Sessions", "count", "higher_is_better", "sum",
            thresholds=Thresholds(drop_alert_pct=40.0)),
    _metric("ga4", "screen_page_views", "Pages vues", "count", "higher_is_better", "sum"),
    _metric("ga4", "engaged_sessions", "Sessions avec engagement", "count",
            "higher_is_better", "sum"),
    _metric("ga4", "key_events", "Événements clés (conversions)", "count",
            "higher_is_better", "sum", thresholds=Thresholds(drop_alert_pct=50.0)),
    _metric("ga4", "total_revenue", "Revenu total", "currency", "higher_is_better", "sum"),
    _metric("ga4", "event_count", "Nombre d'événements", "count", "neutral", "sum",
            dimensions=("event_name",), top_n=TOP_N),
    _metric("gsc", "clicks", "Clics depuis la recherche Google", "count",
            "higher_is_better", "sum", dimensions=("page", "query"), top_n=TOP_N,
            thresholds=Thresholds(drop_alert_pct=40.0)),
    _metric("gsc", "impressions", "Impressions dans la recherche Google", "count",
            "higher_is_better", "sum", dimensions=("page", "query"), top_n=TOP_N),
    _metric("gsc", "ctr", "Taux de clic", "ratio", "higher_is_better", "ratio",
            ratio_of=("clicks", "impressions")),
    _metric("gsc", "position", "Position moyenne", "position", "lower_is_better",
            "weighted_mean", weight_by="impressions"),
    _metric("cwv", "lcp_p75_ms", "LCP des visiteurs réels (75e centile)", "ms",
            "lower_is_better", "last", thresholds=Thresholds(good=2500.0, poor=4000.0)),
    _metric("cwv", "inp_p75_ms", "INP des visiteurs réels (75e centile)", "ms",
            "lower_is_better", "last", thresholds=Thresholds(good=200.0, poor=500.0)),
    _metric("cwv", "cls_p75", "CLS des visiteurs réels (75e centile)", "unitless",
            "lower_is_better", "last", thresholds=Thresholds(good=0.1, poor=0.25)),
    _metric("cwv", "performance_score", "Score de performance (laboratoire)", "score",
            "higher_is_better", "last", thresholds=Thresholds(good=90.0, poor=50.0)),
    _metric("probe", "tls_days_remaining", "Jours avant expiration du certificat HTTPS",
            "days", "higher_is_better", "last", thresholds=Thresholds(good=30.0, poor=7.0)),
    _metric("probe", "page_up", "Page d'accueil joignable (dernier contrôle du jour)",
            "ratio", "higher_is_better", "mean", thresholds=Thresholds(good=1.0, poor=0.9)),
)

METRICS_BY_KEY: dict[str, MetricDef] = {metric.key: metric for metric in METRICS}
_BY_SOURCE_AND_NAME: dict[tuple[str, str], MetricDef] = {
    (metric.source, metric.name): metric for metric in METRICS
}


def metric_def(source: str, name: str) -> MetricDef | None:
    return _BY_SOURCE_AND_NAME.get((source, name))


def metrics_for_source(source: str) -> tuple[MetricDef, ...]:
    return tuple(metric for metric in METRICS if metric.source == source)
```

- [ ] **Étape 4 : écrire le nettoyage des dimensions**

```python
# backend/app/services/metrics/dimensions.py
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
```

- [ ] **Étape 5 : écrire l'agrégation (pure)**

```python
# backend/app/services/metrics/aggregate.py
"""Agrégation pure d'une série journalière selon le registre (cumuls semaine/mois,
totaux de l'API de séries). Aucune période sans donnée ne produit de valeur : None."""

from __future__ import annotations

import calendar
from collections.abc import Mapping
from datetime import date, timedelta
from statistics import fmean
from typing import Literal

from app.services.metrics.registry import MetricDef

Grain = Literal["week", "month"]
GRAINS: tuple[Grain, ...] = ("week", "month")


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def month_start(day: date) -> date:
    return day.replace(day=1)


def period_start(day: date, grain: Grain) -> date:
    return week_start(day) if grain == "week" else month_start(day)


def period_end(start: date, grain: Grain) -> date:
    if grain == "week":
        return start + timedelta(days=6)
    return start.replace(day=calendar.monthrange(start.year, start.month)[1])


def periods_between(start: date, end: date, grain: Grain) -> list[date]:
    periods: list[date] = []
    cursor = period_start(start, grain)
    while cursor <= end:
        periods.append(cursor)
        cursor = period_end(cursor, grain) + timedelta(days=1)
    return periods


def siblings_needed(defn: MetricDef) -> tuple[str, ...]:
    if defn.aggregation == "ratio" and defn.ratio_of is not None:
        return defn.ratio_of
    if defn.aggregation == "weighted_mean" and defn.weight_by is not None:
        return (defn.weight_by,)
    return ()


def aggregate(
    defn: MetricDef,
    values: Mapping[date, float],
    siblings: Mapping[str, Mapping[date, float]] | None = None,
) -> float | None:
    siblings = siblings or {}
    if defn.aggregation == "sum":
        return float(sum(values.values())) if values else None
    if defn.aggregation == "mean":
        return fmean(values.values()) if values else None
    if defn.aggregation == "last":
        return float(values[max(values)]) if values else None
    if defn.aggregation == "ratio" and defn.ratio_of is not None:
        numerator = siblings.get(defn.ratio_of[0], {})
        denominator = siblings.get(defn.ratio_of[1], {})
        days = numerator.keys() & denominator.keys()
        total = sum(denominator[day] for day in days)
        if not days or total == 0:
            return None
        return sum(numerator[day] for day in days) / total
    if defn.aggregation == "weighted_mean" and defn.weight_by is not None:
        weights = siblings.get(defn.weight_by, {})
        days = values.keys() & weights.keys()
        total = sum(weights[day] for day in days)
        if not days or total == 0:
            return None
        return sum(values[day] * weights[day] for day in days) / total
    return None
```

- [ ] **Étape 6 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_metrics_registry.py tests/test_metrics_dimensions.py tests/test_metrics_aggregate.py -v
uv run ruff check app tests
```

Attendu : tous verts, ruff propre.

- [ ] **Étape 7 : commit**

```bash
git add backend/app/services/metrics backend/tests/test_metrics_registry.py backend/tests/test_metrics_dimensions.py backend/tests/test_metrics_aggregate.py
git commit -m "feat(donnees): contrat MetricSource, registre de metriques, nettoyage des dimensions et agregation

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 3 : Stockage idempotent, plafond top N et cumuls semaine/mois

**Fichiers :**
- Créer : `backend/app/services/metrics/store.py`
- Test : `backend/tests/test_metrics_store.py`

**Interfaces :**
- Consomme : `MetricPoint`, `MetricRollup` (Tâche 1) ; `Observation` (types),
  `metric_def` (registre), `CLEANERS`, `dim_key` (dimensions), `GRAINS`, `aggregate`,
  `period_start`, `period_end`, `siblings_needed` (agrégation) — Tâche 2.
- Produit (`app.services.metrics.store`) :
  - `StoreResult(written: int, dropped: int, days: frozenset[date])`
  - `lock_metrics(session, website_id: UUID, source: str) -> None` (verrou consultatif
    transactionnel `metrics:{website_id}:{source}`)
  - `prepare_rows(*, website_id, source, observations, run_id, now) ->
    tuple[list[dict[str, Any]], int]` (pure : validation, nettoyage, top N ; renvoie les
    lignes et le nombre d'observations écartées)
  - `store_observations(session, *, website_id: UUID, source: str, observations:
    Sequence[Observation], run_id: UUID | None, now: datetime) -> StoreResult` — ne
    committe pas ; remplace, pour chaque couple (métrique, jour) présent, l'ensemble
    des lignes de ce jour (un jour absent de la collecte n'est jamais effacé), puis
    recalcule les cumuls.
  - `refresh_rollups(session, *, website_id, source, days: Iterable[date], now) -> int`
    (nombre de lignes de cumul écrites).

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_metrics_store.py
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import MetricPoint
from app.models.metric_rollup import MetricRollup
from app.models.website import Website
from app.services.metrics.store import prepare_rows, store_observations
from app.services.metrics.types import Observation
from tests.conftest import owner_workspace_id

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
MON, TUE = date(2026, 9, 21), date(2026, 9, 22)


def _obs(metric: str, day: date, value: float, **dims: str) -> Observation:
    return Observation(metric, day, value, dict(dims))


async def _site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"store-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


async def _points(db_session: AsyncSession, website_id) -> list[tuple]:
    rows = await db_session.execute(
        select(
            MetricPoint.source, MetricPoint.metric, MetricPoint.dims, MetricPoint.day,
            MetricPoint.value,
        )
        .where(MetricPoint.website_id == website_id)
        .order_by(MetricPoint.metric, MetricPoint.day, MetricPoint.dim_key)
    )
    return [tuple(row) for row in rows.all()]


async def _rollups(db_session: AsyncSession, website_id) -> dict[tuple[str, str, date], tuple]:
    rows = await db_session.execute(
        select(MetricRollup).where(MetricRollup.website_id == website_id, MetricRollup.dim_key == "")
    )
    return {
        (r.metric, r.grain, r.period_start): (r.value, r.days_covered) for r in rows.scalars()
    }


def test_prepare_rows_validates_and_cleans() -> None:
    observations = [
        _obs("sessions", MON, 10),
        _obs("inconnue", MON, 1),  # métrique hors registre
        _obs("sessions", TUE, float("nan")),  # valeur non finie
        _obs("event_count", MON, 5, event_name="purchase"),
        _obs("event_count", MON, 3, event_name="nom invalide !"),  # nom GA4 invalide
        _obs("event_count", MON, 2, page="/x"),  # dimension non permise pour GA4
    ]
    rows, dropped = prepare_rows(
        website_id=uuid4(), source="ga4", observations=observations, run_id=None, now=NOW
    )
    assert dropped == 4
    assert [(r["metric"], r["dims"], r["day"]) for r in rows] == [
        ("event_count", {"event_name": "purchase"}, MON),
        ("sessions", {}, MON),
    ]
    assert rows[1]["dim_key"] == "" and rows[0]["dim_key"] != ""


def test_prepare_rows_keeps_the_top_n_per_day_and_dimension() -> None:
    observations = [_obs("clicks", MON, float(i), page=f"/p{i:02d}") for i in range(30)]
    observations.append(_obs("clicks", MON, 99.0))  # le total n'est jamais plafonné
    rows, dropped = prepare_rows(
        website_id=uuid4(), source="gsc", observations=observations, run_id=None, now=NOW
    )
    assert dropped == 5
    pages = {r["dims"]["page"] for r in rows if r["dims"]}
    assert pages == {f"/p{i:02d}" for i in range(5, 30)}
    assert any(r["dims"] == {} and r["value"] == 99.0 for r in rows)


def test_prepare_rows_cleans_pages_before_capping() -> None:
    observations = [_obs("clicks", MON, 3.0, page="https://x.fr/panier?id=1")]
    rows, dropped = prepare_rows(
        website_id=uuid4(), source="gsc", observations=observations, run_id=None, now=NOW
    )
    assert dropped == 0 and rows[0]["dims"] == {"page": "/panier"}


async def test_storing_the_same_observations_twice_gives_the_same_rows(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-idem.test")
    run_id = uuid4()
    observations = [
        _obs("clicks", MON, 4, page="/a"),
        _obs("clicks", MON, 2, page="/b"),
        _obs("clicks", MON, 6),
        _obs("impressions", MON, 60),
    ]
    first = await store_observations(
        db_session, website_id=site.id, source="gsc", observations=observations,
        run_id=run_id, now=NOW,
    )
    snapshot = await _points(db_session, site.id)
    second = await store_observations(
        db_session, website_id=site.id, source="gsc", observations=observations,
        run_id=run_id, now=NOW,
    )
    assert await _points(db_session, site.id) == snapshot
    assert first.written == second.written == 4
    assert first.days == frozenset({MON})
    stored_run = await db_session.scalar(
        select(MetricPoint.run_id).where(MetricPoint.website_id == site.id).limit(1)
    )
    assert stored_run == run_id


async def test_a_replay_removes_dimension_rows_that_left_the_top(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-replay.test")
    await store_observations(
        db_session, website_id=site.id, source="gsc",
        observations=[_obs("clicks", MON, 4, page="/a"), _obs("clicks", MON, 2, page="/b")],
        run_id=None, now=NOW,
    )
    await store_observations(
        db_session, website_id=site.id, source="gsc",
        observations=[_obs("clicks", MON, 5, page="/a")], run_id=None, now=NOW,
    )
    assert await _points(db_session, site.id) == [
        ("gsc", "clicks", {"page": "/a"}, MON, 5.0)
    ]


async def test_a_day_missing_from_a_new_collection_is_kept(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-keep.test")
    await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[_obs("sessions", MON, 3), _obs("sessions", TUE, 4)],
        run_id=None, now=NOW,
    )
    await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[_obs("sessions", TUE, 5)], run_id=None, now=NOW,
    )
    values = {row[3]: row[4] for row in await _points(db_session, site.id)}
    assert values == {MON: 3.0, TUE: 5.0}


async def test_rollups_use_the_registry_aggregations(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-rollup.test")
    observations = [
        _obs("clicks", MON, 10), _obs("clicks", TUE, 30),
        _obs("impressions", MON, 100), _obs("impressions", TUE, 300),
        _obs("ctr", MON, 0.1), _obs("ctr", TUE, 0.1),
        _obs("position", MON, 10.0), _obs("position", TUE, 20.0),
    ]
    await store_observations(
        db_session, website_id=site.id, source="gsc", observations=observations,
        run_id=None, now=NOW,
    )
    rollups = await _rollups(db_session, site.id)
    week, month = date(2026, 9, 21), date(2026, 9, 1)
    for grain, start in (("week", week), ("month", month)):
        assert rollups[("clicks", grain, start)] == (40.0, 2)
        assert rollups[("impressions", grain, start)] == (400.0, 2)
        assert rollups[("ctr", grain, start)][0] == pytest.approx(0.1)
        # Moyenne pondérée par les impressions : (10*100 + 20*300) / 400.
        assert rollups[("position", grain, start)][0] == pytest.approx(17.5)


async def test_rollups_are_recomputed_after_a_replay(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-rollup-replay.test")
    for value in (3.0, 8.0):
        await store_observations(
            db_session, website_id=site.id, source="ga4",
            observations=[_obs("sessions", MON, value), _obs("sessions", TUE, 1.0)],
            run_id=None, now=NOW,
        )
    rollups = await _rollups(db_session, site.id)
    assert rollups[("sessions", "week", date(2026, 9, 21))] == (9.0, 2)
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_metrics_store.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.services.metrics.store'`).

- [ ] **Étape 2 : écrire le stockage**

```python
# backend/app/services/metrics/store.py
"""Stockage idempotent des observations et recalcul des cumuls.

Règles :
- une observation hors registre, avec une dimension non permise, une valeur de
  dimension écartée par le nettoyage ou une valeur non finie est ignorée (et comptée) ;
- chaque dimension est plafonnée à `top_n` valeurs par jour (les plus fortes) ;
- rejouer un jour remplace exactement les lignes de ce couple (métrique, jour) : un
  même jeu d'observations donne toujours les mêmes lignes ; un jour absent de la
  collecte n'est jamais effacé ;
- le verrou (site, source) est pris AVANT toute lecture ou écriture.
Aucune fonction ne committe : l'appelant décide de la transaction."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import MetricPoint
from app.models.metric_rollup import MetricRollup
from app.services.metrics.aggregate import (
    GRAINS,
    aggregate,
    period_end,
    period_start,
    siblings_needed,
)
from app.services.metrics.dimensions import CLEANERS, dim_key
from app.services.metrics.registry import MetricDef, metric_def
from app.services.metrics.types import Observation

_BATCH = 1000
_POINT_KEY = ["website_id", "source", "metric", "dim_key", "day"]


@dataclass(frozen=True, slots=True)
class StoreResult:
    written: int
    dropped: int
    days: frozenset[date]


async def lock_metrics(session: AsyncSession, website_id: UUID, source: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"metrics:{website_id}:{source}"},
    )


def _batches(rows: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    for index in range(0, len(rows), _BATCH):
        yield rows[index : index + _BATCH]


def _rank(row: dict[str, Any]) -> tuple[float, str]:
    """Valeur décroissante, puis valeur de dimension croissante (ordre déterministe)."""
    return (-row["value"], next(iter(row["dims"].values())))


def _clean_dims(defn: MetricDef, dims: dict[str, str]) -> dict[str, str] | None:
    if not dims:
        return {}
    if len(dims) != 1:
        return None
    ((name, raw),) = dims.items()
    if name not in defn.dimensions or not isinstance(raw, str):
        return None
    cleaned = CLEANERS[name](raw)
    return {name: cleaned} if cleaned is not None else None


def prepare_rows(
    *,
    website_id: UUID,
    source: str,
    observations: Sequence[Observation],
    run_id: UUID | None,
    now: datetime,
) -> tuple[list[dict[str, Any]], int]:
    dropped = 0
    kept: dict[tuple[str, str, date], dict[str, Any]] = {}
    for obs in observations:
        defn = metric_def(source, obs.metric)
        value = obs.value
        if defn is None or not isinstance(value, int | float) or not math.isfinite(value):
            dropped += 1
            continue
        dims = _clean_dims(defn, obs.dims)
        if dims is None:
            dropped += 1
            continue
        key = dim_key(dims)
        kept[(obs.metric, key, obs.day)] = {
            "website_id": website_id,
            "source": source,
            "metric": obs.metric,
            "dim_key": key,
            "day": obs.day,
            "value": float(value),
            "dims": dims,
            "collected_at": now,
            "run_id": run_id,
        }

    rows: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, date], list[dict[str, Any]]] = defaultdict(list)
    for row in kept.values():
        if not row["dims"]:
            rows.append(row)
            continue
        name = next(iter(row["dims"]))
        groups[(row["metric"], name, row["day"])].append(row)
    for (metric, _name, _day), members in groups.items():
        cap = metric_def(source, metric).top_n  # type: ignore[union-attr]
        members.sort(key=_rank)
        rows.extend(members[:cap])
        dropped += max(0, len(members) - cap)
    rows.sort(key=lambda r: (r["metric"], r["day"], r["dim_key"]))
    return rows, dropped


async def store_observations(
    session: AsyncSession,
    *,
    website_id: UUID,
    source: str,
    observations: Sequence[Observation],
    run_id: UUID | None,
    now: datetime,
) -> StoreResult:
    rows, dropped = prepare_rows(
        website_id=website_id, source=source, observations=observations, run_id=run_id, now=now
    )
    if not rows:
        return StoreResult(written=0, dropped=dropped, days=frozenset())
    await lock_metrics(session, website_id, source)
    pairs = sorted({(row["metric"], row["day"]) for row in rows})
    await session.execute(
        delete(MetricPoint).where(
            MetricPoint.website_id == website_id,
            MetricPoint.source == source,
            tuple_(MetricPoint.metric, MetricPoint.day).in_(pairs),
        )
    )
    for chunk in _batches(rows):
        statement = pg_insert(MetricPoint).values(chunk)
        statement = statement.on_conflict_do_update(
            index_elements=_POINT_KEY,
            set_={
                "value": statement.excluded.value,
                "dims": statement.excluded.dims,
                "collected_at": statement.excluded.collected_at,
                "run_id": statement.excluded.run_id,
            },
        )
        await session.execute(statement)
    days = frozenset(day for _, day in pairs)
    await refresh_rollups(session, website_id=website_id, source=source, days=days, now=now)
    return StoreResult(written=len(rows), dropped=dropped, days=days)


async def refresh_rollups(
    session: AsyncSession,
    *,
    website_id: UUID,
    source: str,
    days: Iterable[date],
    now: datetime,
) -> int:
    """Recalcule entièrement les cumuls des semaines et mois touchés par `days`, à partir
    de tous les points de ces périodes (idempotent : supprimer puis réécrire)."""
    wanted = set(days)
    if not wanted:
        return 0
    written = 0
    for grain in GRAINS:
        starts = sorted({period_start(day, grain) for day in wanted})
        start_set = set(starts)
        low, high = starts[0], period_end(starts[-1], grain)
        result = await session.execute(
            select(
                MetricPoint.metric, MetricPoint.dim_key, MetricPoint.day, MetricPoint.value,
                MetricPoint.dims,
            ).where(
                MetricPoint.website_id == website_id,
                MetricPoint.source == source,
                MetricPoint.day >= low,
                MetricPoint.day <= high,
            )
        )
        series: dict[tuple[str, str, date], dict[date, float]] = defaultdict(dict)
        labels: dict[tuple[str, date], dict[str, str]] = {}
        for metric, key, day, value, dims in result.all():
            start = period_start(day, grain)
            if start not in start_set:
                continue
            series[(metric, key, start)][day] = value
            labels[(key, start)] = dims
        await session.execute(
            delete(MetricRollup).where(
                MetricRollup.website_id == website_id,
                MetricRollup.source == source,
                MetricRollup.grain == grain,
                MetricRollup.period_start.in_(starts),
            )
        )
        rows: list[dict[str, Any]] = []
        for (metric, key, start), values in series.items():
            defn = metric_def(source, metric)
            if defn is None:
                continue
            siblings = {name: series.get((name, key, start), {}) for name in siblings_needed(defn)}
            value = aggregate(defn, values, siblings)
            if value is None or not math.isfinite(value):
                continue
            rows.append(
                {
                    "website_id": website_id,
                    "source": source,
                    "metric": metric,
                    "dim_key": key,
                    "grain": grain,
                    "period_start": start,
                    "value": value,
                    "days_covered": len(values),
                    "dims": labels[(key, start)],
                    "updated_at": now,
                }
            )
        for chunk in _batches(rows):
            await session.execute(insert(MetricRollup).values(chunk))
        written += len(rows)
    return written
```

- [ ] **Étape 3 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_metrics_store.py -v
uv run ruff check app tests
```

Attendu : tous verts.

- [ ] **Étape 4 : commit**

```bash
git add backend/app/services/metrics/store.py backend/tests/test_metrics_store.py
git commit -m "feat(donnees): stockage idempotent des observations, plafond top N et cumuls semaine/mois

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 4 : Partitions mensuelles (création d'avance, sortie de la partition par défaut, purge à 25 mois)

**Fichiers :**
- Créer : `backend/app/services/metrics/partitions.py`
- Test : `backend/tests/test_metrics_partitions.py`

**Interfaces :**
- Consomme : `DEFAULT_PARTITION`, `MetricPoint` (Tâche 1) ; `month_start` (Tâche 2).
- Produit (`app.services.metrics.partitions`) :
  - `RETENTION_MONTHS = 25`
  - `add_months(month: date, count: int) -> date` (premier du mois)
  - `partition_name(month: date) -> str` (`"metric_points_p2026_09"`)
  - `Partition(name: str, start: date | None, end: date | None)` (`None` = partition
    par défaut ; `end` exclu)
  - `list_partitions(session) -> list[Partition]`
  - `ensure_partitions(session, *, today: date, months_back: int = 4, months_ahead:
    int = 3) -> list[str]` (noms créés, idempotent ; déplace vers la nouvelle
    partition les lignes du mois restées dans la partition par défaut)
  - `PurgeResult(dropped: tuple[str, ...], deleted_default_rows: int)`
  - `purge_expired(session, *, today: date, retention_months: int = RETENTION_MONTHS)
    -> PurgeResult` (idempotent)
  - Aucune fonction ne committe ; l'appelant prend le verrou de maintenance (Tâche 11).

- [ ] **Étape 1 : écrire les tests qui échouent**

Les instructions DDL de PostgreSQL sont transactionnelles : chaque test crée et
supprime des partitions dans la transaction de `db_session`, annulée à la fin du test
(la base de test ne garde que la partition par défaut créée par `create_all`).

```python
# backend/tests/test_metrics_partitions.py
from datetime import UTC, date, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import DEFAULT_PARTITION, MetricPoint
from app.models.website import Website
from app.services.metrics.partitions import (
    add_months,
    ensure_partitions,
    list_partitions,
    partition_name,
    purge_expired,
)
from tests.conftest import owner_workspace_id

TODAY = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)


async def _site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"part-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


def _point(site: Website, day: date) -> MetricPoint:
    return MetricPoint(
        website_id=site.id, source="ga4", metric="sessions", dim_key="", day=day,
        value=1.0, dims={}, collected_at=NOW,
    )


async def _partition_of(db_session: AsyncSession, day: date) -> str:
    return await db_session.scalar(
        text("SELECT tableoid::regclass::text FROM metric_points WHERE day = :day"),
        {"day": day},
    )


def test_month_arithmetic_and_names() -> None:
    assert add_months(date(2026, 9, 1), 4) == date(2027, 1, 1)
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert partition_name(date(2026, 9, 1)) == "metric_points_p2026_09"


async def test_ensure_partitions_creates_the_window_once(db_session: AsyncSession) -> None:
    created = await ensure_partitions(db_session, today=TODAY)
    assert created == [
        "metric_points_p2026_05",
        "metric_points_p2026_06",
        "metric_points_p2026_07",
        "metric_points_p2026_08",
        "metric_points_p2026_09",
        "metric_points_p2026_10",
        "metric_points_p2026_11",
        "metric_points_p2026_12",
    ]
    assert await ensure_partitions(db_session, today=TODAY) == []
    partitions = {p.name: p for p in await list_partitions(db_session)}
    assert partitions[DEFAULT_PARTITION].start is None
    assert partitions["metric_points_p2026_09"].start == date(2026, 9, 1)
    assert partitions["metric_points_p2026_09"].end == date(2026, 10, 1)


async def test_rows_waiting_in_the_default_partition_move_to_their_month(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "part-move.test")
    db_session.add(_point(site, date(2027, 2, 10)))
    await db_session.flush()
    assert await _partition_of(db_session, date(2027, 2, 10)) == DEFAULT_PARTITION

    created = await ensure_partitions(db_session, today=TODAY, months_back=0, months_ahead=5)
    assert "metric_points_p2027_02" in created
    assert await _partition_of(db_session, date(2027, 2, 10)) == "metric_points_p2027_02"
    # Déplacée, pas copiée : une seule ligne au total.
    count = await db_session.scalar(
        select(func.count()).select_from(MetricPoint).where(MetricPoint.website_id == site.id)
    )
    assert count == 1


async def test_purge_drops_expired_partitions_and_old_default_rows(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "part-purge.test")
    await ensure_partitions(db_session, today=date(2024, 5, 10), months_back=0, months_ahead=0)
    db_session.add_all([_point(site, date(2024, 3, 15)), _point(site, date(2026, 9, 20))])
    await db_session.flush()

    result = await purge_expired(db_session, today=TODAY)
    assert result.dropped == ("metric_points_p2024_05",)
    assert result.deleted_default_rows == 1  # le 2024-03-15, plus vieux que 25 mois
    days = (
        await db_session.execute(select(MetricPoint.day).where(MetricPoint.website_id == site.id))
    ).scalars().all()
    assert days == [date(2026, 9, 20)]

    again = await purge_expired(db_session, today=TODAY)
    assert again.dropped == () and again.deleted_default_rows == 0
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_metrics_partitions.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.services.metrics.partitions'`).

- [ ] **Étape 2 : écrire la gestion des partitions**

```python
# backend/app/services/metrics/partitions.py
"""Partitions mensuelles de `metric_points`.

- `ensure_partitions` crée d'avance les mois manquants autour d'aujourd'hui. Si des
  lignes de ce mois attendent dans la partition par défaut, PostgreSQL refuse de créer
  la partition (« updated partition constraint for default partition would be violated
  ») : on crée donc une table vide de même forme, on y déplace ces lignes, puis on
  l'attache. La partition par défaut est verrouillée pendant l'opération, ce qui
  empêche une collecte concurrente d'y écrire une ligne du même mois entre-temps.
- `purge_expired` détache et supprime les partitions entièrement plus vieilles que la
  rétention (25 mois, comparaison annuelle), et purge la partition par défaut au-delà.
Les noms de tables sont construits par le code à partir de dates et vérifiés par
expression régulière : aucune valeur extérieure n'entre dans le SQL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import DEFAULT_PARTITION
from app.services.metrics.aggregate import month_start

RETENTION_MONTHS = 25
_NAME = re.compile(r"^metric_points_p\d{4}_\d{2}$")
_BOUNDS = re.compile(r"FOR VALUES FROM \('(\d{4}-\d{2}-\d{2})'\) TO \('(\d{4}-\d{2}-\d{2})'\)")


@dataclass(frozen=True, slots=True)
class Partition:
    name: str
    start: date | None
    end: date | None


@dataclass(frozen=True, slots=True)
class PurgeResult:
    dropped: tuple[str, ...]
    deleted_default_rows: int


def add_months(month: date, count: int) -> date:
    index = month.year * 12 + (month.month - 1) + count
    return date(index // 12, index % 12 + 1, 1)


def partition_name(month: date) -> str:
    return f"metric_points_p{month:%Y_%m}"


def _checked(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"nom de partition inattendu : {name}")
    return name


async def list_partitions(session: AsyncSession) -> list[Partition]:
    rows = await session.execute(
        text(
            "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) "
            "FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "WHERE p.relname = 'metric_points' ORDER BY c.relname"
        )
    )
    partitions: list[Partition] = []
    for name, bound in rows.all():
        match = _BOUNDS.search(bound or "")
        if match is None:
            partitions.append(Partition(name=name, start=None, end=None))
        else:
            partitions.append(
                Partition(
                    name=name,
                    start=date.fromisoformat(match.group(1)),
                    end=date.fromisoformat(match.group(2)),
                )
            )
    return partitions


async def _create_partition(session: AsyncSession, start: date) -> str:
    end = add_months(start, 1)
    name = _checked(partition_name(start))
    await session.execute(text(f"LOCK TABLE {DEFAULT_PARTITION} IN ACCESS EXCLUSIVE MODE"))
    await session.execute(
        text(f"CREATE TABLE {name} (LIKE metric_points INCLUDING DEFAULTS INCLUDING CONSTRAINTS)")
    )
    await session.execute(
        text(
            f"WITH moved AS (DELETE FROM {DEFAULT_PARTITION} "
            "WHERE day >= :start AND day < :end RETURNING *) "
            f"INSERT INTO {name} SELECT * FROM moved"
        ),
        {"start": start, "end": end},
    )
    await session.execute(
        text(
            f"ALTER TABLE metric_points ATTACH PARTITION {name} "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )
    )
    return name


async def ensure_partitions(
    session: AsyncSession, *, today: date, months_back: int = 4, months_ahead: int = 3
) -> list[str]:
    existing = {p.start for p in await list_partitions(session) if p.start is not None}
    current = month_start(today)
    created: list[str] = []
    for offset in range(-months_back, months_ahead + 1):
        start = add_months(current, offset)
        if start in existing:
            continue
        created.append(await _create_partition(session, start))
    return created


async def purge_expired(
    session: AsyncSession, *, today: date, retention_months: int = RETENTION_MONTHS
) -> PurgeResult:
    cutoff = add_months(month_start(today), -retention_months)
    dropped: list[str] = []
    for partition in await list_partitions(session):
        if partition.end is None or partition.end > cutoff:
            continue
        name = _checked(partition.name)
        await session.execute(text(f"ALTER TABLE metric_points DETACH PARTITION {name}"))
        await session.execute(text(f"DROP TABLE {name}"))
        dropped.append(name)
    result = await session.execute(
        text(f"DELETE FROM {DEFAULT_PARTITION} WHERE day < :cutoff"), {"cutoff": cutoff}
    )
    return PurgeResult(dropped=tuple(dropped), deleted_default_rows=result.rowcount or 0)
```

- [ ] **Étape 3 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_metrics_partitions.py tests/test_metrics_store.py -v
uv run ruff check app tests
```

Attendu : tous verts.

- [ ] **Étape 4 : commit**

```bash
git add backend/app/services/metrics/partitions.py backend/tests/test_metrics_partitions.py
git commit -m "feat(donnees): partitions mensuelles de metric_points (creation, deplacement depuis la partition par defaut, purge a 25 mois)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 5 : Adaptateurs GA4 Data et Search Console

**Fichiers :**
- Créer : `backend/app/services/metrics/sources/__init__.py`,
  `backend/app/services/metrics/sources/google_http.py`,
  `backend/app/services/metrics/sources/ga4.py`,
  `backend/app/services/metrics/sources/gsc.py`,
  `backend/app/services/metrics/sources/credentials.py`
- Test : `backend/tests/test_metrics_sources_google.py`

**Interfaces :**
- Consomme : `Observation`, `DayRange`, `SourceError`, `SOURCE_SPECS` (Tâche 2) ;
  `metric_def` (registre) ; `clean_event`, `CLEANERS` (dimensions) ;
  `_RUN_REPORT_URL`, `_property_number` (`app.services.ga4`) ; `_QUERY_URL`
  (`app.services.gsc`) ; `_raise_for_status`, `GoogleReadError`
  (`app.services.measurement.google_reader`) ; `build_reader`
  (`app.services.measurement.google_access`).
- Produit :
  - `google_json(method: str, url: str, token: str, *, json: dict | None = None,
    client: httpx.AsyncClient | None = None) -> Any` (`sources.google_http`) : erreurs
    HTTP et réseau converties en `SourceError` ; `RECOVERABLE_REASONS: dict[str, bool]`.
  - `Ga4Source(*, property_id: str | None, token: str | None, client=None)` avec
    `spec = SOURCE_SPECS["ga4"]` ; `parse_totals(payload) -> list[Observation]`,
    `parse_events(payload, *, top_n: int) -> list[Observation]` (`sources.ga4`).
    Raisons : `ga4_not_connected` (non concerné), `token_unavailable`,
    `permission_or_api_disabled`, `not_found` (définitives), `quota`, `network`,
    `api_error` (récupérables).
  - `GscSource(*, site_url: str | None, token: str | None, client=None)` avec
    `spec = SOURCE_SPECS["gsc"]` ; `parse_totals(payload)`,
    `parse_dimension(payload, dimension: str, *, top_n: int)` (`sources.gsc`). Raison
    « non concerné » : `gsc_not_connected`.
  - `GoogleCredentials(ga4_property, ga4_token, gsc_site, gsc_token)` (jetons exclus du
    `repr`) et `resolve_google_credentials(session, website, *, oauth, cipher) ->
    GoogleCredentials` (`sources.credentials`) — réutilise `build_reader` (lecture des
    liaisons + rafraîchissement des jetons) ; peut passer une connexion à
    `needs_reauth` (l'appelant committe).

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_metrics_sources_google.py
import json
from datetime import date

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import ResourceType
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import (
    DiscoveredResources,
    GoogleTokenResponse,
    GoogleUserInfo,
)
from app.services.metrics.sources.credentials import resolve_google_credentials
from app.services.metrics.sources.ga4 import Ga4Source, parse_events, parse_totals
from app.services.metrics.sources.gsc import GscSource, parse_dimension
from app.services.metrics.types import DayRange, Observation, SourceError
from tests.conftest import owner_workspace_id
from tests.measurement_fakes import FakeOAuth

SITE = Website(domain="exemple.fr", display_name="Exemple")
WINDOW = DayRange(date(2026, 9, 20), date(2026, 9, 21))

_GA4_HEADERS = [
    {"name": n, "type": "TYPE_INTEGER"}
    for n in ("sessions", "screenPageViews", "engagedSessions", "keyEvents", "totalRevenue")
]


def _ga4_totals(*days: tuple[str, list[str]]) -> dict:
    return {
        "dimensionHeaders": [{"name": "date"}],
        "metricHeaders": _GA4_HEADERS,
        "rows": [
            {"dimensionValues": [{"value": day}], "metricValues": [{"value": v} for v in values]}
            for day, values in days
        ],
    }


def _ga4_events(*rows: tuple[str, str, str]) -> dict:
    return {
        "metricHeaders": [{"name": "eventCount", "type": "TYPE_INTEGER"}],
        "rows": [
            {
                "dimensionValues": [{"value": day}, {"value": name}],
                "metricValues": [{"value": count}],
            }
            for day, name, count in rows
        ],
    }


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_ga4_totals_are_read_by_header_name() -> None:
    observations = parse_totals(_ga4_totals(("20260920", ["12", "30", "8", "2", "99.5"])))
    values = {o.metric: o.value for o in observations}
    assert values == {
        "sessions": 12.0,
        "screen_page_views": 30.0,
        "engaged_sessions": 8.0,
        "key_events": 2.0,
        "total_revenue": 99.5,
    }
    assert {o.day for o in observations} == {date(2026, 9, 20)}


def test_ga4_empty_report_gives_no_observation_never_zero() -> None:
    assert parse_totals({"metricHeaders": _GA4_HEADERS}) == []


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"rows": "pas une liste", "metricHeaders": _GA4_HEADERS},
        {"rows": [{"dimensionValues": [{"value": "20260920"}]}], "metricHeaders": _GA4_HEADERS},
        _ga4_totals(("2026-09-20", ["1", "1", "1", "1", "1"])),
        _ga4_totals(("20260920", ["un", "1", "1", "1", "1"])),
        {"rows": _ga4_totals(("20260920", ["1"] * 5))["rows"], "metricHeaders": []},
    ],
)
def test_ga4_unexpected_shapes_are_recoverable_errors(payload) -> None:
    with pytest.raises(SourceError) as excinfo:
        parse_totals(payload)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


def test_ga4_events_are_cleaned_merged_and_capped() -> None:
    observations = parse_events(
        _ga4_events(
            ("20260920", "purchase", "3"),
            ("20260920", "page_view", "40"),
            ("20260920", "nom invalide !", "99"),
            ("20260920", "scroll", "40"),
        ),
        top_n=2,
    )
    assert [(o.dims["event_name"], o.value) for o in observations] == [
        ("page_view", 40.0),
        ("scroll", 40.0),
    ]


async def test_ga4_source_chunks_the_window_and_keeps_only_its_days() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["Authorization"] == "Bearer jeton"
        assert request.url.path == "/v1beta/properties/42:runReport"
        if len(body["dimensions"]) == 1:
            return httpx.Response(200, json=_ga4_totals(("20260920", ["5"] * 5), ("20260101", ["7"] * 5)))
        return httpx.Response(200, json=_ga4_events(("20260920", "purchase", "1")))

    source = Ga4Source(property_id="properties/42", token="jeton", client=_client(handler))
    window = DayRange(date(2026, 8, 1), date(2026, 9, 20))  # 51 jours -> 2 tranches
    observations = await source.collect(SITE, window)
    assert len(seen) == 4
    assert seen[0]["dateRanges"] == [{"startDate": "2026-08-01", "endDate": "2026-08-31"}]
    assert seen[2]["dateRanges"] == [{"startDate": "2026-09-01", "endDate": "2026-09-20"}]
    assert all(window.contains(o.day) for o in observations)
    assert any(o.metric == "event_count" for o in observations)


async def test_ga4_source_without_property_is_not_applicable() -> None:
    with pytest.raises(SourceError) as excinfo:
        await Ga4Source(property_id=None, token=None).collect(SITE, WINDOW)
    assert excinfo.value.reason == "ga4_not_connected" and excinfo.value.not_applicable


@pytest.mark.parametrize(
    ("status", "reason", "recoverable"),
    [
        (401, "token_unavailable", False),
        (403, "permission_or_api_disabled", False),
        (404, "not_found", False),
        (429, "quota", True),
        (503, "api_error", True),
    ],
)
async def test_ga4_http_errors_are_classified(status: int, reason: str, recoverable: bool) -> None:
    source = Ga4Source(
        property_id="properties/42",
        token="jeton",
        client=_client(lambda request: httpx.Response(status, json={"error": {}})),
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, WINDOW)
    assert (excinfo.value.reason, excinfo.value.recoverable) == (reason, recoverable)


async def test_ga4_network_error_is_recoverable_and_hides_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    source = Ga4Source(property_id="properties/42", token="jeton-secret", client=_client(handler))
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, WINDOW)
    assert excinfo.value.reason == "network" and excinfo.value.recoverable
    assert "jeton-secret" not in repr(excinfo.value)


def _gsc(*rows: dict) -> dict:
    return {"rows": list(rows), "responseAggregationType": "byProperty"}


def test_gsc_dimension_rows_are_cleaned_merged_and_capped() -> None:
    payload = _gsc(
        {"keys": ["2026-09-20", "https://exemple.fr/a?utm=1"], "clicks": 2, "impressions": 10, "ctr": 0.2, "position": 3},
        {"keys": ["2026-09-20", "http://exemple.fr/a"], "clicks": 3, "impressions": 20, "ctr": 0.15, "position": 4},
        {"keys": ["2026-09-20", "https://exemple.fr/b"], "clicks": 1, "impressions": 90, "ctr": 0.01, "position": 9},
        {"keys": ["2026-09-20", "https://exemple.fr/c"], "clicks": 0, "impressions": 5, "ctr": 0, "position": 30},
    )
    observations = parse_dimension(payload, "page", top_n=2)
    assert observations == [
        Observation("clicks", date(2026, 9, 20), 5.0, {"page": "/a"}),
        Observation("impressions", date(2026, 9, 20), 30.0, {"page": "/a"}),
        Observation("clicks", date(2026, 9, 20), 1.0, {"page": "/b"}),
        Observation("impressions", date(2026, 9, 20), 90.0, {"page": "/b"}),
    ]


def test_gsc_personal_queries_are_dropped() -> None:
    payload = _gsc(
        {"keys": ["2026-09-20", "jean.dupont@gmail.com"], "clicks": 9, "impressions": 9, "ctr": 1, "position": 1},
        {"keys": ["2026-09-20", "chaise chêne"], "clicks": 1, "impressions": 4, "ctr": 0.25, "position": 2},
    )
    queries = {o.dims["query"] for o in parse_dimension(payload, "query", top_n=25)}
    assert queries == {"chaise chêne"}


async def test_gsc_source_reads_totals_pages_and_queries() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        assert "sc-domain%3Aexemple.fr" in str(request.url)
        if body["dimensions"] == ["date"]:
            return httpx.Response(
                200,
                json=_gsc({"keys": ["2026-09-20"], "clicks": 4, "impressions": 40, "ctr": 0.1, "position": 7.5}),
            )
        return httpx.Response(200, json=_gsc())

    source = GscSource(site_url="sc-domain:exemple.fr", token="jeton", client=_client(handler))
    observations = await source.collect(SITE, WINDOW)
    assert [b["dimensions"] for b in bodies] == [["date"], ["date", "page"], ["date", "query"]]
    assert all(b["dataState"] == "final" and b["rowLimit"] == 25000 for b in bodies)
    assert {o.metric: o.value for o in observations} == {
        "clicks": 4.0, "impressions": 40.0, "ctr": 0.1, "position": 7.5,
    }


async def test_gsc_unexpected_shape_is_recoverable() -> None:
    source = GscSource(
        site_url="sc-domain:exemple.fr",
        token="jeton",
        client=_client(lambda request: httpx.Response(200, json={"rows": [{"keys": "x"}]})),
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, WINDOW)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


async def test_gsc_without_site_is_not_applicable() -> None:
    with pytest.raises(SourceError) as excinfo:
        await GscSource(site_url=None, token=None).collect(SITE, WINDOW)
    assert excinfo.value.reason == "gsc_not_connected" and excinfo.value.not_applicable


async def test_credentials_come_from_the_site_links(db_session: AsyncSession, make_user) -> None:
    user = await make_user(sub="cred-owner")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain="cred.test", display_name="cred")
    db_session.add(site)
    await db_session.flush()
    cipher = load_token_cipher(get_settings())
    connection = await upsert_google_connection(
        db_session,
        workspace_id=workspace_id,
        userinfo=GoogleUserInfo(sub="g-cred", email="cred@gmail.com"),
        token=GoogleTokenResponse(
            access_token="a", expires_in=3600, scopes=("openid",), refresh_token="r"
        ),
        cipher=cipher,
    )
    db_session.add_all(
        [
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=connection.id,
                resource_type=ResourceType.GA4_PROPERTY,
                resource_id="properties/42",
            ),
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=connection.id,
                resource_type=ResourceType.GSC_SITE,
                resource_id="sc-domain:cred.test",
            ),
        ]
    )
    await db_session.flush()
    oauth = FakeOAuth(DiscoveredResources(ga4_properties=(), gsc_sites=()))
    credentials = await resolve_google_credentials(db_session, site, oauth=oauth, cipher=cipher)
    assert credentials.ga4_property == "properties/42" and credentials.ga4_token == "tok"
    assert credentials.gsc_site == "sc-domain:cred.test" and credentials.gsc_token == "tok"
    assert "tok" not in repr(credentials)


async def test_credentials_of_an_unlinked_site_are_empty(db_session: AsyncSession, make_user) -> None:
    user = await make_user(sub="cred-none")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain="cred-none.test", display_name="x")
    db_session.add(site)
    await db_session.flush()
    oauth = FakeOAuth(DiscoveredResources(ga4_properties=(), gsc_sites=()))
    credentials = await resolve_google_credentials(
        db_session, site, oauth=oauth, cipher=load_token_cipher(get_settings())
    )
    assert credentials.ga4_property is None and credentials.gsc_site is None
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_metrics_sources_google.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.services.metrics.sources'`).

- [ ] **Étape 2 : écrire le client HTTP Google commun**

```python
# backend/app/services/metrics/sources/__init__.py
"""Adaptateurs `MetricSource` : GA4 Data, Search Console, PageSpeed/CrUX, sondes."""
```

```python
# backend/app/services/metrics/sources/google_http.py
"""Appel JSON authentifié vers une API Google, erreurs converties en `SourceError`.

Réutilise la correspondance statut HTTP -> raison du lecteur Google du plan de mesure
(`_raise_for_status`). Le jeton n'apparaît jamais dans une erreur : les exceptions
httpx (qui portent la requête) sont remplacées, pas chaînées."""

from __future__ import annotations

from typing import Any

import httpx

from app.services.measurement.google_reader import GoogleReadError, _raise_for_status
from app.services.metrics.types import SourceError

_TIMEOUT = httpx.Timeout(30.0)

# Raison -> nouvelle tentative utile ?
RECOVERABLE_REASONS: dict[str, bool] = {
    "token_unavailable": False,
    "permission_or_api_disabled": False,
    "not_found": False,
    "quota": True,
    "network": True,
    "api_error": True,
}


async def google_json(
    method: str,
    url: str,
    token: str,
    *,
    json: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> Any:
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        try:
            response = await http.request(
                method, url, json=json, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError:
            raise SourceError("network", recoverable=True) from None
    finally:
        if owns:
            await http.aclose()
    try:
        _raise_for_status(response)
    except GoogleReadError as exc:
        raise SourceError(exc.reason, recoverable=RECOVERABLE_REASONS.get(exc.reason, True)) from None
    try:
        return response.json()
    except ValueError:
        raise SourceError("api_error", recoverable=True) from None
```

- [ ] **Étape 3 : écrire l'adaptateur GA4**

```python
# backend/app/services/metrics/sources/ga4.py
"""Source GA4 Data API (`runReport`) : totaux journaliers et événements (top N par jour).

Les métriques sont lues par NOM d'en-tête (`metricHeaders`), jamais par position
supposée. Un jour absent de la réponse reste absent (GA4 omet les jours sans donnée :
on n'invente pas de zéro). Toute forme inattendue lève `SourceError("api_error")`."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime
from typing import Any

import httpx

from app.models.website import Website
from app.services.ga4 import _RUN_REPORT_URL, _property_number
from app.services.metrics.dimensions import clean_event
from app.services.metrics.registry import metric_def
from app.services.metrics.sources.google_http import google_json
from app.services.metrics.types import SOURCE_SPECS, DayRange, Observation, SourceError, SourceSpec

# Nom court (registre) -> nom de la métrique GA4.
TOTALS: dict[str, str] = {
    "sessions": "sessions",
    "screen_page_views": "screenPageViews",
    "engaged_sessions": "engagedSessions",
    "key_events": "keyEvents",
    "total_revenue": "totalRevenue",
}
EVENT_TOP_N = metric_def("ga4", "event_count").top_n  # type: ignore[union-attr]


def _api_error() -> SourceError:
    return SourceError("api_error", recoverable=True)


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise _api_error()
    rows = payload.get("rows", [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise _api_error()
    return rows


def _metric_index(payload: dict[str, Any]) -> dict[str, int]:
    headers = payload.get("metricHeaders")
    if not isinstance(headers, list):
        raise _api_error()
    index: dict[str, int] = {}
    for position, header in enumerate(headers):
        if not isinstance(header, dict) or not isinstance(header.get("name"), str):
            raise _api_error()
        index[header["name"]] = position
    return index


def _cells(row: dict[str, Any], key: str, count: int) -> list[str]:
    cells = row.get(key)
    if not isinstance(cells, list) or len(cells) < count:
        raise _api_error()
    values: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict) or not isinstance(cell.get("value"), str):
            raise _api_error()
        values.append(cell["value"])
    return values


def _day(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        raise _api_error() from None


def _number(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise _api_error() from None
    if not math.isfinite(value):
        raise _api_error()
    return value


def parse_totals(payload: Any) -> list[Observation]:
    rows = _rows(payload)
    if not rows:
        return []
    index = _metric_index(payload)
    if any(api_name not in index for api_name in TOTALS.values()):
        raise _api_error()
    observations: list[Observation] = []
    for row in rows:
        day = _day(_cells(row, "dimensionValues", 1)[0])
        metrics = _cells(row, "metricValues", len(index))
        for name, api_name in TOTALS.items():
            observations.append(Observation(name, day, _number(metrics[index[api_name]])))
    return observations


def parse_events(payload: Any, *, top_n: int) -> list[Observation]:
    rows = _rows(payload)
    if not rows:
        return []
    index = _metric_index(payload)
    if "eventCount" not in index:
        raise _api_error()
    per_day: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        raw_day, raw_name = _cells(row, "dimensionValues", 2)[:2]
        day = _day(raw_day)
        count = _number(_cells(row, "metricValues", len(index))[index["eventCount"]])
        name = clean_event(raw_name)
        if name is not None:
            per_day[day][name] += count
    observations: list[Observation] = []
    for day in sorted(per_day):
        ranked = sorted(per_day[day].items(), key=lambda item: (-item[1], item[0]))[:top_n]
        observations.extend(
            Observation("event_count", day, count, {"event_name": name}) for name, count in ranked
        )
    return observations


class Ga4Source:
    spec: SourceSpec = SOURCE_SPECS["ga4"]

    def __init__(
        self,
        *,
        property_id: str | None,
        token: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._property_id = property_id
        self._token = token
        self._client = client

    async def collect(self, website: Website, day_range: DayRange) -> list[Observation]:
        _ = website
        if not self._property_id:
            raise SourceError("ga4_not_connected", recoverable=False, not_applicable=True)
        if not self._token:
            raise SourceError("token_unavailable", recoverable=False)
        url = _RUN_REPORT_URL.format(pid=_property_number(self._property_id))
        observations: list[Observation] = []
        for chunk in day_range.chunks(self.spec.max_days_per_call):
            date_ranges = [{"startDate": chunk.start.isoformat(), "endDate": chunk.end.isoformat()}]
            totals = await google_json(
                "POST",
                url,
                self._token,
                json={
                    "dateRanges": date_ranges,
                    "dimensions": [{"name": "date"}],
                    "metrics": [{"name": api_name} for api_name in TOTALS.values()],
                    "limit": 1000,
                },
                client=self._client,
            )
            observations.extend(parse_totals(totals))
            events = await google_json(
                "POST",
                url,
                self._token,
                json={
                    "dateRanges": date_ranges,
                    "dimensions": [{"name": "date"}, {"name": "eventName"}],
                    "metrics": [{"name": "eventCount"}],
                    "limit": 25000,
                },
                client=self._client,
            )
            observations.extend(parse_events(events, top_n=EVENT_TOP_N))
        return [obs for obs in observations if day_range.contains(obs.day)]
```

- [ ] **Étape 4 : écrire l'adaptateur Search Console**

```python
# backend/app/services/metrics/sources/gsc.py
"""Source Search Console (Search Analytics) : totaux journaliers (clics, impressions,
CTR, position) puis top N pages et requêtes par jour (clics et impressions).

Les pages sont réduites au chemin (plusieurs URL peuvent donner le même chemin : on
additionne) ; les requêtes personnelles sont écartées (voir `dimensions.py`). Seules les
données finales sont lues (`dataState: final`)."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from app.models.website import Website
from app.services.gsc import _QUERY_URL
from app.services.metrics.dimensions import CLEANERS
from app.services.metrics.registry import metric_def
from app.services.metrics.sources.google_http import google_json
from app.services.metrics.types import SOURCE_SPECS, DayRange, Observation, SourceError, SourceSpec

_ROW_LIMIT = 25000
DIMENSION_TOP_N = metric_def("gsc", "clicks").top_n  # type: ignore[union-attr]
_TOTAL_FIELDS = ("clicks", "impressions", "ctr", "position")


def _api_error() -> SourceError:
    return SourceError("api_error", recoverable=True)


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise _api_error()
    rows = payload.get("rows", [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise _api_error()
    return rows


def _keys(row: dict[str, Any], count: int) -> list[str]:
    keys = row.get("keys")
    if (
        not isinstance(keys, list)
        or len(keys) < count
        or not all(isinstance(key, str) for key in keys)
    ):
        raise _api_error()
    return keys


def _day(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _api_error() from None


def _number(row: dict[str, Any], field: str) -> float:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise _api_error()
    return float(value)


def parse_totals(payload: Any) -> list[Observation]:
    observations: list[Observation] = []
    for row in _rows(payload):
        day = _day(_keys(row, 1)[0])
        observations.extend(Observation(name, day, _number(row, name)) for name in _TOTAL_FIELDS)
    return observations


def parse_dimension(payload: Any, dimension: str, *, top_n: int) -> list[Observation]:
    cleaner = CLEANERS[dimension]
    merged: dict[date, dict[str, list[float]]] = defaultdict(dict)
    for row in _rows(payload):
        raw_day, raw_value = _keys(row, 2)[:2]
        day = _day(raw_day)
        clicks, impressions = _number(row, "clicks"), _number(row, "impressions")
        value = cleaner(raw_value)
        if value is None:
            continue
        slot = merged[day].setdefault(value, [0.0, 0.0])
        slot[0] += clicks
        slot[1] += impressions
    observations: list[Observation] = []
    for day in sorted(merged):
        ranked = sorted(
            merged[day].items(), key=lambda item: (-item[1][0], -item[1][1], item[0])
        )[:top_n]
        for value, (clicks, impressions) in ranked:
            observations.append(Observation("clicks", day, clicks, {dimension: value}))
            observations.append(Observation("impressions", day, impressions, {dimension: value}))
    return observations


class GscSource:
    spec: SourceSpec = SOURCE_SPECS["gsc"]

    def __init__(
        self,
        *,
        site_url: str | None,
        token: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._site_url = site_url
        self._token = token
        self._client = client

    async def _query(self, chunk: DayRange, dimensions: list[str]) -> Any:
        return await google_json(
            "POST",
            _QUERY_URL.format(site=quote(self._site_url or "", safe="")),
            self._token or "",
            json={
                "startDate": chunk.start.isoformat(),
                "endDate": chunk.end.isoformat(),
                "dimensions": dimensions,
                "rowLimit": _ROW_LIMIT,
                "dataState": "final",
            },
            client=self._client,
        )

    async def collect(self, website: Website, day_range: DayRange) -> list[Observation]:
        _ = website
        if not self._site_url:
            raise SourceError("gsc_not_connected", recoverable=False, not_applicable=True)
        if not self._token:
            raise SourceError("token_unavailable", recoverable=False)
        observations: list[Observation] = []
        for chunk in day_range.chunks(self.spec.max_days_per_call):
            observations.extend(parse_totals(await self._query(chunk, ["date"])))
            for dimension in ("page", "query"):
                payload = await self._query(chunk, ["date", dimension])
                observations.extend(parse_dimension(payload, dimension, top_n=DIMENSION_TOP_N))
        return [obs for obs in observations if day_range.contains(obs.day)]
```

- [ ] **Étape 5 : écrire la résolution des jetons**

```python
# backend/app/services/metrics/sources/credentials.py
"""Jetons GA4 / Search Console d'un site, à partir de ses liaisons Google.

Réutilise `build_reader` du plan de mesure (même logique que l'audit : une connexion
révoquée passe à `needs_reauth`, que l'appelant committe). Les jetons restent en
mémoire et sont exclus du `repr` (jamais dans un log)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website import Website
from app.security.token_crypto import TokenCipher
from app.services.google_oauth import GoogleOAuthClient
from app.services.measurement.google_access import build_reader


@dataclass(frozen=True, slots=True)
class GoogleCredentials:
    ga4_property: str | None
    ga4_token: str | None = field(repr=False)
    gsc_site: str | None
    gsc_token: str | None = field(repr=False)


async def resolve_google_credentials(
    session: AsyncSession,
    website: Website,
    *,
    oauth: GoogleOAuthClient,
    cipher: TokenCipher,
) -> GoogleCredentials:
    reader = await build_reader(session, website, oauth=oauth, cipher=cipher)
    return GoogleCredentials(
        ga4_property=reader.ga4_property,
        ga4_token=reader.ga4_token,
        gsc_site=reader.gsc_site,
        gsc_token=reader.gsc_token,
    )
```

(Le champ `gsc_site` sans valeur par défaut placé après un champ `field(repr=False)`
sans valeur par défaut est valide : aucun des deux n'a de défaut.)

- [ ] **Étape 6 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_metrics_sources_google.py -v
uv run ruff check app tests
```

Attendu : tous verts.

- [ ] **Étape 7 : commit**

```bash
git add backend/app/services/metrics/sources backend/tests/test_metrics_sources_google.py
git commit -m "feat(donnees): adaptateurs GA4 Data et Search Console (lecture seule, erreurs typees, dimensions nettoyees)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 6 : Adaptateurs Core Web Vitals (CrUX via PageSpeed) et sondes (TLS, disponibilité)

**Fichiers :**
- Créer : `backend/app/services/metrics/sources/cwv.py`,
  `backend/app/services/metrics/sources/probes.py`
- Test : `backend/tests/test_metrics_sources_cwv_probes.py`

**Interfaces :**
- Consomme : `Observation`, `DayRange`, `SourceError`, `SOURCE_SPECS`, `utc_today`
  (Tâche 2) ; `PAGESPEED_URL`, `_field_percentile` (`app.services.pagespeed`) ;
  `TlsChecker` (`app.services.audit_engine`) ; `TlsStatus` (`app.services.tls_check`) ;
  `PageFetcher` (`app.services.measurement.fetch`).
- Produit :
  - `parse_cwv(payload, *, day: date) -> list[Observation]` et
    `CwvSource(*, api_key: str | None, client=None, today=utc_today)` avec
    `spec = SOURCE_SPECS["cwv"]` (`sources.cwv`). Observations : `lcp_p75_ms`,
    `inp_p75_ms`, `cls_p75` (terrain, origine) et `performance_score` (labo), datées du
    jour de collecte ; fenêtre qui n'inclut pas aujourd'hui ⇒ `[]` sans appel réseau.
    Raisons : `quota`, `network`, `api_error` (récupérables), `site_unreachable`,
    `permission_or_api_disabled` (définitives).
  - `ProbeSource(*, tls_checker: TlsChecker, page_fetcher: PageFetcher,
    today=utc_today)` avec `spec = SOURCE_SPECS["probe"]` (`sources.probes`).
    Observations : `tls_days_remaining`, `page_up`. Rien d'observable ⇒
    `SourceError("unreachable", recoverable=True)`.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_metrics_sources_cwv_probes.py
from datetime import UTC, date, datetime

import httpx
import pytest

from app.models.website import Website
from app.services.metrics.sources.cwv import CwvSource, parse_cwv
from app.services.metrics.sources.probes import ProbeSource
from app.services.metrics.types import DayRange, Observation, SourceError
from app.services.page_fetch import PageSnapshot
from app.services.tls_check import TlsStatus

TODAY = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
SITE = Website(domain="exemple.fr", display_name="Exemple", allow_insecure_probe=False)
TODAY_ONLY = DayRange(TODAY, TODAY)


def _payload(*, origin: dict | None = None, score: float | None = 0.72) -> dict:
    payload: dict = {"lighthouseResult": {"categories": {"performance": {"score": score}}}}
    if origin is not None:
        payload["originLoadingExperience"] = {"metrics": origin}
    # Données de la page seule : jamais lues (la valeur terrain est celle de l'origine).
    payload["loadingExperience"] = {
        "metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 99999}}
    }
    return payload


_ORIGIN = {
    "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2300},
    "INTERACTION_TO_NEXT_PAINT": {"percentile": 180},
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5},
}


def test_parse_cwv_reads_origin_field_data_and_lab_score() -> None:
    observations = parse_cwv(_payload(origin=_ORIGIN), day=TODAY)
    assert {o.metric: o.value for o in observations} == {
        "lcp_p75_ms": 2300.0,
        "inp_p75_ms": 180.0,
        "cls_p75": 0.05,
        "performance_score": 72.0,
    }


def test_parse_cwv_without_field_data_gives_no_field_observation() -> None:
    observations = parse_cwv(_payload(origin=None, score=None), day=TODAY)
    assert observations == []


def test_parse_cwv_rejects_a_non_object() -> None:
    with pytest.raises(SourceError) as excinfo:
        parse_cwv(["pas", "un", "objet"], day=TODAY)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_cwv_source_calls_pagespeed_for_the_origin_with_the_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_payload(origin=_ORIGIN))

    source = CwvSource(api_key="cle", client=_client(handler), today=lambda: TODAY)
    observations = await source.collect(SITE, TODAY_ONLY)
    assert len(seen) == 1
    params = seen[0].url.params
    assert params["url"] == "https://exemple.fr" and params["strategy"] == "mobile"
    assert params["key"] == "cle"
    assert all(o.day == TODAY for o in observations) and len(observations) == 4


async def test_cwv_source_skips_a_window_without_today() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucun appel attendu")

    source = CwvSource(api_key=None, client=_client(handler), today=lambda: TODAY)
    assert await source.collect(SITE, DayRange(date(2026, 9, 1), date(2026, 9, 20))) == []


@pytest.mark.parametrize(
    ("status", "reason", "recoverable"),
    [
        (429, "quota", True),
        (400, "site_unreachable", False),
        (403, "permission_or_api_disabled", False),
        (500, "api_error", True),
    ],
)
async def test_cwv_http_errors_are_classified(status: int, reason: str, recoverable: bool) -> None:
    source = CwvSource(
        api_key="cle",
        client=_client(lambda request: httpx.Response(status, json={})),
        today=lambda: TODAY,
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert (excinfo.value.reason, excinfo.value.recoverable) == (reason, recoverable)


async def test_cwv_network_error_never_carries_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    source = CwvSource(api_key="cle-secrete", client=_client(handler), today=lambda: TODAY)
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason == "network"
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__


def _tls(status: str, days: int | None) -> TlsStatus:
    return TlsStatus(host="exemple.fr", status=status, checked_at=NOW, days_remaining=days)


def _page(status: int) -> PageSnapshot:
    return PageSnapshot(
        url="https://exemple.fr",
        final_url="https://exemple.fr/",
        status=status,
        html="<html></html>",
        headers={"content-type": "text/html"},
        redirected=False,
        history=(),
    )


def _probe(tls: TlsStatus, page: PageSnapshot | None, calls: list | None = None) -> ProbeSource:
    async def tls_checker(domain: str) -> TlsStatus:
        return tls

    async def page_fetcher(url: str, *, allow_insecure: bool = False) -> PageSnapshot | None:
        if calls is not None:
            calls.append((url, allow_insecure))
        return page

    return ProbeSource(tls_checker=tls_checker, page_fetcher=page_fetcher, today=lambda: TODAY)


async def test_probes_observe_certificate_and_availability() -> None:
    calls: list = []
    observations = await _probe(_tls("valid", 45), _page(200), calls).collect(SITE, TODAY_ONLY)
    assert observations == [
        Observation("tls_days_remaining", TODAY, 45.0),
        Observation("page_up", TODAY, 1.0),
    ]
    assert calls == [("https://exemple.fr", False)]


async def test_an_expired_certificate_and_a_server_error_are_real_observations() -> None:
    observations = await _probe(_tls("expired", -3), _page(503)).collect(SITE, TODAY_ONLY)
    assert {o.metric: o.value for o in observations} == {
        "tls_days_remaining": -3.0,
        "page_up": 0.0,
    }


async def test_nothing_observable_is_a_recoverable_error() -> None:
    with pytest.raises(SourceError) as excinfo:
        await _probe(_tls("unreachable", None), None).collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason == "unreachable" and excinfo.value.recoverable


async def test_a_partial_probe_keeps_what_was_observed() -> None:
    observations = await _probe(_tls("unreachable", None), _page(200)).collect(SITE, TODAY_ONLY)
    assert observations == [Observation("page_up", TODAY, 1.0)]
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_metrics_sources_cwv_probes.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.services.metrics.sources.cwv'`).

- [ ] **Étape 2 : écrire l'adaptateur CWV**

```python
# backend/app/services/metrics/sources/cwv.py
"""Source Core Web Vitals des visiteurs réels (CrUX, via PageSpeed Insights).

Valeur terrain = 75e centile de l'ORIGINE (`originLoadingExperience`, fenêtre glissante
de 28 jours calculée par Google), datée du jour de collecte. Sans donnée terrain,
aucune observation terrain : jamais le laboratoire à la place, jamais zéro. Le score
Lighthouse (laboratoire) est stocké à part (`performance_score`)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from app.models.website import Website
from app.services.metrics.types import (
    SOURCE_SPECS,
    DayRange,
    Observation,
    SourceError,
    SourceSpec,
    utc_today,
)
from app.services.pagespeed import PAGESPEED_URL, _field_percentile

_TIMEOUT = httpx.Timeout(60.0)
_FIELD_METRICS: dict[str, tuple[str, ...]] = {
    "lcp_p75_ms": ("LARGEST_CONTENTFUL_PAINT_MS",),
    "inp_p75_ms": ("INTERACTION_TO_NEXT_PAINT", "EXPERIMENTAL_INTERACTION_TO_NEXT_PAINT"),
    "cls_p75": ("CUMULATIVE_LAYOUT_SHIFT_SCORE",),
}


def _section(value: Any, key: str) -> dict[str, Any]:
    inner = value.get(key) if isinstance(value, dict) else None
    return inner if isinstance(inner, dict) else {}


def parse_cwv(payload: Any, *, day: date) -> list[Observation]:
    if not isinstance(payload, dict):
        raise SourceError("api_error", recoverable=True)
    metrics = _section(_section(payload, "originLoadingExperience"), "metrics")
    observations: list[Observation] = []
    for name, keys in _FIELD_METRICS.items():
        percentile = _field_percentile(metrics, *keys)
        if percentile is None:
            continue
        # CrUX donne le CLS multiplié par 100.
        value = percentile / 100 if name == "cls_p75" else float(percentile)
        observations.append(Observation(name, day, value))
    performance = _section(_section(_section(payload, "lighthouseResult"), "categories"), "performance")
    score = performance.get("score")
    if isinstance(score, int | float) and not isinstance(score, bool) and 0 <= score <= 1:
        observations.append(Observation("performance_score", day, round(score * 100, 1)))
    return observations


def _raise_for_pagespeed(status: int) -> None:
    if status < 400:
        return
    if status == 429:
        raise SourceError("quota", recoverable=True)
    if status == 400:
        # PageSpeed n'a pas pu charger la page (DNS, TLS, 4xx du site...).
        raise SourceError("site_unreachable", recoverable=False)
    if status in (401, 403):
        raise SourceError("permission_or_api_disabled", recoverable=False)
    if status >= 500:
        raise SourceError("api_error", recoverable=True)
    raise SourceError("api_error", recoverable=False)


class CwvSource:
    spec: SourceSpec = SOURCE_SPECS["cwv"]

    def __init__(
        self,
        *,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        today: Callable[[], date] = utc_today,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._today = today

    async def collect(self, website: Website, day_range: DayRange) -> list[Observation]:
        day = self._today()
        if not day_range.contains(day):
            return []
        params = {
            "url": f"https://{website.domain}",
            "strategy": "mobile",
            "category": "performance",
        }
        if self._api_key:
            params["key"] = self._api_key
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            try:
                response = await http.get(PAGESPEED_URL, params=params)
            except httpx.HTTPError:
                # L'exception httpx porte l'URL, donc la clé : jamais chaînée.
                raise SourceError("network", recoverable=True) from None
        finally:
            if owns:
                await http.aclose()
        _raise_for_pagespeed(response.status_code)
        try:
            payload = response.json()
        except ValueError:
            raise SourceError("api_error", recoverable=True) from None
        return parse_cwv(payload, day=day)
```

- [ ] **Étape 3 : écrire l'adaptateur des sondes**

```python
# backend/app/services/metrics/sources/probes.py
"""Sondes légères : jours restants du certificat HTTPS et disponibilité de la page
d'accueil. Un certificat expiré (jours négatifs) ou une réponse 5xx sont de vraies
observations ; un site qui ne répond pas du tout n'en produit aucune (on ne sait pas si
la panne vient de lui ou du réseau)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

from app.models.website import Website
from app.services.audit_engine import TlsChecker
from app.services.measurement.fetch import PageFetcher
from app.services.metrics.types import (
    SOURCE_SPECS,
    DayRange,
    Observation,
    SourceError,
    SourceSpec,
    utc_today,
)

logger = logging.getLogger(__name__)


class ProbeSource:
    spec: SourceSpec = SOURCE_SPECS["probe"]

    def __init__(
        self,
        *,
        tls_checker: TlsChecker,
        page_fetcher: PageFetcher,
        today: Callable[[], date] = utc_today,
    ) -> None:
        self._tls_checker = tls_checker
        self._page_fetcher = page_fetcher
        self._today = today

    async def collect(self, website: Website, day_range: DayRange) -> list[Observation]:
        day = self._today()
        if not day_range.contains(day):
            return []
        observations: list[Observation] = []
        tls = await self._tls_checker(website.domain)
        if tls.status != "unreachable" and tls.days_remaining is not None:
            observations.append(Observation("tls_days_remaining", day, float(tls.days_remaining)))
        else:
            logger.info("sonde TLS sans résultat", extra={"website_id": str(website.id)})
        page = await self._page_fetcher(
            f"https://{website.domain}", allow_insecure=bool(website.allow_insecure_probe)
        )
        if page is not None:
            observations.append(Observation("page_up", day, 1.0 if page.status < 400 else 0.0))
        else:
            logger.info("page d'accueil injoignable", extra={"website_id": str(website.id)})
        if not observations:
            raise SourceError("unreachable", recoverable=True)
        return observations
```

- [ ] **Étape 4 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_metrics_sources_cwv_probes.py -v
uv run ruff check app tests
```

Attendu : tous verts.

- [ ] **Étape 5 : commit**

```bash
git add backend/app/services/metrics/sources/cwv.py backend/app/services/metrics/sources/probes.py backend/tests/test_metrics_sources_cwv_probes.py
git commit -m "feat(donnees): adaptateurs Core Web Vitals terrain (CrUX origine) et sondes TLS/disponibilite

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 7 : Types de tâches et exécuteur (clé d'idempotence, bail, reprises, limites par workspace)

**Fichiers :**
- Modifier : `backend/app/config.py` (réglages des tâches)
- Créer : `backend/app/services/jobs/__init__.py`, `backend/app/services/jobs/kinds.py`,
  `backend/app/services/jobs/runner.py`
- Créer : `backend/tests/jobs_fakes.py`
- Test : `backend/tests/test_jobs_runner.py`

**Interfaces :**
- Consomme : `JobRun`, `Schedule` (Tâche 1) ; `SourceError`, `SOURCE_SPECS`, `utc_now`
  (Tâche 2).
- Produit (`app.config.Settings`, tous optionnels) : `jobs_lease_seconds: int = 900`,
  `jobs_max_attempts: int = 5`, `jobs_workspace_concurrency: int = 2`,
  `jobs_workspace_daily_cap: int = 300`, `jobs_tick_batch: int = 100`.
- Produit (`app.services.jobs.kinds`) :
  - `Frequency` (`"hourly" | "three_daily" | "daily" | "every_3_days" | "weekly"`),
    `QueueName` (`"ga4" | "gsc" | "cwv" | "light" | "heavy"`),
    `FREQUENCY_INTERVALS: dict[str, timedelta]`, `FREQUENCY_LABELS: dict[str, str]`.
  - `TaskKind(name, label, queue="light", schedulable=False, source=None,
    floor=timedelta(hours=1), default_frequency=None, per_site=True)` avec
    `.allowed_frequencies() -> tuple[str, ...]`.
  - `KINDS: dict[str, TaskKind]` : `collect_ga4`, `collect_gsc`, `collect_cwv`,
    `collect_probes`, `measurement_check` (planifiables), `backfill`,
    `partition_maintenance` (global). `SCHEDULABLE_KINDS`, `BACKFILL_SOURCES = ("ga4",
    "gsc")`, `COLLECT_KIND_BY_SOURCE: dict[str, str]` (`"ga4" -> "collect_ga4"`,
    `"probe" -> "collect_probes"`…).
  - `effective_interval(kind: TaskKind, frequency: str) -> timedelta`,
    `slot_start(now: datetime, interval: timedelta) -> datetime`,
    `slot_label(slot: datetime) -> str` (`"20260926T0000"`).
  - `RunSpec(kind, website_id, workspace_id, window, params={})` avec `.key -> str`
    (`"{kind}:{website_id|global}:{window}"`), `.queue -> QueueName` (le rattrapage
    prend la file de sa source) et `.to_payload() -> dict[str, Any]`.
- Produit (`app.services.jobs.runner`) :
  - `ClaimStatus` (`"claimed" | "duplicate" | "busy" | "exhausted" | "throttled"`),
    `JobLimits(lease, max_attempts, workspace_concurrency)` + `.from_settings(settings)`,
    `Claim(status, run: JobRun)`, `HandlerOutcome(status="succeeded", observations=0,
    note=None)`, `Handler = Callable[[AsyncSession, JobRun], Awaitable[HandlerOutcome]]`,
    `RunResult(claim: ClaimStatus, status: str | None, retry: bool)`.
  - `lock_key(session, key: str) -> None` (verrou consultatif transactionnel).
  - `claim_run(session, spec: RunSpec, *, now, limits) -> Claim` (ne committe pas).
  - `record_schedule_outcome(session, run: JobRun, *, now) -> None`.
  - `execute_run(session, spec, *, handlers: Mapping[str, Handler], limits,
    clock=utc_now) -> RunResult` (committe : après la réclamation, puis à la fin).
  - Contrat des gestionnaires : ils reçoivent la session (sans transaction ouverte) et
    le `JobRun` réclamé ; ils peuvent committer leurs écritures intermédiaires ; ils
    lèvent `SourceError` pour un échec typé ; `execute_run` fait `rollback` sur erreur.
- Produit (`tests/jobs_fakes.py`) : `LIMITS: JobLimits`, `make_site(db_session,
  make_user, domain) -> Website`.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/jobs_fakes.py
"""Doubles et utilitaires des tests du lot B (tâches planifiées) : aucun réseau."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website import Website
from app.services.jobs.runner import JobLimits
from tests.conftest import owner_workspace_id

LIMITS = JobLimits(lease=timedelta(minutes=15), max_attempts=3, workspace_concurrency=2)


async def make_site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"jobs-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site
```

```python
# backend/tests/test_jobs_runner.py
import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.job_run import JobRun
from app.models.metric_point import MetricPoint
from app.models.schedule import Schedule
from app.models.user import User
from app.models.website import Website
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.services.jobs.kinds import (
    KINDS,
    RunSpec,
    effective_interval,
    slot_label,
    slot_start,
)
from app.services.jobs.runner import HandlerOutcome, claim_run, execute_run, lock_key
from app.services.metrics.types import SourceError
from tests.jobs_fakes import LIMITS, make_site

NOW = datetime(2026, 9, 26, 6, 7, tzinfo=UTC)


def _spec(site: Website, window: str = "w1", kind: str = "collect_probes") -> RunSpec:
    return RunSpec(kind, site.id, site.workspace_id, window)


def _clock():
    return NOW


async def _ok(session, run) -> HandlerOutcome:
    return HandlerOutcome(observations=2)


def test_kinds_floors_frequencies_and_slots() -> None:
    assert KINDS["collect_ga4"].allowed_frequencies() == ("three_daily", "daily", "every_3_days", "weekly")
    assert KINDS["collect_probes"].allowed_frequencies()[0] == "hourly"
    # Plancher appliqué même si la base contenait une fréquence trop élevée.
    assert effective_interval(KINDS["collect_ga4"], "hourly") == timedelta(hours=8)
    assert slot_start(NOW, timedelta(hours=8)) == datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
    assert slot_start(NOW, timedelta(hours=1)) == datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
    assert slot_label(slot_start(NOW, timedelta(days=1))) == "20260926T0000"


def test_run_spec_key_queue_and_payload() -> None:
    spec = RunSpec("backfill", None, None, "ga4-20260926T0000", {"source": "ga4"})
    assert spec.key == "backfill:global:ga4-20260926T0000"
    assert spec.queue == "ga4"
    assert RunSpec("collect_probes", None, None, "w").queue == "light"
    assert spec.to_payload() == {
        "kind": "backfill",
        "website_id": None,
        "workspace_id": None,
        "window": "ga4-20260926T0000",
        "params": {"source": "ga4"},
    }


async def test_first_claim_starts_the_run_with_a_lease(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-first.test")
    claim = await claim_run(db_session, _spec(site), now=NOW, limits=LIMITS)
    assert claim.status == "claimed"
    assert claim.run.status == "running" and claim.run.attempt == 1
    assert claim.run.lease_expires_at == NOW + LIMITS.lease
    assert claim.run.idempotency_key == f"collect_probes:{site.id}:w1"


async def test_a_second_delivery_during_the_lease_is_busy(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-busy.test")
    await claim_run(db_session, _spec(site), now=NOW, limits=LIMITS)
    claim = await claim_run(db_session, _spec(site), now=NOW + timedelta(minutes=5), limits=LIMITS)
    assert claim.status == "busy" and claim.run.attempt == 1


async def test_an_expired_lease_is_reclaimed_with_a_new_attempt(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-lease.test")
    await claim_run(db_session, _spec(site), now=NOW, limits=LIMITS)
    claim = await claim_run(db_session, _spec(site), now=NOW + timedelta(minutes=16), limits=LIMITS)
    assert claim.status == "claimed" and claim.run.attempt == 2


async def test_an_expired_lease_on_the_last_attempt_is_exhausted(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-exhausted.test")
    limits = replace(LIMITS, max_attempts=1)
    await claim_run(db_session, _spec(site), now=NOW, limits=limits)
    claim = await claim_run(db_session, _spec(site), now=NOW + timedelta(minutes=16), limits=limits)
    assert claim.status == "exhausted"
    assert claim.run.status == "failed" and claim.run.error_code == "lease_expired"


async def test_a_finished_run_is_never_run_again(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-dup.test")
    calls: list[str] = []

    async def handler(session, run) -> HandlerOutcome:
        calls.append(run.idempotency_key)
        return HandlerOutcome(observations=2)

    first = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": handler}, limits=LIMITS, clock=_clock
    )
    again = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": handler}, limits=LIMITS, clock=_clock
    )
    assert (first.claim, first.status, first.retry) == ("claimed", "succeeded", False)
    assert (again.claim, again.retry) == ("duplicate", False)
    assert len(calls) == 1
    run = await db_session.scalar(select(JobRun).where(JobRun.website_id == site.id))
    assert run.observations == 2 and run.lease_expires_at is None and run.duration_ms == 0


async def test_workspace_concurrency_is_limited(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-conc.test")
    other = await make_site(db_session, make_user, "run-conc-other.test")
    assert (await claim_run(db_session, _spec(site, "a"), now=NOW, limits=LIMITS)).status == "claimed"
    assert (await claim_run(db_session, _spec(site, "b"), now=NOW, limits=LIMITS)).status == "claimed"
    throttled = await claim_run(db_session, _spec(site, "c"), now=NOW, limits=LIMITS)
    assert throttled.status == "throttled" and throttled.run.status == "queued"
    # Un autre workspace n'est pas freiné.
    assert (await claim_run(db_session, _spec(other, "a"), now=NOW, limits=LIMITS)).status == "claimed"


async def test_a_recoverable_error_fails_and_asks_for_a_retry(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-retry.test")

    async def quota(session, run) -> HandlerOutcome:
        raise SourceError("quota", recoverable=True)

    result = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": quota}, limits=LIMITS, clock=_clock
    )
    assert (result.status, result.retry) == ("failed", True)
    retried = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": _ok}, limits=LIMITS, clock=_clock
    )
    assert (retried.claim, retried.status) == ("claimed", "succeeded")
    run = await db_session.scalar(select(JobRun).where(JobRun.website_id == site.id))
    assert run.attempt == 2 and run.error_code is None


async def test_a_fatal_error_is_not_retried(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-fatal.test")

    async def revoked(session, run) -> HandlerOutcome:
        raise SourceError("token_unavailable", recoverable=False)

    result = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": revoked}, limits=LIMITS, clock=_clock
    )
    assert (result.status, result.retry) == ("failed", False)
    again = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": _ok}, limits=LIMITS, clock=_clock
    )
    assert again.claim == "exhausted"


async def test_not_applicable_is_skipped_and_keeps_the_schedule_healthy(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-skip.test")
    db_session.add(
        Schedule(
            website_id=site.id, kind="collect_ga4", frequency="daily", enabled=True,
            next_due_at=NOW, failing_since=NOW - timedelta(days=2),
        )
    )
    await db_session.flush()

    async def unlinked(session, run) -> HandlerOutcome:
        raise SourceError("ga4_not_connected", recoverable=False, not_applicable=True)

    result = await execute_run(
        db_session, _spec(site, kind="collect_ga4"), handlers={"collect_ga4": unlinked},
        limits=LIMITS, clock=_clock,
    )
    assert (result.status, result.retry) == ("skipped", False)
    schedule = await db_session.scalar(select(Schedule).where(Schedule.website_id == site.id))
    assert schedule.last_status == "skipped"
    assert schedule.last_error_code == "ga4_not_connected"
    assert schedule.failing_since is None


async def test_an_unexpected_exception_rolls_back_partial_writes(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-crash.test")

    async def crash(session, run) -> HandlerOutcome:
        session.add(
            MetricPoint(
                website_id=site.id, source="probe", metric="page_up", dim_key="",
                day=date(2026, 9, 26), value=1.0, dims={}, collected_at=NOW,
            )
        )
        await session.flush()
        raise RuntimeError("bogue")

    result = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": crash}, limits=LIMITS, clock=_clock
    )
    assert (result.status, result.retry) == ("failed", True)
    run = await db_session.scalar(select(JobRun).where(JobRun.website_id == site.id))
    assert run.error_code == "internal_error" and run.error_detail == "RuntimeError"
    assert await db_session.scalar(select(func.count()).select_from(MetricPoint)) == 0


async def test_success_and_failure_update_the_schedule(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-schedule.test")
    db_session.add(
        Schedule(
            website_id=site.id, kind="collect_probes", frequency="daily", enabled=True,
            next_due_at=NOW,
        )
    )
    await db_session.flush()

    async def broken(session, run) -> HandlerOutcome:
        raise SourceError("unreachable", recoverable=True)

    await execute_run(
        db_session, _spec(site, "f"), handlers={"collect_probes": broken}, limits=LIMITS, clock=_clock
    )
    schedule = await db_session.scalar(select(Schedule).where(Schedule.website_id == site.id))
    assert schedule.last_status == "failed" and schedule.failing_since == NOW
    assert schedule.last_error_code == "unreachable"

    await execute_run(
        db_session, _spec(site, "s"), handlers={"collect_probes": _ok}, limits=LIMITS, clock=_clock
    )
    await db_session.refresh(schedule)
    assert schedule.last_status == "succeeded" and schedule.failing_since is None
    assert schedule.last_success_at == NOW and schedule.last_error_code is None


async def test_a_backfill_success_marks_the_collect_schedule(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-backfill.test")
    db_session.add(
        Schedule(
            website_id=site.id, kind="collect_gsc", frequency="daily", enabled=True,
            next_due_at=NOW,
        )
    )
    await db_session.flush()
    spec = RunSpec("backfill", site.id, site.workspace_id, "gsc-x", {"source": "gsc"})
    await execute_run(db_session, spec, handlers={"backfill": _ok}, limits=LIMITS, clock=_clock)
    schedule = await db_session.scalar(select(Schedule).where(Schedule.website_id == site.id))
    assert schedule.backfill_done_at == NOW and schedule.last_status == "succeeded"


async def test_a_second_delivery_waits_for_the_key_lock_then_sees_the_run_busy(engine) -> None:
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as setup:
        user = User(email="jobs-lock@example.com", google_sub="jobs-lock-sub")
        setup.add(user)
        await setup.flush()
        workspace = Workspace(name="jobs-lock", owner_user_id=user.id)
        setup.add(workspace)
        await setup.flush()
        setup.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        site = Website(workspace_id=workspace.id, domain="jobs-lock.test", display_name="lock")
        setup.add(site)
        await setup.commit()
        site_id, workspace_id, user_id = site.id, workspace.id, user.id

    spec = RunSpec("collect_probes", site_id, workspace_id, "lock")
    try:
        async with maker() as holder, maker() as other:
            first = await claim_run(holder, spec, now=NOW, limits=LIMITS)  # verrou tenu
            assert first.status == "claimed"
            task = asyncio.create_task(claim_run(other, spec, now=NOW, limits=LIMITS))
            waiting = 0
            for _ in range(200):
                assert not task.done(), "la seconde livraison doit attendre le verrou de la clé"
                waiting = await holder.scalar(
                    text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
                )
                if waiting:
                    break
                await asyncio.sleep(0.05)
            assert waiting, "la seconde livraison doit attendre le verrou de la clé"
            await holder.commit()
            second = await asyncio.wait_for(task, timeout=10)
            assert second.status == "busy"
            await other.commit()
    finally:
        async with maker() as cleanup:
            await cleanup.execute(delete(Website).where(Website.id == site_id))
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


async def test_lock_key_is_reentrant_in_a_transaction(db_session: AsyncSession) -> None:
    await lock_key(db_session, "x")
    await lock_key(db_session, "x")  # ne se bloque pas lui-même
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_jobs_runner.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.services.jobs'`).

- [ ] **Étape 2 : ajouter les réglages**

Dans `backend/app/config.py`, dans la classe `Settings`, juste avant le commentaire
`# {version:int -> clé base64 de 32 octets}` :

```python
    # --- Tâches planifiées (lot B) ---
    # Bail d'une tâche : au-delà, une autre livraison peut la reprendre.
    jobs_lease_seconds: int = 900
    # Aligné sur la configuration des files Cloud Tasks (runbook).
    jobs_max_attempts: int = 5
    # Tâches simultanées par workspace, et tâches déposées par jour et par workspace.
    jobs_workspace_concurrency: int = 2
    jobs_workspace_daily_cap: int = 300
    # Tâches déposées au plus par passage du planificateur.
    jobs_tick_batch: int = 100
```

- [ ] **Étape 3 : écrire les types de tâches**

```python
# backend/app/services/jobs/__init__.py
"""Tâches planifiées : types, exécution, planification, files et santé (lot B)."""
```

```python
# backend/app/services/jobs/kinds.py
"""Types de tâches, fréquences et identité d'une exécution (`RunSpec`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from app.services.metrics.types import SOURCE_SPECS

Frequency = Literal["hourly", "three_daily", "daily", "every_3_days", "weekly"]
QueueName = Literal["ga4", "gsc", "cwv", "light", "heavy"]

FREQUENCY_INTERVALS: dict[str, timedelta] = {
    "hourly": timedelta(hours=1),
    "three_daily": timedelta(hours=8),
    "daily": timedelta(days=1),
    "every_3_days": timedelta(days=3),
    "weekly": timedelta(days=7),
}
FREQUENCY_LABELS: dict[str, str] = {
    "hourly": "Toutes les heures",
    "three_daily": "3 fois par jour",
    "daily": "Tous les jours",
    "every_3_days": "Tous les 3 jours",
    "weekly": "Toutes les semaines",
}

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class TaskKind:
    name: str
    label: str
    queue: QueueName = "light"
    schedulable: bool = False
    # Source collectée (tâches `collect_*`).
    source: str | None = None
    # Plancher de fréquence (quotas Google : 8 h ; sondes légères : 1 h).
    floor: timedelta = timedelta(hours=1)
    default_frequency: Frequency | None = None
    per_site: bool = True

    def allowed_frequencies(self) -> tuple[str, ...]:
        return tuple(name for name, interval in FREQUENCY_INTERVALS.items() if interval >= self.floor)


KINDS: dict[str, TaskKind] = {
    kind.name: kind
    for kind in (
        TaskKind(
            "collect_ga4", "Données Google Analytics 4", queue="ga4", schedulable=True,
            source="ga4", floor=SOURCE_SPECS["ga4"].min_interval, default_frequency="daily",
        ),
        TaskKind(
            "collect_gsc", "Données Search Console", queue="gsc", schedulable=True,
            source="gsc", floor=SOURCE_SPECS["gsc"].min_interval, default_frequency="daily",
        ),
        TaskKind(
            "collect_cwv", "Core Web Vitals des visiteurs réels", queue="cwv",
            schedulable=True, source="cwv", floor=SOURCE_SPECS["cwv"].min_interval,
            default_frequency="daily",
        ),
        TaskKind(
            "collect_probes", "Certificat HTTPS et disponibilité du site", queue="light",
            schedulable=True, source="probe", floor=SOURCE_SPECS["probe"].min_interval,
            default_frequency="three_daily",
        ),
        # Lit GA4 et Search Console : même plancher que les sources à quota.
        TaskKind(
            "measurement_check", "Vérification du plan de mesure", queue="light",
            schedulable=True, floor=timedelta(hours=8), default_frequency="daily",
        ),
        TaskKind("backfill", "Historique initial (90 jours)"),
        TaskKind("partition_maintenance", "Maintenance du stockage des mesures", per_site=False),
    )
}
SCHEDULABLE_KINDS: tuple[TaskKind, ...] = tuple(k for k in KINDS.values() if k.schedulable)
BACKFILL_SOURCES: tuple[str, ...] = ("ga4", "gsc")
COLLECT_KIND_BY_SOURCE: dict[str, str] = {
    kind.source: kind.name for kind in SCHEDULABLE_KINDS if kind.source is not None
}


def effective_interval(kind: TaskKind, frequency: str) -> timedelta:
    return max(FREQUENCY_INTERVALS[frequency], kind.floor)


def slot_start(now: datetime, interval: timedelta) -> datetime:
    """Début du créneau contenant `now` (créneaux alignés sur l'époque Unix, en UTC)."""
    return _EPOCH + ((now - _EPOCH) // interval) * interval


def slot_label(slot: datetime) -> str:
    return slot.astimezone(UTC).strftime("%Y%m%dT%H%M")


@dataclass(frozen=True, slots=True)
class RunSpec:
    """Identité d'une exécution : la clé d'idempotence en découle."""

    kind: str
    website_id: UUID | None
    workspace_id: UUID | None
    window: str
    params: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.website_id or 'global'}:{self.window}"

    @property
    def queue(self) -> QueueName:
        if self.kind == "backfill":
            source = self.params.get("source")
            return "gsc" if source == "gsc" else "ga4" if source == "ga4" else "light"
        return KINDS[self.kind].queue

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "website_id": str(self.website_id) if self.website_id else None,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "window": self.window,
            "params": dict(self.params),
        }
```

- [ ] **Étape 4 : écrire l'exécuteur**

```python
# backend/app/services/jobs/runner.py
"""Exécution d'une tâche : clé d'idempotence, bail, reprises, classification des
erreurs et limites par workspace.

La réclamation prend d'abord un verrou consultatif sur la clé de la tâche, puis sur le
workspace, AVANT toute lecture : deux livraisons de la même tâche ne s'exécutent jamais
ensemble, et le décompte des tâches en cours d'un workspace est exact. La réclamation
est committée avant le travail : aucune transaction ne reste ouverte pendant la
collecte réseau."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.services.jobs.kinds import COLLECT_KIND_BY_SOURCE, RunSpec
from app.services.metrics.types import SourceError, utc_now

logger = logging.getLogger(__name__)

ClaimStatus = Literal["claimed", "duplicate", "busy", "exhausted", "throttled"]


@dataclass(frozen=True, slots=True)
class JobLimits:
    lease: timedelta
    max_attempts: int
    workspace_concurrency: int

    @classmethod
    def from_settings(cls, settings: Settings) -> JobLimits:
        return cls(
            lease=timedelta(seconds=settings.jobs_lease_seconds),
            max_attempts=settings.jobs_max_attempts,
            workspace_concurrency=settings.jobs_workspace_concurrency,
        )


@dataclass(frozen=True, slots=True)
class Claim:
    status: ClaimStatus
    run: JobRun


@dataclass(frozen=True, slots=True)
class HandlerOutcome:
    status: Literal["succeeded", "skipped"] = "succeeded"
    observations: int = 0
    note: str | None = None


Handler = Callable[[AsyncSession, JobRun], Awaitable[HandlerOutcome]]


@dataclass(frozen=True, slots=True)
class RunResult:
    claim: ClaimStatus
    status: str | None
    # La file doit-elle réessayer plus tard (réponse non 2xx) ?
    retry: bool


async def lock_key(session: AsyncSession, key: str) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})


def _close(
    run: JobRun,
    *,
    status: str,
    error_code: str | None,
    recoverable: bool | None,
    now: datetime,
    observations: int = 0,
    detail: str | None = None,
) -> None:
    run.status = status
    run.error_code = error_code
    run.error_detail = detail
    run.recoverable = recoverable
    run.observations = observations
    run.finished_at = now
    run.lease_expires_at = None
    if run.started_at is not None:
        run.duration_ms = max(0, int((now - run.started_at).total_seconds() * 1000))


async def claim_run(
    session: AsyncSession, spec: RunSpec, *, now: datetime, limits: JobLimits
) -> Claim:
    await lock_key(session, f"job:{spec.key}")
    await session.execute(
        pg_insert(JobRun)
        .values(
            id=uuid4(),
            idempotency_key=spec.key,
            kind=spec.kind,
            website_id=spec.website_id,
            workspace_id=spec.workspace_id,
            window_label=spec.window,
            params=dict(spec.params),
            status="queued",
            attempt=0,
            max_attempts=limits.max_attempts,
            enqueued_at=now,
            observations=0,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    run = (
        await session.execute(
            select(JobRun)
            .where(JobRun.idempotency_key == spec.key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    if run.status in ("succeeded", "skipped"):
        return Claim("duplicate", run)
    lease_valid = run.lease_expires_at is not None and run.lease_expires_at > now
    if run.status == "running" and lease_valid:
        return Claim("busy", run)
    if run.status == "failed" and run.recoverable is False:
        return Claim("exhausted", run)
    if run.attempt >= run.max_attempts:
        if run.status == "running":  # bail expiré sur la dernière tentative
            _close(run, status="failed", error_code="lease_expired", recoverable=True, now=now)
            await session.flush()
        return Claim("exhausted", run)
    if run.workspace_id is not None:
        await lock_key(session, f"workspace:{run.workspace_id}")
        running = await session.scalar(
            select(func.count())
            .select_from(JobRun)
            .where(
                JobRun.workspace_id == run.workspace_id,
                JobRun.status == "running",
                JobRun.lease_expires_at > now,
                JobRun.id != run.id,
            )
        )
        if (running or 0) >= limits.workspace_concurrency:
            return Claim("throttled", run)
    run.status = "running"
    run.attempt += 1
    run.started_at = now
    run.finished_at = None
    run.lease_expires_at = now + limits.lease
    await session.flush()
    return Claim("claimed", run)


async def record_schedule_outcome(session: AsyncSession, run: JobRun, *, now: datetime) -> None:
    if run.website_id is None:
        return
    if run.kind == "backfill":
        kind = COLLECT_KIND_BY_SOURCE.get(str(run.params.get("source", "")))
    else:
        kind = run.kind
    if kind is None:
        return
    schedule = (
        await session.execute(
            select(Schedule)
            .where(Schedule.website_id == run.website_id, Schedule.kind == kind)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if schedule is None:
        return
    schedule.last_run_at = now
    schedule.last_status = run.status
    if run.status == "succeeded":
        schedule.last_success_at = now
        schedule.failing_since = None
        schedule.last_error_code = None
        if run.kind == "backfill":
            schedule.backfill_done_at = now
    elif run.status == "failed":
        schedule.last_error_code = run.error_code
        if schedule.failing_since is None:
            schedule.failing_since = now
    else:  # « ignorée » : rien à collecter, ce n'est pas un échec
        schedule.last_error_code = run.error_code
        schedule.failing_since = None


async def _finish(
    session: AsyncSession,
    run_id,
    *,
    status: str,
    error_code: str | None,
    recoverable: bool | None,
    now: datetime,
    observations: int = 0,
    detail: str | None = None,
) -> RunResult:
    run = await session.get(JobRun, run_id, with_for_update=True, populate_existing=True)
    if run is None:  # site supprimé pendant l'exécution (cascade)
        await session.commit()
        return RunResult("claimed", None, retry=False)
    _close(
        run,
        status=status,
        error_code=error_code,
        recoverable=recoverable,
        now=now,
        observations=observations,
        detail=detail,
    )
    await record_schedule_outcome(session, run, now=now)
    await session.commit()
    retry = status == "failed" and recoverable is True and run.attempt < run.max_attempts
    return RunResult("claimed", status, retry=retry)


async def execute_run(
    session: AsyncSession,
    spec: RunSpec,
    *,
    handlers: Mapping[str, Handler],
    limits: JobLimits,
    clock: Callable[[], datetime] = utc_now,
) -> RunResult:
    claim = await claim_run(session, spec, now=clock(), limits=limits)
    await session.commit()
    if claim.status != "claimed":
        return RunResult(claim.status, claim.run.status, retry=claim.status in ("busy", "throttled"))

    run_id = claim.run.id
    handler = handlers.get(spec.kind)
    log_extra = {"job_kind": spec.kind, "job_key": spec.key}
    try:
        if handler is None:
            raise SourceError("unknown_kind", recoverable=False)
        outcome = await handler(session, claim.run)
    except SourceError as exc:
        await session.rollback()
        if exc.not_applicable:
            return await _finish(
                session, run_id, status="skipped", error_code=exc.reason, recoverable=None,
                now=clock(),
            )
        logger.warning(
            "tâche en échec",
            extra={**log_extra, "event": "job_failed", "error_code": exc.reason,
                   "recoverable": exc.recoverable},
        )
        return await _finish(
            session, run_id, status="failed", error_code=exc.reason,
            recoverable=exc.recoverable, now=clock(),
        )
    except Exception as exc:
        await session.rollback()
        logger.exception("tâche en échec inattendu", extra={**log_extra, "event": "job_crashed"})
        return await _finish(
            session, run_id, status="failed", error_code="internal_error", recoverable=True,
            now=clock(), detail=type(exc).__name__,
        )
    return await _finish(
        session, run_id, status=outcome.status, error_code=outcome.note, recoverable=None,
        now=clock(), observations=outcome.observations,
    )
```

- [ ] **Étape 5 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_jobs_runner.py tests/test_config_guard.py -v
uv run ruff check app tests
```

Attendu : tous verts (les tests existants de configuration restent inchangés et verts).

- [ ] **Étape 6 : commit**

```bash
git add backend/app/config.py backend/app/services/jobs backend/tests/jobs_fakes.py backend/tests/test_jobs_runner.py
git commit -m "feat(taches): types de taches et executeur (cle d'idempotence, bail, reprises, limites par workspace)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 8 : Santé des tâches et alertes d'exploitation

**Fichiers :**
- Créer : `backend/app/services/jobs/health.py`, `backend/app/services/jobs/messages.py`
- Test : `backend/tests/test_jobs_health.py`

**Interfaces :**
- Consomme : `Schedule`, `JobRun`, `Website` (Tâche 1).
- Produit (`app.services.jobs.health`) :
  - constantes `FAILING_AFTER = timedelta(hours=24)`, `OVERDUE_AFTER =
    timedelta(hours=2)`, `STUCK_QUEUED_AFTER = timedelta(hours=1)`,
    `CLIENT_ACTION_CODES: frozenset[str]` ;
  - `FailingSchedule(website_id, kind, failing_since, error_code, client_action)` ;
  - `JobsHealth(checked_at, failing: tuple[FailingSchedule, ...], overdue: int,
    stuck_running: int, stuck_queued: int)` avec `.ok -> bool` et
    `.internal_failures -> tuple[FailingSchedule, ...]` ;
  - `compute_jobs_health(session, *, now) -> JobsHealth` (lecture seule) ;
  - `report_jobs_health(health, *, capture: Callable[[str, dict[str, Any]], None] |
    None = None) -> None` : ligne de log `jobs_health_alert` (ERROR si un échec relève
    de nous, un retard ou une tâche bloquée ; WARNING si seul le client peut agir) et
    événement Sentry (message fixe, compteurs en `extra`) pour le niveau ERROR ;
    `jobs_health_ok` en INFO sinon.
- Produit (`app.services.jobs.messages`) : `ERROR_MESSAGES: dict[str, str]`,
  `error_message(code: str | None) -> str | None` (texte français pour l'interface).

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_jobs_health.py
import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.services.jobs.health import (
    FailingSchedule,
    JobsHealth,
    compute_jobs_health,
    report_jobs_health,
)
from app.services.jobs.messages import error_message
from tests.jobs_fakes import make_site

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)


def _schedule(site, kind: str, **values) -> Schedule:
    base = {"website_id": site.id, "kind": kind, "frequency": "daily", "enabled": True,
            "next_due_at": NOW + timedelta(hours=1)}
    base.update(values)
    return Schedule(**base)


def _run(site, key: str, **values) -> JobRun:
    base = {"idempotency_key": key, "kind": "collect_probes", "website_id": site.id,
            "workspace_id": site.workspace_id, "window_label": "w", "params": {},
            "status": "queued", "attempt": 0, "max_attempts": 5, "observations": 0,
            "enqueued_at": NOW}
    base.update(values)
    return JobRun(**base)


async def test_a_collection_failing_for_more_than_a_day_is_reported(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-fail.test")
    db_session.add_all(
        [
            _schedule(site, "collect_gsc", failing_since=NOW - timedelta(hours=25),
                      last_error_code="quota"),
            _schedule(site, "collect_ga4", failing_since=NOW - timedelta(hours=25),
                      last_error_code="token_unavailable"),
            _schedule(site, "collect_cwv", failing_since=NOW - timedelta(hours=2),
                      last_error_code="quota"),
        ]
    )
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    kinds = {f.kind: f.client_action for f in health.failing}
    assert kinds == {"collect_gsc": False, "collect_ga4": True}
    assert [f.kind for f in health.internal_failures] == ["collect_gsc"]
    assert not health.ok


async def test_archived_sites_and_disabled_schedules_are_ignored(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-archived.test")
    site.archived_at = NOW
    other = await make_site(db_session, make_user, "health-disabled.test")
    db_session.add_all(
        [
            _schedule(site, "collect_gsc", failing_since=NOW - timedelta(days=3)),
            _schedule(other, "collect_gsc", enabled=False, failing_since=NOW - timedelta(days=3),
                      next_due_at=NOW - timedelta(days=3)),
        ]
    )
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    assert health.ok and health.failing == () and health.overdue == 0


async def test_overdue_and_stuck_runs_are_counted(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "health-stuck.test")
    db_session.add_all(
        [
            _schedule(site, "collect_probes", next_due_at=NOW - timedelta(hours=3)),
            _run(site, "a", status="running", lease_expires_at=NOW - timedelta(minutes=1)),
            _run(site, "b", status="running", lease_expires_at=NOW + timedelta(minutes=10)),
            _run(site, "c", status="queued", enqueued_at=NOW - timedelta(hours=2)),
            _run(site, "d", status="queued", enqueued_at=NOW - timedelta(minutes=5)),
        ]
    )
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    assert (health.overdue, health.stuck_running, health.stuck_queued) == (1, 1, 1)


def _health(**values) -> JobsHealth:
    base = {"checked_at": NOW, "failing": (), "overdue": 0, "stuck_running": 0, "stuck_queued": 0}
    base.update(values)
    return JobsHealth(**base)


def _failing(client_action: bool) -> FailingSchedule:
    return FailingSchedule(
        website_id=None, kind="collect_gsc", failing_since=NOW - timedelta(days=2),
        error_code="token_unavailable" if client_action else "quota", client_action=client_action,
    )


def test_a_healthy_report_is_info_without_sentry(caplog: pytest.LogCaptureFixture) -> None:
    captured: list = []
    with caplog.at_level(logging.INFO, logger="app.services.jobs.health"):
        report_jobs_health(_health(), capture=lambda message, extra: captured.append(message))
    assert captured == []
    assert any(r.message == "jobs_health_ok" for r in caplog.records)


def test_our_failures_are_errors_sent_to_sentry(caplog: pytest.LogCaptureFixture) -> None:
    captured: list = []
    with caplog.at_level(logging.INFO, logger="app.services.jobs.health"):
        report_jobs_health(
            _health(failing=(_failing(False), _failing(True)), stuck_queued=2),
            capture=lambda message, extra: captured.append((message, extra)),
        )
    record = next(r for r in caplog.records if r.message == "jobs_health_alert")
    assert record.levelno == logging.ERROR
    assert record.event == "jobs_health_alert"
    assert (record.failing_internal, record.failing_client_action, record.stuck_queued) == (1, 1, 2)
    assert captured == [
        (
            "Tâches planifiées en échec ou en retard",
            {"failing_internal": 1, "failing_client_action": 1, "overdue": 0,
             "stuck_running": 0, "stuck_queued": 2, "kinds": ["collect_gsc"]},
        )
    ]


def test_client_side_failures_only_are_warnings(caplog: pytest.LogCaptureFixture) -> None:
    captured: list = []
    with caplog.at_level(logging.INFO, logger="app.services.jobs.health"):
        report_jobs_health(_health(failing=(_failing(True),)), capture=lambda m, e: captured.append(m))
    record = next(r for r in caplog.records if r.message == "jobs_health_alert")
    assert record.levelno == logging.WARNING and captured == []


def test_error_messages_are_french_and_never_empty() -> None:
    assert error_message(None) is None
    assert error_message("quota").startswith("Quota Google atteint")
    assert error_message("code-inconnu") == "Erreur inattendue : nous sommes prévenus."
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_jobs_health.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.services.jobs.health'`).

- [ ] **Étape 2 : écrire les messages d'erreur**

```python
# backend/app/services/jobs/messages.py
"""Codes d'erreur stables des tâches -> texte français affiché dans l'interface."""

from __future__ import annotations

_UNKNOWN = "Erreur inattendue : nous sommes prévenus."

ERROR_MESSAGES: dict[str, str] = {
    "ga4_not_connected": "Aucune propriété GA4 n'est reliée à ce site.",
    "gsc_not_connected": "Aucun site Search Console n'est relié à ce site.",
    "token_unavailable": "L'accès Google a expiré : reconnecte ton compte Google.",
    "permission_or_api_disabled": "Google refuse l'accès (droits insuffisants ou API désactivée).",
    "not_found": "La ressource Google reliée est introuvable.",
    "quota": "Quota Google atteint : nouvel essai automatique.",
    "circuit_open": "Quota Google atteint pour ce compte : pause de 30 minutes puis nouvel essai.",
    "network": "Service momentanément injoignable : nouvel essai automatique.",
    "api_error": "Réponse inattendue du service : nouvel essai automatique.",
    "site_unreachable": "Ton site n'a pas pu être analysé par Google (page injoignable).",
    "unreachable": "Ton site ne répond pas.",
    "website_inactive": "Site archivé : suivi suspendu.",
    "not_dispatched": "La tâche n'a pas démarré : nouvel essai au prochain passage.",
    "enqueue_failed": "La tâche n'a pas pu être programmée : nouvel essai au prochain passage.",
    "lease_expired": "La tâche a été interrompue : nouvel essai automatique.",
    "internal_error": _UNKNOWN,
    "unknown_kind": _UNKNOWN,
    "bad_params": _UNKNOWN,
}


def error_message(code: str | None) -> str | None:
    if code is None:
        return None
    return ERROR_MESSAGES.get(code, _UNKNOWN)
```

- [ ] **Étape 3 : écrire la santé des tâches**

```python
# backend/app/services/jobs/health.py
"""Santé des tâches planifiées et alertes d'exploitation.

Objectif (spec §6 mesure 6) : une collecte en échec depuis plus de 24 h doit être vue
par l'équipe AVANT le client. Pas d'e-mail (aucun fournisseur) : une ligne de log
structurée (alerte Cloud Monitoring côté propriétaire), un événement Sentry et un
résumé interne (`GET /internal/jobs/health`)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import sentry_sdk
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.models.website import Website

logger = logging.getLogger(__name__)

FAILING_AFTER = timedelta(hours=24)
OVERDUE_AFTER = timedelta(hours=2)
STUCK_QUEUED_AFTER = timedelta(hours=1)
# Échecs que seul le client peut lever (reconnexion Google, droits, site injoignable).
CLIENT_ACTION_CODES: frozenset[str] = frozenset(
    {"token_unavailable", "permission_or_api_disabled", "not_found", "site_unreachable"}
)
_SENTRY_MESSAGE = "Tâches planifiées en échec ou en retard"

Capture = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class FailingSchedule:
    website_id: UUID | None
    kind: str
    failing_since: datetime
    error_code: str | None
    client_action: bool


@dataclass(frozen=True, slots=True)
class JobsHealth:
    checked_at: datetime
    failing: tuple[FailingSchedule, ...]
    overdue: int
    stuck_running: int
    stuck_queued: int

    @property
    def internal_failures(self) -> tuple[FailingSchedule, ...]:
        return tuple(item for item in self.failing if not item.client_action)

    @property
    def ok(self) -> bool:
        return not self.failing and not self.overdue and not self.stuck_running and not self.stuck_queued


def _active_schedules():
    return (
        select(Schedule)
        .join(Website, Website.id == Schedule.website_id)
        .where(Schedule.enabled.is_(True), Website.archived_at.is_(None))
    )


async def compute_jobs_health(session: AsyncSession, *, now: datetime) -> JobsHealth:
    failing_rows = (
        await session.execute(
            _active_schedules()
            .where(
                Schedule.failing_since.is_not(None),
                Schedule.failing_since <= now - FAILING_AFTER,
            )
            .order_by(Schedule.failing_since)
        )
    ).scalars().all()
    failing = tuple(
        FailingSchedule(
            website_id=row.website_id,
            kind=row.kind,
            failing_since=row.failing_since,  # type: ignore[arg-type]
            error_code=row.last_error_code,
            client_action=row.last_error_code in CLIENT_ACTION_CODES,
        )
        for row in failing_rows
    )
    overdue = await session.scalar(
        select(func.count()).select_from(
            _active_schedules().where(Schedule.next_due_at < now - OVERDUE_AFTER).subquery()
        )
    )
    stuck_running = await session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.status == "running", JobRun.lease_expires_at < now)
    )
    stuck_queued = await session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.status == "queued", JobRun.enqueued_at < now - STUCK_QUEUED_AFTER)
    )
    return JobsHealth(
        checked_at=now,
        failing=failing,
        overdue=overdue or 0,
        stuck_running=stuck_running or 0,
        stuck_queued=stuck_queued or 0,
    )


def _sentry_capture(message: str, extra: dict[str, Any]) -> None:
    with sentry_sdk.new_scope() as scope:
        for key, value in extra.items():
            scope.set_extra(key, value)
        sentry_sdk.capture_message(message, level="error")


def report_jobs_health(health: JobsHealth, *, capture: Capture | None = None) -> None:
    if health.ok:
        logger.info("jobs_health_ok", extra={"event": "jobs_health"})
        return
    internal = len(health.internal_failures)
    extra: dict[str, Any] = {
        "failing_internal": internal,
        "failing_client_action": len(health.failing) - internal,
        "overdue": health.overdue,
        "stuck_running": health.stuck_running,
        "stuck_queued": health.stuck_queued,
        "kinds": sorted({item.kind for item in health.failing}),
    }
    ours = internal or health.overdue or health.stuck_running or health.stuck_queued
    level = logging.ERROR if ours else logging.WARNING
    logger.log(level, "jobs_health_alert", extra={"event": "jobs_health_alert", **extra})
    if level == logging.ERROR:
        (capture or _sentry_capture)(_SENTRY_MESSAGE, extra)
```

- [ ] **Étape 4 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_jobs_health.py -v
uv run ruff check app tests
```

Attendu : tous verts.

- [ ] **Étape 5 : commit**

```bash
git add backend/app/services/jobs/health.py backend/app/services/jobs/messages.py backend/tests/test_jobs_health.py
git commit -m "feat(taches): sante des taches planifiees et alertes (logs structures, Sentry)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 9 : Planificateur (`tick`), abstraction `TaskQueue` et `InlineQueue`

**Fichiers :**
- Créer : `backend/app/services/jobs/queue.py`, `backend/app/services/jobs/scheduler.py`
- Modifier : `backend/tests/jobs_fakes.py` (ajout de `RecordingQueue`)
- Test : `backend/tests/test_jobs_scheduler.py`

**Interfaces :**
- Consomme : `Schedule`, `JobRun`, `Website` (Tâche 1) ; `KINDS`,
  `SCHEDULABLE_KINDS`, `BACKFILL_SOURCES`, `QueueName`, `RunSpec`,
  `effective_interval`, `slot_start`, `slot_label` (Tâche 7) ; `compute_jobs_health`,
  `report_jobs_health` (Tâche 8).
- Produit (`app.services.jobs.queue`) :
  - `TaskMessage(spec: RunSpec, queue: QueueName)` ;
  - `EnqueueError(reason: str)` (attribut `.reason`) ;
  - `TaskQueue` (Protocol) : `async enqueue(message: TaskMessage) -> None` (lève
    `EnqueueError` si la tâche n'a pas pu être déposée ; un doublon déjà déposé n'est
    pas une erreur) ;
  - `InlineQueue(execute: Callable[[RunSpec], Awaitable[object]])` : exécute la tâche
    dans le processus, sans réseau ni nouvelle tentative ; attribut `executed:
    list[str]` (clés exécutées).
- Produit (`app.services.jobs.scheduler`) :
  - `TickResult(materialized, enqueued, capped, failed_enqueue, expired_queued)` ;
  - `materialize_default_schedules(session, *, now) -> int` ;
  - `due_schedules(session, *, now, limit) -> list[tuple[Schedule, Website]]` (verrou
    `FOR UPDATE SKIP LOCKED` sur les plannings) ;
  - `plan_run(schedule, website, *, now) -> RunSpec` ;
  - `insert_queued(session, spec, *, now, max_attempts) -> bool` ;
  - `expire_stale_queued(session, *, now, older_than=timedelta(hours=2)) -> int` ;
  - `runs_today(session, workspace_id, *, now) -> int` ;
  - `tick(session, queue: TaskQueue, *, now, batch: int, daily_cap: int, max_attempts:
    int) -> TickResult` (committe ; aucune transaction ouverte pendant les dépôts).
- Produit (`tests/jobs_fakes.py`) : `RecordingQueue(failing_kinds=frozenset())` avec
  `.messages: list[TaskMessage]`.

- [ ] **Étape 1 : écrire les tests qui échouent**

Ajouter à la fin de `backend/tests/jobs_fakes.py` (et ajouter
`from app.services.jobs.queue import EnqueueError, TaskMessage` aux imports) :

```python
class RecordingQueue:
    """File factice : enregistre les dépôts ; `failing_kinds` simule une panne de dépôt."""

    def __init__(self, *, failing_kinds: frozenset[str] = frozenset()) -> None:
        self.messages: list[TaskMessage] = []
        self._failing = failing_kinds

    async def enqueue(self, message: TaskMessage) -> None:
        if message.spec.kind in self._failing:
            raise EnqueueError("network")
        self.messages.append(message)
```

```python
# backend/tests/test_jobs_scheduler.py
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.services.jobs.kinds import RunSpec
from app.services.jobs.queue import InlineQueue, TaskMessage
from app.services.jobs.scheduler import (
    due_schedules,
    expire_stale_queued,
    materialize_default_schedules,
    plan_run,
    tick,
)
from tests.jobs_fakes import RecordingQueue, make_site

NOW = datetime(2026, 9, 26, 6, 7, tzinfo=UTC)


async def _tick(session: AsyncSession, queue, *, now: datetime = NOW, daily_cap: int = 300):
    return await tick(session, queue, now=now, batch=100, daily_cap=daily_cap, max_attempts=5)


async def _schedules(session: AsyncSession, website_id) -> dict[str, Schedule]:
    rows = await session.execute(select(Schedule).where(Schedule.website_id == website_id))
    return {row.kind: row for row in rows.scalars()}


async def test_default_schedules_are_materialized_once_for_active_sites(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-mat.test")
    archived = await make_site(db_session, make_user, "tick-archived.test")
    archived.archived_at = NOW
    await db_session.flush()

    assert await materialize_default_schedules(db_session, now=NOW) == 5
    assert await materialize_default_schedules(db_session, now=NOW) == 0
    schedules = await _schedules(db_session, site.id)
    assert {kind: s.frequency for kind, s in schedules.items()} == {
        "collect_ga4": "daily",
        "collect_gsc": "daily",
        "collect_cwv": "daily",
        "collect_probes": "three_daily",
        "measurement_check": "daily",
    }
    assert all(s.enabled and s.next_due_at == NOW for s in schedules.values())
    assert await _schedules(db_session, archived.id) == {}


async def test_a_first_tick_backfills_google_sources_and_runs_the_others(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-first.test")
    queue = RecordingQueue()
    result = await _tick(db_session, queue)
    by_kind = {(m.spec.kind, m.spec.params.get("source")): m for m in queue.messages}
    assert set(by_kind) == {
        ("backfill", "ga4"),
        ("backfill", "gsc"),
        ("collect_cwv", None),
        ("collect_probes", None),
        ("measurement_check", None),
        ("partition_maintenance", None),
    }
    assert by_kind[("backfill", "ga4")].queue == "ga4"
    assert by_kind[("backfill", "gsc")].spec.window == "gsc-20260926T0000"
    assert by_kind[("collect_probes", None)].queue == "light"
    assert by_kind[("collect_cwv", None)].spec.key == f"collect_cwv:{site.id}:20260926T0000"
    assert by_kind[("partition_maintenance", None)].spec.key == "partition_maintenance:global:20260926"
    assert (result.materialized, result.enqueued, result.capped) == (5, 6, 0)

    schedules = await _schedules(db_session, site.id)
    assert schedules["collect_cwv"].next_due_at == datetime(2026, 9, 27, tzinfo=UTC)
    assert schedules["collect_probes"].next_due_at == datetime(2026, 9, 26, 8, tzinfo=UTC)
    queued = await db_session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.status == "queued")
    )
    assert queued == 6


async def test_a_second_tick_in_the_same_slot_deposits_nothing(
    db_session: AsyncSession, make_user
) -> None:
    await make_site(db_session, make_user, "tick-again.test")
    await _tick(db_session, RecordingQueue())
    queue = RecordingQueue()
    result = await _tick(db_session, queue, now=NOW + timedelta(minutes=15))
    assert queue.messages == [] and result.enqueued == 0


async def test_the_frequency_floor_applies_even_to_a_bad_row(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-floor.test")
    db_session.add(
        Schedule(
            website_id=site.id, kind="collect_ga4", frequency="hourly", enabled=True,
            next_due_at=NOW, backfill_done_at=NOW - timedelta(days=1),
        )
    )
    await db_session.flush()
    queue = RecordingQueue()
    await _tick(db_session, queue)
    ga4 = next(m for m in queue.messages if m.spec.kind == "collect_ga4")
    assert ga4.spec.window == "20260926T0000"  # créneau de 8 h, pas d'1 h
    schedules = await _schedules(db_session, site.id)
    assert schedules["collect_ga4"].next_due_at == datetime(2026, 9, 26, 8, tzinfo=UTC)


async def test_the_workspace_daily_cap_holds_back_extra_tasks(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-cap.test")
    queue = RecordingQueue()
    result = await _tick(db_session, queue, daily_cap=2)
    site_messages = [m for m in queue.messages if m.spec.website_id == site.id]
    assert len(site_messages) == 2 and result.capped == 3
    # Les plannings retenus restent dus : ils partiront le lendemain.
    schedules = await _schedules(db_session, site.id)
    assert sum(1 for s in schedules.values() if s.next_due_at == NOW) == 3


async def test_a_failed_deposit_is_retried_at_the_next_tick(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-enqueue-fail.test")
    result = await _tick(db_session, RecordingQueue(failing_kinds=frozenset({"collect_cwv"})))
    assert result.failed_enqueue == 1
    schedules = await _schedules(db_session, site.id)
    assert schedules["collect_cwv"].next_due_at == NOW  # redevenu dû
    run = await db_session.scalar(select(JobRun).where(JobRun.kind == "collect_cwv"))
    assert (run.status, run.error_code) == ("failed", "enqueue_failed")

    queue = RecordingQueue()
    await _tick(db_session, queue, now=NOW + timedelta(minutes=15))
    assert [m.spec.kind for m in queue.messages] == ["collect_cwv"]
    await db_session.refresh(run)
    assert run.status == "queued" and run.error_code is None


async def test_archived_sites_and_disabled_schedules_are_not_due(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-disabled.test")
    db_session.add(
        Schedule(website_id=site.id, kind="collect_cwv", frequency="daily", enabled=False,
                 next_due_at=NOW - timedelta(days=1))
    )
    await db_session.flush()
    assert await due_schedules(db_session, now=NOW, limit=10) == []


async def test_stale_queued_runs_expire(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "tick-expire.test")
    db_session.add(
        JobRun(
            idempotency_key="old", kind="collect_probes", website_id=site.id,
            workspace_id=site.workspace_id, window_label="w", params={}, status="queued",
            attempt=0, max_attempts=5, observations=0, enqueued_at=NOW - timedelta(hours=3),
        )
    )
    await db_session.flush()
    assert await expire_stale_queued(db_session, now=NOW) == 1
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == "old"))
    await db_session.refresh(run)
    assert (run.status, run.error_code, run.recoverable) == ("failed", "not_dispatched", True)


async def test_plan_run_switches_to_regular_collection_after_the_backfill(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-plan.test")
    schedule = Schedule(website_id=site.id, kind="collect_gsc", frequency="daily",
                        enabled=True, next_due_at=NOW)
    assert plan_run(schedule, site, now=NOW) == RunSpec(
        "backfill", site.id, site.workspace_id, "gsc-20260926T0000", {"source": "gsc"}
    )
    schedule.backfill_done_at = NOW
    assert plan_run(schedule, site, now=NOW) == RunSpec(
        "collect_gsc", site.id, site.workspace_id, "20260926T0000"
    )


async def test_inline_queue_executes_in_process() -> None:
    seen: list[str] = []

    async def execute(spec: RunSpec) -> None:
        seen.append(spec.key)

    queue = InlineQueue(execute)
    spec = RunSpec("partition_maintenance", None, None, "20260926")
    await queue.enqueue(TaskMessage(spec, spec.queue))
    assert seen == queue.executed == ["partition_maintenance:global:20260926"]
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_jobs_scheduler.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.services.jobs.queue'`).

- [ ] **Étape 2 : écrire l'abstraction de file**

```python
# backend/app/services/jobs/queue.py
"""Files de tâches.

- `TaskQueue` : contrat commun ; `enqueue` lève `EnqueueError` si la tâche n'a pas pu
  être déposée (un doublon déjà présent n'est pas une erreur).
- `InlineQueue` : développement et tests. Exécute la tâche immédiatement dans le
  processus : aucun réseau, aucune nouvelle tentative, aucune limite de débit.
- `CloudTasksQueue` (production) : `app/services/jobs/cloud_tasks.py`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from app.services.jobs.kinds import QueueName, RunSpec


@dataclass(frozen=True, slots=True)
class TaskMessage:
    spec: RunSpec
    queue: QueueName


class EnqueueError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TaskQueue(Protocol):
    async def enqueue(self, message: TaskMessage) -> None: ...


class InlineQueue:
    def __init__(self, execute: Callable[[RunSpec], Awaitable[object]]) -> None:
        self._execute = execute
        self.executed: list[str] = []

    async def enqueue(self, message: TaskMessage) -> None:
        self.executed.append(message.spec.key)
        await self._execute(message.spec)
```

- [ ] **Étape 3 : écrire le planificateur**

```python
# backend/app/services/jobs/scheduler.py
"""Planificateur : appelé par Cloud Scheduler (`POST /internal/tick`, toutes les 15 min).

Un passage :
1. matérialise les plannings par défaut des sites actifs, expire les tâches restées en
   file plus de 2 h ; commit ;
2. réserve les plannings dus (`FOR UPDATE SKIP LOCKED` : deux passages concurrents ne
   prennent jamais le même), applique la limite quotidienne du workspace, avance
   `next_due_at` au créneau suivant et crée les lignes `job_runs` « en file » ; commit ;
3. dépose les tâches dans la file SANS transaction ouverte ;
4. une tâche non déposée redevient due (`next_due_at` restauré, ligne
   `enqueue_failed`) ; commit ;
5. publie la santé des tâches (logs, Sentry)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, literal, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.models.website import Website
from app.services.jobs.health import compute_jobs_health, report_jobs_health
from app.services.jobs.kinds import (
    BACKFILL_SOURCES,
    KINDS,
    SCHEDULABLE_KINDS,
    RunSpec,
    effective_interval,
    slot_label,
    slot_start,
)
from app.services.jobs.queue import EnqueueError, TaskMessage, TaskQueue

logger = logging.getLogger(__name__)

STALE_QUEUED_AFTER = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class TickResult:
    materialized: int
    enqueued: int
    capped: int
    failed_enqueue: int
    expired_queued: int


async def materialize_default_schedules(session: AsyncSession, *, now: datetime) -> int:
    created = 0
    for kind in SCHEDULABLE_KINDS:
        source = select(
            func.gen_random_uuid(),
            Website.id,
            literal(kind.name),
            literal(kind.default_frequency),
            true(),
            literal(now),
        ).where(Website.archived_at.is_(None))
        statement = (
            pg_insert(Schedule)
            .from_select(
                ["id", "website_id", "kind", "frequency", "enabled", "next_due_at"], source
            )
            .on_conflict_do_nothing(index_elements=["website_id", "kind"])
        )
        result = await session.execute(statement)
        created += result.rowcount or 0
    return created


async def expire_stale_queued(
    session: AsyncSession, *, now: datetime, older_than: timedelta = STALE_QUEUED_AFTER
) -> int:
    result = await session.execute(
        update(JobRun)
        .where(JobRun.status == "queued", JobRun.enqueued_at < now - older_than)
        .values(status="failed", error_code="not_dispatched", recoverable=True, finished_at=now)
    )
    return result.rowcount or 0


async def due_schedules(
    session: AsyncSession, *, now: datetime, limit: int
) -> list[tuple[Schedule, Website]]:
    rows = await session.execute(
        select(Schedule, Website)
        .join(Website, Website.id == Schedule.website_id)
        .where(
            Schedule.enabled.is_(True),
            Schedule.next_due_at <= now,
            Website.archived_at.is_(None),
        )
        .order_by(Schedule.next_due_at)
        .limit(limit)
        .with_for_update(of=Schedule, skip_locked=True)
    )
    return [(schedule, website) for schedule, website in rows.all()]


def plan_run(schedule: Schedule, website: Website, *, now: datetime) -> RunSpec:
    kind = KINDS[schedule.kind]
    label = slot_label(slot_start(now, effective_interval(kind, schedule.frequency)))
    if kind.source in BACKFILL_SOURCES and schedule.backfill_done_at is None:
        return RunSpec(
            "backfill", website.id, website.workspace_id, f"{kind.source}-{label}",
            {"source": kind.source},
        )
    return RunSpec(kind.name, website.id, website.workspace_id, label)


async def insert_queued(
    session: AsyncSession, spec: RunSpec, *, now: datetime, max_attempts: int
) -> bool:
    """Crée la ligne « en file » ; vrai si elle est nouvelle, ou si un dépôt précédent
    de la même tâche avait échoué (elle repart en file)."""
    result = await session.execute(
        pg_insert(JobRun)
        .values(
            id=uuid4(),
            idempotency_key=spec.key,
            kind=spec.kind,
            website_id=spec.website_id,
            workspace_id=spec.workspace_id,
            window_label=spec.window,
            params=dict(spec.params),
            status="queued",
            attempt=0,
            max_attempts=max_attempts,
            enqueued_at=now,
            observations=0,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(JobRun.id)
    )
    if result.scalar_one_or_none() is not None:
        return True
    reset = await session.execute(
        update(JobRun)
        .where(
            JobRun.idempotency_key == spec.key,
            JobRun.status == "failed",
            JobRun.error_code == "enqueue_failed",
        )
        .values(status="queued", error_code=None, recoverable=None, finished_at=None)
    )
    return (reset.rowcount or 0) > 0


async def runs_today(session: AsyncSession, workspace_id: UUID, *, now: datetime) -> int:
    midnight = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    count = await session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.workspace_id == workspace_id, JobRun.enqueued_at >= midnight)
    )
    return count or 0


async def tick(
    session: AsyncSession,
    queue: TaskQueue,
    *,
    now: datetime,
    batch: int,
    daily_cap: int,
    max_attempts: int,
) -> TickResult:
    materialized = await materialize_default_schedules(session, now=now)
    expired = await expire_stale_queued(session, now=now)
    await session.commit()

    # (planning ou None pour la maintenance, échéance précédente, tâche)
    planned: list[tuple[Schedule | None, datetime | None, RunSpec]] = []
    counts: dict[UUID, int] = {}
    capped = 0
    for schedule, website in await due_schedules(session, now=now, limit=batch):
        workspace_id = website.workspace_id
        if workspace_id not in counts:
            counts[workspace_id] = await runs_today(session, workspace_id, now=now)
        if counts[workspace_id] >= daily_cap:
            capped += 1
            continue
        counts[workspace_id] += 1
        spec = plan_run(schedule, website, now=now)
        previous_due = schedule.next_due_at
        interval = effective_interval(KINDS[schedule.kind], schedule.frequency)
        schedule.next_due_at = slot_start(now, interval) + interval
        if await insert_queued(session, spec, now=now, max_attempts=max_attempts):
            planned.append((schedule, previous_due, spec))
    maintenance = RunSpec("partition_maintenance", None, None, now.strftime("%Y%m%d"))
    if await insert_queued(session, maintenance, now=now, max_attempts=max_attempts):
        planned.append((None, None, maintenance))
    await session.commit()

    enqueued = 0
    failed: list[tuple[Schedule | None, datetime | None, RunSpec]] = []
    for item in planned:
        spec = item[2]
        try:
            await queue.enqueue(TaskMessage(spec, spec.queue))
        except EnqueueError as exc:
            logger.warning(
                "dépôt de tâche en échec",
                extra={"event": "job_enqueue_failed", "job_key": spec.key, "reason": exc.reason},
            )
            failed.append(item)
        else:
            enqueued += 1

    for schedule, previous_due, spec in failed:
        if schedule is not None and previous_due is not None:
            # Par l'ORM (objet encore chargé, `expire_on_commit=False`) : une mise à jour
            # SQL directe laisserait l'objet en mémoire périmé.
            schedule.next_due_at = previous_due
        await session.execute(
            update(JobRun)
            .where(JobRun.idempotency_key == spec.key, JobRun.status == "queued")
            .values(status="failed", error_code="enqueue_failed", recoverable=True, finished_at=now)
        )
    if failed:
        await session.commit()

    report_jobs_health(await compute_jobs_health(session, now=now))
    await session.commit()
    return TickResult(
        materialized=materialized,
        enqueued=enqueued,
        capped=capped,
        failed_enqueue=len(failed),
        expired_queued=expired,
    )
```

- [ ] **Étape 4 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_jobs_scheduler.py tests/test_jobs_runner.py -v
uv run ruff check app tests
```

Attendu : tous verts.

- [ ] **Étape 5 : commit**

```bash
git add backend/app/services/jobs/queue.py backend/app/services/jobs/scheduler.py backend/tests/jobs_fakes.py backend/tests/test_jobs_scheduler.py
git commit -m "feat(taches): planificateur tick (plannings par defaut, creneaux, limite quotidienne) et file InlineQueue

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 10 : `CloudTasksQueue`, jetons du serveur de métadonnées et vérification OIDC

**Fichiers :**
- Modifier : `backend/app/config.py` (réglages files et appels internes)
- Modifier : `backend/pyproject.toml`, `backend/uv.lock` (dépendance `pyjwt[crypto]`)
- Créer : `backend/app/services/gcp_metadata.py`,
  `backend/app/services/jobs/cloud_tasks.py`, `backend/app/security/oidc.py`
- Test : `backend/tests/test_jobs_cloud_tasks.py`, `backend/tests/test_oidc.py`

**Interfaces :**
- Consomme : `TaskMessage`, `EnqueueError` (Tâche 9) ; `RunSpec.to_payload()`,
  `QueueName` (Tâche 7).
- Produit (`app.config.Settings`, tous optionnels) :
  `task_queue_backend: Literal["inline", "cloud_tasks"] = "inline"`,
  `gcp_project: str = ""`, `cloud_tasks_location: str = ""`,
  `cloud_tasks_queue_prefix: str = "guiili"`, `tasks_invoker_service_account: str = ""`,
  `worker_base_url: str = ""`, `internal_oidc_audience: str = ""`,
  `internal_allowed_invokers: list[str] = []`.
- Produit (`app.services.gcp_metadata`) : `MetadataError`,
  `AccessTokenProvider` / `IdentityTokenProvider` (Protocols),
  `MetadataTokenProvider(*, client=None, clock=time.monotonic)` avec
  `async access_token() -> str` et `async identity_token(audience: str) -> str`
  (mis en cache jusqu'à 60 s avant expiration).
- Produit (`app.services.jobs.cloud_tasks`) : `task_id_for(key: str) -> str`,
  `CloudTasksQueue(*, project, location, queue_prefix, target_url, invoker_email,
  audience, tokens: AccessTokenProvider, client=None, dispatch_deadline_seconds=900)`
  implémentant `TaskQueue` (409 = déjà déposée = succès).
- Produit (`app.security.oidc`) : `GOOGLE_ISSUERS`, `GOOGLE_CERTS_URL`,
  `OidcError(reason)` (raisons : `not_configured`, `invalid_token`, `unknown_key`,
  `wrong_issuer`, `email_not_verified`, `caller_not_allowed`, `jwks_unavailable`),
  `OidcIdentity(email: str, subject: str)`, `JwksFetcher`,
  `fetch_google_jwks(client=None) -> dict`, `OidcVerifier(*, audience, allowed_emails,
  fetch_jwks=fetch_google_jwks, cache_seconds=3600, clock=time.monotonic,
  leeway_seconds=30)` avec `async verify(token: str) -> OidcIdentity`.

- [ ] **Étape 1 : ajouter la dépendance**

```bash
cd backend
uv add "pyjwt[crypto]>=2.10"
```

Attendu : `pyproject.toml` gagne `"pyjwt[crypto]>=2.10"` dans `dependencies`, `uv.lock`
est mis à jour. (Justification : vérifier la signature RS256 d'un jeton d'identité
Google ; `cryptography` est déjà présent. Les bibliothèques Google Cloud ne sont pas
ajoutées : REST + httpx suffisent et restent testables par `MockTransport`.)

- [ ] **Étape 2 : écrire les tests qui échouent**

```python
# backend/tests/test_oidc.py
import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.security.oidc import OidcError, OidcVerifier

AUDIENCE = "https://worker.example.run.app"
CALLER = "guiili-tasks@guiili.iam.gserviceaccount.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(number: int) -> str:
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwks(key, kid: str = "k1") -> dict:
    numbers = key.public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256",
                      "n": _b64(numbers.n), "e": _b64(numbers.e)}]}


def _token(*, key=KEY, kid: str = "k1", **overrides) -> str:
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": AUDIENCE, "email": CALLER,
              "email_verified": True, "sub": "1234", "iat": now, "exp": now + 600}
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def _verifier(jwks: dict | None = None, calls: list | None = None) -> OidcVerifier:
    async def fetch() -> dict:
        if calls is not None:
            calls.append(1)
        return jwks or _jwks(KEY)

    return OidcVerifier(audience=AUDIENCE, allowed_emails={CALLER}, fetch_jwks=fetch)


async def test_a_valid_google_token_is_accepted_and_keys_are_cached() -> None:
    calls: list = []
    verifier = _verifier(calls=calls)
    identity = await verifier.verify(_token())
    assert identity.email == CALLER and identity.subject == "1234"
    await verifier.verify(_token())
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("token_kwargs", "reason"),
    [
        ({"aud": "https://autre.run.app"}, "invalid_token"),
        ({"exp": int(time.time()) - 3600}, "invalid_token"),
        ({"iss": "https://evil.example"}, "wrong_issuer"),
        ({"email_verified": False}, "email_not_verified"),
        ({"email": "intrus@example.com"}, "caller_not_allowed"),
        ({"key": OTHER_KEY}, "invalid_token"),
        ({"kid": "inconnue"}, "unknown_key"),
    ],
)
async def test_bad_tokens_are_refused(token_kwargs: dict, reason: str) -> None:
    with pytest.raises(OidcError) as excinfo:
        await _verifier().verify(_token(**token_kwargs))
    assert excinfo.value.reason == reason


async def test_garbage_and_hs256_tokens_are_refused() -> None:
    verifier = _verifier()
    with pytest.raises(OidcError):
        await verifier.verify("pas-un-jeton")
    forged = jwt.encode({"aud": AUDIENCE, "email": CALLER}, "secret", algorithm="HS256",
                        headers={"kid": "k1"})
    with pytest.raises(OidcError) as excinfo:
        await verifier.verify(forged)
    assert excinfo.value.reason == "invalid_token"


async def test_an_unconfigured_verifier_refuses_everything() -> None:
    verifier = OidcVerifier(audience="", allowed_emails=set(), fetch_jwks=None)  # type: ignore[arg-type]
    with pytest.raises(OidcError) as excinfo:
        await verifier.verify(_token())
    assert excinfo.value.reason == "not_configured"
```

```python
# backend/tests/test_jobs_cloud_tasks.py
import base64
import json

import httpx
import pytest

from app.services.gcp_metadata import MetadataError, MetadataTokenProvider
from app.services.jobs.cloud_tasks import CloudTasksQueue, task_id_for
from app.services.jobs.kinds import RunSpec
from app.services.jobs.queue import EnqueueError, TaskMessage

TARGET = "https://worker.example.run.app/internal/tasks/run"


class _Tokens:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def access_token(self) -> str:
        if self.fail:
            raise MetadataError("indisponible")
        return "jeton-acces"


def _queue(handler, tokens: _Tokens | None = None) -> CloudTasksQueue:
    return CloudTasksQueue(
        project="guiili",
        location="us-central1",
        queue_prefix="guiili",
        target_url=TARGET,
        invoker_email="guiili-tasks@guiili.iam.gserviceaccount.com",
        audience="https://worker.example.run.app",
        tokens=tokens or _Tokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


SPEC = RunSpec("backfill", None, None, "ga4-20260926T0000", {"source": "ga4"})


def test_task_ids_are_stable_and_valid() -> None:
    first = task_id_for(SPEC.key)
    assert first == task_id_for(SPEC.key)
    assert first.startswith("t-") and len(first) == 66
    assert all(c.isalnum() or c in "-_" for c in first)


async def test_a_task_is_created_in_its_source_queue_with_an_oidc_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"name": "ok"})

    await _queue(handler).enqueue(TaskMessage(SPEC, SPEC.queue))
    request = seen[0]
    assert request.url.path == "/v2/projects/guiili/locations/us-central1/queues/guiili-ga4/tasks"
    assert request.headers["Authorization"] == "Bearer jeton-acces"
    task = json.loads(request.content)["task"]
    assert task["name"].endswith(f"/tasks/{task_id_for(SPEC.key)}")
    assert task["dispatchDeadline"] == "900s"
    http_request = task["httpRequest"]
    assert http_request["url"] == TARGET and http_request["httpMethod"] == "POST"
    assert http_request["oidcToken"] == {
        "serviceAccountEmail": "guiili-tasks@guiili.iam.gserviceaccount.com",
        "audience": "https://worker.example.run.app",
    }
    assert json.loads(base64.b64decode(http_request["body"])) == SPEC.to_payload()


async def test_an_already_existing_task_is_not_an_error() -> None:
    await _queue(lambda request: httpx.Response(409, json={})).enqueue(TaskMessage(SPEC, "ga4"))


@pytest.mark.parametrize("status", [400, 403, 429, 500])
async def test_other_http_errors_raise_enqueue_error(status: int) -> None:
    with pytest.raises(EnqueueError) as excinfo:
        await _queue(lambda request: httpx.Response(status, json={})).enqueue(
            TaskMessage(SPEC, "ga4")
        )
    assert excinfo.value.reason == f"http_{status}"


async def test_network_and_credential_failures_raise_enqueue_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(EnqueueError) as network:
        await _queue(boom).enqueue(TaskMessage(SPEC, "ga4"))
    assert network.value.reason == "network"
    with pytest.raises(EnqueueError) as credentials:
        await _queue(lambda r: httpx.Response(200), _Tokens(fail=True)).enqueue(
            TaskMessage(SPEC, "ga4")
        )
    assert credentials.value.reason == "credentials"


async def test_metadata_tokens_are_cached_until_near_expiry() -> None:
    calls: list[str] = []
    clock = [1000.0]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Metadata-Flavor"] == "Google"
        calls.append(request.url.path)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": f"a{len(calls)}", "expires_in": 3599})
        assert request.url.params["audience"] == "https://worker.example.run.app"
        return httpx.Response(200, text=f"id{len(calls)}")

    provider = MetadataTokenProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), clock=lambda: clock[0]
    )
    assert await provider.access_token() == "a1"
    assert await provider.access_token() == "a1"
    clock[0] += 3599 - 30  # moins de 60 s avant l'expiration : renouvelé
    assert await provider.access_token() == "a2"
    assert await provider.identity_token("https://worker.example.run.app") == "id3"
    assert await provider.identity_token("https://worker.example.run.app") == "id3"


async def test_metadata_failure_raises_metadata_error() -> None:
    provider = MetadataTokenProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    )
    with pytest.raises(MetadataError):
        await provider.access_token()
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_oidc.py tests/test_jobs_cloud_tasks.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.security.oidc'`).

- [ ] **Étape 3 : ajouter les réglages**

Dans `backend/app/config.py`, en tête de fichier, `Literal` est déjà importé. Après le
bloc « Tâches planifiées (lot B) » ajouté à la Tâche 7 :

```python
    # --- Files et appels internes (lot B) ---
    # "inline" : exécution dans le processus (local, tests). "cloud_tasks" : production.
    task_queue_backend: Literal["inline", "cloud_tasks"] = "inline"
    gcp_project: str = ""
    cloud_tasks_location: str = ""
    # Files « {préfixe}-{ga4|gsc|cwv|light|heavy} » (ex. guiili-staging-ga4).
    cloud_tasks_queue_prefix: str = "guiili"
    # Compte de service dont Cloud Tasks joint le jeton OIDC en appelant le worker.
    tasks_invoker_service_account: str = ""
    # URL https du service worker (appels internes, délégation headless).
    worker_base_url: str = ""
    # Audience attendue des jetons OIDC reçus par le worker (en général = worker_base_url).
    internal_oidc_audience: str = ""
    # E-mails des comptes autorisés à appeler /internal/* (Scheduler, Tasks, API).
    internal_allowed_invokers: list[str] = []
```

- [ ] **Étape 4 : écrire les jetons de métadonnées**

```python
# backend/app/services/gcp_metadata.py
"""Jetons du compte de service d'exécution, lus sur le serveur de métadonnées de Cloud
Run (aucune bibliothèque Google, aucun fichier de clé). Jamais appelé en test : les
tests injectent un client httpx factice."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

import httpx

_BASE = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default"
_HEADERS = {"Metadata-Flavor": "Google"}
_TIMEOUT = httpx.Timeout(5.0)
_MARGIN_SECONDS = 60.0
# Un jeton d'identité Google vit une heure ; on le renouvelle au bout de 50 minutes.
_IDENTITY_TTL_SECONDS = 3000.0


class MetadataError(Exception):
    """Jeton indisponible (hors Cloud Run, serveur de métadonnées en erreur)."""


class AccessTokenProvider(Protocol):
    async def access_token(self) -> str: ...


class IdentityTokenProvider(Protocol):
    async def identity_token(self, audience: str) -> str: ...


class MetadataTokenProvider:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._clock = clock
        self._access: tuple[str, float] | None = None
        self._identity: dict[str, tuple[str, float]] = {}

    async def _get(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            response = await http.get(f"{_BASE}{path}", params=params, headers=_HEADERS)
        except httpx.HTTPError:
            raise MetadataError("serveur de métadonnées injoignable") from None
        finally:
            if owns:
                await http.aclose()
        if response.status_code != 200:
            raise MetadataError(f"serveur de métadonnées : HTTP {response.status_code}")
        return response

    async def access_token(self) -> str:
        now = self._clock()
        if self._access is not None and self._access[1] - _MARGIN_SECONDS > now:
            return self._access[0]
        response = await self._get("/token")
        try:
            payload = response.json()
            token, expires_in = str(payload["access_token"]), float(payload["expires_in"])
        except (ValueError, KeyError, TypeError):
            raise MetadataError("réponse de jeton illisible") from None
        self._access = (token, now + expires_in)
        return token

    async def identity_token(self, audience: str) -> str:
        now = self._clock()
        cached = self._identity.get(audience)
        if cached is not None and cached[1] > now:
            return cached[0]
        response = await self._get("/identity", {"audience": audience, "format": "full"})
        token = response.text.strip()
        if not token:
            raise MetadataError("jeton d'identité vide")
        self._identity[audience] = (token, now + _IDENTITY_TTL_SECONDS)
        return token
```

- [ ] **Étape 5 : écrire la file Cloud Tasks**

```python
# backend/app/services/jobs/cloud_tasks.py
"""File Cloud Tasks (API REST v2). Une file par source (quotas Google) : le débit, les
nouvelles tentatives et le backoff sont réglés sur la file (runbook). Chaque tâche porte
un jeton OIDC du compte `tasks_invoker_service_account`, vérifié par le worker. Le nom
de la tâche dérive de la clé d'idempotence : Cloud Tasks refuse un doublon (409)."""

from __future__ import annotations

import base64
import hashlib
import json

import httpx

from app.services.gcp_metadata import AccessTokenProvider, MetadataError
from app.services.jobs.queue import EnqueueError, TaskMessage

_API = "https://cloudtasks.googleapis.com/v2/{parent}/tasks"
_TIMEOUT = httpx.Timeout(10.0)


def task_id_for(key: str) -> str:
    return "t-" + hashlib.sha256(key.encode("utf-8")).hexdigest()


class CloudTasksQueue:
    def __init__(
        self,
        *,
        project: str,
        location: str,
        queue_prefix: str,
        target_url: str,
        invoker_email: str,
        audience: str,
        tokens: AccessTokenProvider,
        client: httpx.AsyncClient | None = None,
        dispatch_deadline_seconds: int = 900,
    ) -> None:
        self._project = project
        self._location = location
        self._prefix = queue_prefix
        self._target_url = target_url
        self._invoker_email = invoker_email
        self._audience = audience
        self._tokens = tokens
        self._client = client
        self._deadline = dispatch_deadline_seconds

    async def enqueue(self, message: TaskMessage) -> None:
        parent = (
            f"projects/{self._project}/locations/{self._location}"
            f"/queues/{self._prefix}-{message.queue}"
        )
        body = json.dumps(message.spec.to_payload(), separators=(",", ":")).encode("utf-8")
        task = {
            "name": f"{parent}/tasks/{task_id_for(message.spec.key)}",
            "dispatchDeadline": f"{self._deadline}s",
            "httpRequest": {
                "httpMethod": "POST",
                "url": self._target_url,
                "headers": {"Content-Type": "application/json"},
                "body": base64.b64encode(body).decode("ascii"),
                "oidcToken": {
                    "serviceAccountEmail": self._invoker_email,
                    "audience": self._audience,
                },
            },
        }
        try:
            token = await self._tokens.access_token()
        except MetadataError:
            raise EnqueueError("credentials") from None
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            response = await http.post(
                _API.format(parent=parent),
                json={"task": task},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError:
            raise EnqueueError("network") from None
        finally:
            if owns:
                await http.aclose()
        if response.status_code == 409:  # déjà déposée : c'est le but de la clé
            return
        if response.status_code >= 400:
            raise EnqueueError(f"http_{response.status_code}")
```

- [ ] **Étape 6 : écrire la vérification OIDC**

```python
# backend/app/security/oidc.py
"""Vérification des jetons d'identité (OIDC) Google reçus par les routes internes.

Contrôles : signature RS256 avec une clé publique Google (JWKS, mise en cache une
heure, relue une fois si l'identifiant de clé est inconnu), audience, expiration,
émetteur Google, e-mail vérifié et présent dans la liste des appelants autorisés
(comptes de service de Cloud Scheduler, de Cloud Tasks et de l'API). Sans audience ou
sans liste d'appelants, tout est refusé."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_TIMEOUT = httpx.Timeout(5.0)

JwksFetcher = Callable[[], Awaitable[dict[str, Any]]]


class OidcError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class OidcIdentity:
    email: str
    subject: str


async def fetch_google_jwks(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        response = await http.get(GOOGLE_CERTS_URL)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise OidcError("jwks_unavailable") from None
    finally:
        if owns:
            await http.aclose()
    if not isinstance(payload, dict):
        raise OidcError("jwks_unavailable")
    return payload


class OidcVerifier:
    def __init__(
        self,
        *,
        audience: str,
        allowed_emails: Iterable[str],
        fetch_jwks: JwksFetcher = fetch_google_jwks,
        cache_seconds: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
        leeway_seconds: int = 30,
    ) -> None:
        self._audience = audience
        self._allowed = frozenset(email.lower() for email in allowed_emails)
        self._fetch = fetch_jwks
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._leeway = leeway_seconds
        self._keys: dict[str, Any] = {}
        self._loaded_at: float | None = None

    async def _refresh(self) -> None:
        payload = await self._fetch()
        keys: dict[str, Any] = {}
        for entry in payload.get("keys", []) if isinstance(payload.get("keys"), list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("kid"), str):
                continue
            try:
                keys[entry["kid"]] = jwt.PyJWK(entry).key
            except jwt.PyJWTError:
                continue
        self._keys = keys
        self._loaded_at = self._clock()

    async def _key(self, kid: str) -> Any:
        stale = self._loaded_at is None or self._clock() - self._loaded_at > self._cache_seconds
        if stale or kid not in self._keys:
            await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise OidcError("unknown_key")
        return key

    async def verify(self, token: str) -> OidcIdentity:
        if not self._audience or not self._allowed:
            raise OidcError("not_configured")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise OidcError("invalid_token") from None
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str):
            raise OidcError("invalid_token")
        key = await self._key(kid)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
        except jwt.PyJWTError:
            raise OidcError("invalid_token") from None
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise OidcError("wrong_issuer")
        if claims.get("email_verified") is not True:
            raise OidcError("email_not_verified")
        email = str(claims.get("email", "")).lower()
        if email not in self._allowed:
            raise OidcError("caller_not_allowed")
        return OidcIdentity(email=email, subject=str(claims.get("sub", "")))
```

- [ ] **Étape 7 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_oidc.py tests/test_jobs_cloud_tasks.py tests/test_config_guard.py tests/test_deploy_assets.py -v
uv run ruff check app tests
```

Attendu : tous verts (les réglages ajoutés sont optionnels : `test_config_guard.py` et
`test_deploy_assets.py` restent verts sans modification).

- [ ] **Étape 8 : commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/config.py backend/app/services/gcp_metadata.py backend/app/services/jobs/cloud_tasks.py backend/app/security/oidc.py backend/tests/test_oidc.py backend/tests/test_jobs_cloud_tasks.py
git commit -m "feat(taches): file Cloud Tasks (REST), jetons du serveur de metadonnees et verification OIDC des appels internes

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 11 : Gestionnaires des types de tâches (collecte, rattrapage, vérification du plan, maintenance) et disjoncteur

**Fichiers :**
- Créer : `backend/app/services/metrics/sources/factory.py`,
  `backend/app/services/jobs/handlers.py`
- Modifier : `backend/tests/jobs_fakes.py` (ajouts : `FakeSource`, `UnlinkedReader`,
  `offline_fetcher`, `fake_services`)
- Test : `backend/tests/test_jobs_handlers.py`

**Interfaces :**
- Consomme : `MetricSource`, `SOURCE_SPECS`, `SourceError`, `utc_today`, `utc_now`
  (Tâche 2) ; `store_observations` (Tâche 3) ; `ensure_partitions`, `purge_expired`
  (Tâche 4) ; `Ga4Source`, `GscSource`, `resolve_google_credentials` (Tâche 5) ;
  `CwvSource`, `ProbeSource` (Tâche 6) ; `HandlerOutcome`, `Handler`, `lock_key`,
  `COLLECT_KIND_BY_SOURCE`, `BACKFILL_SOURCES` (Tâche 7) ; `refresh_plan`,
  `ReaderFactory` (`app.services.measurement.service`) ; `PageFetcher`
  (`app.services.measurement.fetch`) ; `TlsChecker` (`app.services.audit_engine`) ;
  `GtmHeadlessResult` (`app.services.gtm_headless`).
- Produit (`app.services.metrics.sources.factory`) :
  `SourceFactory = Callable[[AsyncSession, Website, str], Awaitable[MetricSource]]`,
  `default_source_factory(*, pagespeed_api_key: str | None, oauth, cipher,
  tls_checker, page_fetcher) -> SourceFactory` (noms de source : `ga4`, `gsc`, `cwv`,
  `probe` ; autre ⇒ `SourceError("unknown_source", recoverable=False)`).
- Produit (`app.services.jobs.handlers`) :
  - `JobServices(source_factory, page_fetcher, reader_factory, today=utc_today,
    now=utc_now)` ;
  - `BREAKER_WINDOW = timedelta(minutes=30)`, `BREAKER_THRESHOLD = 3`,
    `JOB_RUNS_RETENTION = timedelta(days=90)` ;
  - `quota_breaker_open(session, *, workspace_id, source, now) -> bool` ;
  - `purge_old_job_runs(session, *, now, keep=JOB_RUNS_RETENTION) -> int` ;
  - `build_handlers(services: JobServices) -> dict[str, Handler]` couvrant **tous**
    les noms de `KINDS`.
  - Contrats : collecte ⇒ fenêtre courte `spec.regular_window(today)` ; rattrapage ⇒
    `spec.backfill_window(today)` découpée en tranches committées une par une ;
    `measurement_check` ⇒ `refresh_plan(..., run_headless=False)` (le navigateur n'est
    jamais lancé) ; `partition_maintenance` ⇒ verrou `partition_maintenance`, création
    M-4..M+3, purge 25 mois, purge des `job_runs` terminés depuis plus de 90 jours.
    La résolution des jetons Google est committée AVANT la collecte réseau.

- [ ] **Étape 1 : écrire les tests qui échouent**

Ajouter à `backend/tests/jobs_fakes.py` (imports à regrouper en tête du fichier) :

```python
from collections.abc import Sequence
from datetime import UTC, date, datetime

from app.services.jobs.handlers import JobServices
from app.services.measurement.google_reader import GoogleReadError
from app.services.metrics.types import SOURCE_SPECS, DayRange, Observation, SourceError

TODAY = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 6, 7, tzinfo=UTC)


class FakeSource:
    """Source factice : renvoie les observations comprises dans la fenêtre demandée."""

    def __init__(
        self, name: str, observations: Sequence[Observation] = (), error: SourceError | None = None
    ) -> None:
        self.spec = SOURCE_SPECS[name]
        self._observations = list(observations)
        self._error = error
        self.calls: list[DayRange] = []

    async def collect(self, website, day_range: DayRange) -> list[Observation]:
        self.calls.append(day_range)
        if self._error is not None:
            raise self._error
        return [obs for obs in self._observations if day_range.contains(obs.day)]


class UnlinkedReader:
    """Lecteur Google d'un site sans GA4 ni Search Console reliés (aucun réseau)."""

    gsc_state = "not_linked"

    async def event_stats(self):
        raise GoogleReadError("ga4_not_connected")

    key_events = ads_links_count = measurement_id = event_stats

    async def sitemaps_count(self):
        raise GoogleReadError("gsc_not_connected")


async def offline_fetcher(url: str, *, allow_insecure: bool = False):
    _ = (url, allow_insecure)
    return None  # site injoignable : aucun DNS, aucun réseau


async def unlinked_reader_factory(session, website) -> UnlinkedReader:
    _ = (session, website)
    return UnlinkedReader()


def fake_services(sources: dict[str, FakeSource], calls: list[str] | None = None) -> JobServices:
    async def factory(session, website, name: str):
        if calls is not None:
            calls.append(name)
        return sources[name]

    return JobServices(
        source_factory=factory,
        page_fetcher=offline_fetcher,
        reader_factory=unlinked_reader_factory,
        today=lambda: TODAY,
        now=lambda: NOW,
    )
```

```python
# backend/tests/test_jobs_handlers.py
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.measurement_item_status import MeasurementItemStatus
from app.models.metric_point import MetricPoint
from app.models.schedule import Schedule
from app.services.jobs.handlers import build_handlers, purge_old_job_runs, quota_breaker_open
from app.services.jobs.kinds import KINDS, RunSpec
from app.services.jobs.runner import execute_run
from app.services.metrics.partitions import list_partitions
from app.services.metrics.sources.cwv import CwvSource
from app.services.metrics.sources.factory import default_source_factory
from app.services.metrics.sources.probes import ProbeSource
from app.services.metrics.types import DayRange, Observation, SourceError
from tests.jobs_fakes import (
    LIMITS,
    NOW,
    FakeSource,
    fake_services,
    make_site,
    offline_fetcher,
)


def _clock():
    return NOW


def test_every_kind_has_a_handler() -> None:
    assert set(build_handlers(fake_services({}))) == set(KINDS)


async def test_collect_stores_the_regular_window_with_the_run_id(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-collect.test")
    ga4 = FakeSource("ga4", [Observation("sessions", date(2026, 9, 24), 12.0),
                             Observation("sessions", date(2026, 6, 1), 99.0)])
    handlers = build_handlers(fake_services({"ga4": ga4}))
    spec = RunSpec("collect_ga4", site.id, site.workspace_id, "20260926T0000")
    result = await execute_run(db_session, spec, handlers=handlers, limits=LIMITS, clock=_clock)
    assert result.status == "succeeded"
    assert ga4.calls == [DayRange(date(2026, 9, 23), date(2026, 9, 25))]
    point = await db_session.scalar(select(MetricPoint).where(MetricPoint.website_id == site.id))
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == spec.key))
    assert (point.day, point.value, point.run_id) == (date(2026, 9, 24), 12.0, run.id)
    assert run.observations == 1


async def test_backfill_collects_90_days_in_chunks_and_marks_the_schedule(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-backfill.test")
    db_session.add(Schedule(website_id=site.id, kind="collect_gsc", frequency="daily",
                            enabled=True, next_due_at=NOW))
    await db_session.flush()
    gsc = FakeSource("gsc", [Observation("clicks", date(2026, 7, 1), 3.0)])
    spec = RunSpec("backfill", site.id, site.workspace_id, "gsc-20260926T0000", {"source": "gsc"})
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({"gsc": gsc})), limits=LIMITS,
        clock=_clock,
    )
    assert result.status == "succeeded"
    assert [c.length for c in gsc.calls] == [31, 31, 28]
    assert gsc.calls[-1].end == date(2026, 9, 23)
    schedule = await db_session.scalar(select(Schedule).where(Schedule.website_id == site.id))
    assert schedule.backfill_done_at == NOW


async def test_an_unlinked_source_is_skipped(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "h-unlinked.test")
    ga4 = FakeSource(
        "ga4", error=SourceError("ga4_not_connected", recoverable=False, not_applicable=True)
    )
    spec = RunSpec("collect_ga4", site.id, site.workspace_id, "w")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({"ga4": ga4})), limits=LIMITS,
        clock=_clock,
    )
    assert (result.status, result.retry) == ("skipped", False)


async def test_an_archived_site_is_skipped_without_collecting(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-archived.test")
    site.archived_at = NOW
    await db_session.flush()
    calls: list[str] = []
    spec = RunSpec("collect_probes", site.id, site.workspace_id, "w")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({}, calls)), limits=LIMITS,
        clock=_clock,
    )
    assert result.status == "skipped" and calls == []


async def test_repeated_quota_errors_open_the_breaker(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "h-breaker.test")
    for index in range(3):
        db_session.add(
            JobRun(
                idempotency_key=f"q{index}", kind="collect_ga4", website_id=site.id,
                workspace_id=site.workspace_id, window_label="w", params={}, status="failed",
                error_code="quota", recoverable=True, attempt=1, max_attempts=5,
                observations=0, finished_at=NOW - timedelta(minutes=10),
            )
        )
    await db_session.flush()
    assert await quota_breaker_open(db_session, workspace_id=site.workspace_id, source="ga4", now=NOW)
    assert not await quota_breaker_open(
        db_session, workspace_id=site.workspace_id, source="gsc", now=NOW
    )
    calls: list[str] = []
    spec = RunSpec("collect_ga4", site.id, site.workspace_id, "breaker")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({}, calls)), limits=LIMITS,
        clock=_clock,
    )
    assert (result.status, result.retry) == ("failed", True)
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == spec.key))
    assert run.error_code == "circuit_open" and calls == []


async def test_the_scheduled_plan_check_never_launches_a_browser(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-plan.test")
    spec = RunSpec("measurement_check", site.id, site.workspace_id, "w")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({})), limits=LIMITS, clock=_clock
    )
    assert result.status == "succeeded"
    statuses = await db_session.scalar(
        select(func.count())
        .select_from(MeasurementItemStatus)
        .where(MeasurementItemStatus.website_id == site.id)
    )
    assert statuses > 0


async def test_partition_maintenance_creates_months_and_purges_old_runs(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-maint.test")
    db_session.add(
        JobRun(
            idempotency_key="ancienne", kind="collect_probes", website_id=site.id,
            workspace_id=site.workspace_id, window_label="w", params={}, status="succeeded",
            attempt=1, max_attempts=5, observations=0, finished_at=NOW - timedelta(days=91),
        )
    )
    await db_session.flush()
    spec = RunSpec("partition_maintenance", None, None, "20260926")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({})), limits=LIMITS, clock=_clock
    )
    assert result.status == "succeeded"
    names = {p.name for p in await list_partitions(db_session)}
    assert {"metric_points_p2026_09", "metric_points_p2026_12"} <= names
    assert await db_session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.idempotency_key == "ancienne")
    ) == 0


async def test_purge_old_job_runs_keeps_unfinished_and_recent_runs(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-purge.test")
    for key, finished in (("vieux", NOW - timedelta(days=100)), ("recent", NOW), ("encours", None)):
        db_session.add(
            JobRun(
                idempotency_key=key, kind="collect_probes", website_id=site.id,
                workspace_id=site.workspace_id, window_label="w", params={},
                status="running" if finished is None else "succeeded", attempt=1,
                max_attempts=5, observations=0, finished_at=finished,
            )
        )
    await db_session.flush()
    assert await purge_old_job_runs(db_session, now=NOW) == 1


async def test_default_factory_builds_the_light_sources() -> None:
    async def tls(domain):
        raise AssertionError("aucun appel attendu")

    factory = default_source_factory(
        pagespeed_api_key=None, oauth=None, cipher=None, tls_checker=tls, page_fetcher=offline_fetcher
    )
    assert isinstance(await factory(None, None, "cwv"), CwvSource)
    assert isinstance(await factory(None, None, "probe"), ProbeSource)
    with pytest.raises(SourceError) as excinfo:
        await factory(None, None, "inconnue")
    assert excinfo.value.reason == "unknown_source" and not excinfo.value.recoverable
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_jobs_handlers.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.services.jobs.handlers'`).

- [ ] **Étape 2 : écrire la fabrique de sources**

```python
# backend/app/services/metrics/sources/factory.py
"""Construit la `MetricSource` d'un site pour une source donnée. Les sources Google
lisent les jetons des liaisons du site (base + rafraîchissement OAuth) : l'appelant
committe ensuite, AVANT de lancer la collecte réseau."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website import Website
from app.services.audit_engine import TlsChecker
from app.services.measurement.fetch import PageFetcher
from app.services.metrics.sources.credentials import resolve_google_credentials
from app.services.metrics.sources.cwv import CwvSource
from app.services.metrics.sources.ga4 import Ga4Source
from app.services.metrics.sources.gsc import GscSource
from app.services.metrics.sources.probes import ProbeSource
from app.services.metrics.types import MetricSource, SourceError

SourceFactory = Callable[[AsyncSession, Website, str], Awaitable[MetricSource]]


def default_source_factory(
    *,
    pagespeed_api_key: str | None,
    oauth: Any,
    cipher: Any,
    tls_checker: TlsChecker,
    page_fetcher: PageFetcher,
) -> SourceFactory:
    async def build(session: AsyncSession, website: Website, name: str) -> MetricSource:
        if name in ("ga4", "gsc"):
            credentials = await resolve_google_credentials(
                session, website, oauth=oauth, cipher=cipher
            )
            if name == "ga4":
                return Ga4Source(property_id=credentials.ga4_property, token=credentials.ga4_token)
            return GscSource(site_url=credentials.gsc_site, token=credentials.gsc_token)
        if name == "cwv":
            return CwvSource(api_key=pagespeed_api_key)
        if name == "probe":
            return ProbeSource(tls_checker=tls_checker, page_fetcher=page_fetcher)
        raise SourceError("unknown_source", recoverable=False)

    return build
```

- [ ] **Étape 3 : écrire les gestionnaires**

```python
# backend/app/services/jobs/handlers.py
"""Gestionnaires des types de tâches.

Chaque gestionnaire reçoit la session (aucune transaction ouverte) et le `JobRun`
réclamé, lève `SourceError` pour un échec typé et ne committe que ses étapes
intermédiaires : `execute_run` enregistre le résultat final et le planning."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.website import Website
from app.services.gtm_headless import GtmHeadlessResult
from app.services.jobs.kinds import BACKFILL_SOURCES, COLLECT_KIND_BY_SOURCE
from app.services.jobs.runner import Handler, HandlerOutcome, lock_key
from app.services.measurement.fetch import PageFetcher
from app.services.measurement.service import ReaderFactory, refresh_plan
from app.services.metrics.partitions import ensure_partitions, purge_expired
from app.services.metrics.sources.factory import SourceFactory
from app.services.metrics.store import store_observations
from app.services.metrics.types import MetricSource, SourceError, utc_now, utc_today

logger = logging.getLogger(__name__)

BREAKER_WINDOW = timedelta(minutes=30)
BREAKER_THRESHOLD = 3
JOB_RUNS_RETENTION = timedelta(days=90)


@dataclass(frozen=True, slots=True)
class JobServices:
    source_factory: SourceFactory
    page_fetcher: PageFetcher
    reader_factory: ReaderFactory
    today: Callable[[], date] = utc_today
    now: Callable[[], datetime] = utc_now


async def _active_website(session: AsyncSession, run: JobRun) -> Website:
    website = await session.get(Website, run.website_id) if run.website_id else None
    if website is None or website.archived_at is not None:
        raise SourceError("website_inactive", recoverable=False, not_applicable=True)
    return website


async def quota_breaker_open(
    session: AsyncSession, *, workspace_id: UUID, source: str, now: datetime
) -> bool:
    """Disjoncteur (spec §6 mesure 8) : trop d'échecs `quota` récents pour ce workspace
    et cette source Google ⇒ on n'appelle plus Google pendant `BREAKER_WINDOW`."""
    kind = COLLECT_KIND_BY_SOURCE[source]
    count = await session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(
            JobRun.workspace_id == workspace_id,
            JobRun.error_code == "quota",
            JobRun.finished_at >= now - BREAKER_WINDOW,
            or_(
                JobRun.kind == kind,
                and_(JobRun.kind == "backfill", JobRun.params["source"].astext == source),
            ),
        )
    )
    return (count or 0) >= BREAKER_THRESHOLD


async def _open_source(
    services: JobServices, session: AsyncSession, website: Website, name: str, run: JobRun
) -> MetricSource:
    if (
        name in BACKFILL_SOURCES
        and run.workspace_id is not None
        and await quota_breaker_open(
            session, workspace_id=run.workspace_id, source=name, now=services.now()
        )
    ):
        raise SourceError("circuit_open", recoverable=True)
    source = await services.source_factory(session, website, name)
    # Jetons résolus (et éventuel passage à `needs_reauth`) enregistrés : plus aucune
    # transaction n'est ouverte pendant la collecte réseau.
    await session.commit()
    return source


async def collect(
    services: JobServices, name: str, session: AsyncSession, run: JobRun
) -> HandlerOutcome:
    website = await _active_website(session, run)
    source = await _open_source(services, session, website, name, run)
    observations = await source.collect(website, source.spec.regular_window(services.today()))
    result = await store_observations(
        session,
        website_id=website.id,
        source=name,
        observations=observations,
        run_id=run.id,
        now=services.now(),
    )
    return HandlerOutcome(observations=result.written)


async def backfill(services: JobServices, session: AsyncSession, run: JobRun) -> HandlerOutcome:
    name = str(run.params.get("source", ""))
    if name not in BACKFILL_SOURCES:
        raise SourceError("bad_params", recoverable=False)
    website = await _active_website(session, run)
    source = await _open_source(services, session, website, name, run)
    window = source.spec.backfill_window(services.today())
    if window is None:
        raise SourceError("bad_params", recoverable=False)
    written = 0
    for chunk in window.chunks(source.spec.max_days_per_call):
        observations = await source.collect(website, chunk)
        result = await store_observations(
            session,
            website_id=website.id,
            source=name,
            observations=observations,
            run_id=run.id,
            now=services.now(),
        )
        # Progression conservée tranche par tranche : une reprise réécrit à l'identique.
        await session.commit()
        written += result.written
    return HandlerOutcome(observations=written)


async def _no_browser(url: str) -> GtmHeadlessResult:
    raise RuntimeError(f"le navigateur n'est jamais lancé par une tâche planifiée ({url})")


async def measurement_check(
    services: JobServices, session: AsyncSession, run: JobRun
) -> HandlerOutcome:
    """Vérification légère planifiée du plan de mesure (spec §9 point 8) : même service
    que le bouton « Vérifier maintenant », sans navigateur, sous le verrou du site."""
    website = await _active_website(session, run)
    reader = await services.reader_factory(session, website)
    await refresh_plan(
        session,
        website,
        fetcher=services.page_fetcher,
        reader=reader,
        verifier=_no_browser,
        run_headless=False,
        now=services.now(),
    )
    return HandlerOutcome()


async def purge_old_job_runs(
    session: AsyncSession, *, now: datetime, keep: timedelta = JOB_RUNS_RETENTION
) -> int:
    result = await session.execute(
        delete(JobRun).where(JobRun.finished_at.is_not(None), JobRun.finished_at < now - keep)
    )
    return result.rowcount or 0


async def partition_maintenance(
    services: JobServices, session: AsyncSession, run: JobRun
) -> HandlerOutcome:
    _ = run
    await lock_key(session, "partition_maintenance")
    created = await ensure_partitions(session, today=services.today())
    purged = await purge_expired(session, today=services.today())
    deleted_runs = await purge_old_job_runs(session, now=services.now())
    logger.info(
        "maintenance du stockage des mesures",
        extra={
            "event": "partition_maintenance",
            "created": created,
            "dropped": list(purged.dropped),
            "deleted_default_rows": purged.deleted_default_rows,
            "deleted_job_runs": deleted_runs,
        },
    )
    return HandlerOutcome()


def build_handlers(services: JobServices) -> dict[str, Handler]:
    handlers: dict[str, Handler] = {
        "backfill": partial(backfill, services),
        "measurement_check": partial(measurement_check, services),
        "partition_maintenance": partial(partition_maintenance, services),
    }
    for source, kind in COLLECT_KIND_BY_SOURCE.items():
        handlers[kind] = partial(collect, services, source)
    return handlers
```

- [ ] **Étape 4 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_jobs_handlers.py tests/test_jobs_runner.py tests/test_measurement_service.py -v
uv run ruff check app tests
```

Attendu : tous verts.

- [ ] **Étape 5 : commit**

```bash
git add backend/app/services/metrics/sources/factory.py backend/app/services/jobs/handlers.py backend/tests/jobs_fakes.py backend/tests/test_jobs_handlers.py
git commit -m "feat(taches): collecte par source, rattrapage de 90 jours, verification planifiee du plan de mesure, maintenance et disjoncteur

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 12 : Application worker et routes internes (`/internal/tick`, exécution, santé, headless) + outil local

**Fichiers :**
- Modifier : `backend/app/config.py` (fonction `worker_problems`)
- Modifier : `backend/app/services/jobs/handlers.py` (fonction `default_job_services`)
- Créer : `backend/app/api/internal_auth.py`, `backend/app/api/internal.py`,
  `backend/app/worker_main.py`, `backend/app/tools/jobs.py`
- Modifier : `backend/tests/jobs_fakes.py` (jetons OIDC de test)
- Test : `backend/tests/test_worker_app.py`

**Interfaces :**
- Consomme : `OidcVerifier`, `OidcError`, `OidcIdentity` ; `MetadataTokenProvider` ;
  `CloudTasksQueue` (Tâche 10) ; `tick`, `TickResult`, `InlineQueue`, `TaskQueue`
  (Tâche 9) ; `compute_jobs_health` (Tâche 8) ; `execute_run`, `JobLimits` (Tâche 7) ;
  `JobServices`, `build_handlers` (Tâche 11) ; `default_source_factory` ;
  `verify_gtm`, `GtmHeadlessVerifier`, `headless_result_to_dict`
  (`app.services.gtm_headless`) ; `get_session` ; `configure_logging`,
  `RequestContextMiddleware`, `init_sentry`.
- Produit :
  - `app.config.worker_problems(settings) -> list[str]` (vide en `local` ; sinon exige
    `TASK_QUEUE_BACKEND=cloud_tasks`, `GCP_PROJECT`, `CLOUD_TASKS_LOCATION`,
    `TASKS_INVOKER_SERVICE_ACCOUNT`, `INTERNAL_OIDC_AUDIENCE`, `WORKER_BASE_URL` en
    https, `INTERNAL_ALLOWED_INVOKERS` non vide ; messages sans aucune valeur).
  - `app.services.jobs.handlers.default_job_services(settings) -> JobServices`.
  - `app.api.internal_auth.require_internal_caller(request) -> OidcIdentity` (401 sans
    jeton ou jeton invalide, 403 si l'appelant n'est pas autorisé, 503 si non
    configuré).
  - `app.api.internal` : `router` (préfixe monté `/internal`, `include_in_schema=False`,
    OIDC sur toutes les routes), dépendances surchargeables `get_worker_settings`,
    `get_job_limits`, `get_job_services`, `get_task_queue`, `get_headless_runner` ;
    routes `POST /internal/tick` → `TickOut`, `POST /internal/tasks/run` (corps
    `RunTaskIn`, 503 + `Retry-After: 60` si la file doit réessayer) → `RunTaskOut`,
    `GET /internal/jobs/health` → `JobsHealthOut`, `POST /internal/headless/verify`
    (corps `{"url": "https://..."}`, domaine d'un site connu, un navigateur à la fois)
    → dictionnaire de `headless_result_to_dict`.
  - `app.worker_main` : `create_worker_app(settings=None, *, oidc_verifier=None) ->
    FastAPI` et `app` (instance par défaut). Aucune route `/internal` n'est ajoutée à
    `app.main`.
  - `app.tools.jobs.main(argv, *, settings=None) -> int` (`python -m app.tools.jobs
    tick`, refusé hors `local`).
  - `tests/jobs_fakes.py` : `SIGNING_KEY`, `jwks_for(key) -> dict`,
    `google_id_token(*, audience, email, key=SIGNING_KEY, **claims) -> str`.

- [ ] **Étape 1 : écrire les tests qui échouent**

Ajouter à `backend/tests/jobs_fakes.py` (imports à regrouper en tête : `import base64`,
`import time`, `import jwt`, `from cryptography.hazmat.primitives.asymmetric import rsa`) :

```python
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(number: int) -> str:
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwks_for(key, kid: str = "k1") -> dict:
    numbers = key.public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256",
                      "n": _b64(numbers.n), "e": _b64(numbers.e)}]}


def google_id_token(*, audience: str, email: str, key=SIGNING_KEY, **claims) -> str:
    now = int(time.time())
    payload = {"iss": "https://accounts.google.com", "aud": audience, "email": email,
               "email_verified": True, "sub": "sa-1", "iat": now, "exp": now + 600}
    payload.update(claims)
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "k1"})
```

```python
# backend/tests/test_worker_app.py
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.internal import get_headless_runner, get_job_services
from app.config import Settings, get_settings, worker_problems
from app.db.session import get_session
from app.main import app as api_app
from app.models.job_run import JobRun
from app.security.oidc import OidcVerifier
from app.services.gtm_headless import GtmHeadlessResult
from app.services.metrics.types import Observation, SourceError
from app.tools.jobs import main as jobs_main
from app.worker_main import create_worker_app
from tests.jobs_fakes import (
    SIGNING_KEY,
    TODAY,
    FakeSource,
    fake_services,
    google_id_token,
    jwks_for,
    make_site,
)

AUDIENCE = "https://worker.example.run.app"
CALLER = "guiili-tasks@guiili.iam.gserviceaccount.com"
INTERNAL_ROUTES = [
    ("POST", "/internal/tick", None),
    ("POST", "/internal/tasks/run", {"kind": "partition_maintenance", "window": "20260926"}),
    ("GET", "/internal/jobs/health", None),
    ("POST", "/internal/headless/verify", {"url": "https://exemple.fr"}),
]


def _sources(probe: FakeSource | None = None) -> dict[str, FakeSource]:
    unlinked = SourceError("not_linked", recoverable=False, not_applicable=True)
    return {
        "ga4": FakeSource("ga4", error=unlinked),
        "gsc": FakeSource("gsc", error=unlinked),
        "cwv": FakeSource("cwv"),
        "probe": probe or FakeSource("probe", [Observation("page_up", TODAY, 1.0)]),
    }


async def _fake_headless(url: str) -> GtmHeadlessResult:
    return GtmHeadlessResult(
        gtm_js_loaded=True, containers_initialised=("GTM-TEST",), datalayer_present=True,
        gtm_events=("gtm.js",), requests_before_consent=False, csp_console_errors=(),
        findings=(), checked_at=datetime(2026, 9, 26, tzinfo=UTC),
    )


def _auth(email: str = CALLER, **claims) -> dict[str, str]:
    return {"Authorization": f"Bearer {google_id_token(audience=AUDIENCE, email=email, **claims)}"}


@pytest_asyncio.fixture
async def worker_app(db_session: AsyncSession):
    async def fetch_jwks() -> dict:
        return jwks_for(SIGNING_KEY)

    verifier = OidcVerifier(audience=AUDIENCE, allowed_emails={CALLER}, fetch_jwks=fetch_jwks)
    application = create_worker_app(get_settings(), oidc_verifier=verifier)

    async def _session():
        yield db_session

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_job_services] = lambda: fake_services(_sources())
    application.dependency_overrides[get_headless_runner] = lambda: _fake_headless
    return application


@pytest_asyncio.fixture
async def worker(worker_app):
    async with AsyncClient(transport=ASGITransport(app=worker_app), base_url="http://w") as client:
        yield client


def test_the_public_api_exposes_no_internal_route() -> None:
    assert not any(getattr(route, "path", "").startswith("/internal") for route in api_app.routes)
    assert not any(path.startswith("/internal") for path in api_app.openapi()["paths"])


@pytest.mark.parametrize(("method", "path", "body"), INTERNAL_ROUTES)
async def test_internal_routes_require_a_google_identity(worker, method, path, body) -> None:
    anonymous = await worker.request(method, path, json=body)
    assert anonymous.status_code == 401
    wrong_audience = await worker.request(
        method, path, json=body,
        headers={"Authorization": "Bearer " + google_id_token(audience="https://x", email=CALLER)},
    )
    assert wrong_audience.status_code == 401
    stranger = await worker.request(method, path, json=body, headers=_auth("intrus@example.com"))
    assert stranger.status_code == 403


async def test_a_tick_runs_the_due_tasks_inline(
    worker, db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "worker-tick.test")
    resp = await worker.post("/internal/tick", headers=_auth())
    assert resp.status_code == 200, resp.text
    assert resp.json()["enqueued"] == 6
    runs = {
        run.kind + ":" + run.params.get("source", ""): run.status
        for run in (
            await db_session.execute(select(JobRun).where(JobRun.website_id == site.id))
        ).scalars()
    }
    assert runs == {
        "backfill:ga4": "skipped",
        "backfill:gsc": "skipped",
        "collect_cwv:": "succeeded",
        "collect_probes:": "succeeded",
        "measurement_check:": "succeeded",
    }


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"kind": "inconnu", "window": "w"}, "type de tâche inconnu"),
        ({"kind": "collect_probes", "window": "w"}, "site et workspace"),
        ({"kind": "partition_maintenance", "window": "w", "website_id": str(uuid4()),
          "workspace_id": str(uuid4())}, "tâche globale"),
        ({"kind": "partition_maintenance", "window": "w w"}, "fenêtre invalide"),
        ({"kind": "backfill", "window": "w", "website_id": str(uuid4()),
          "workspace_id": str(uuid4()), "params": {"source": "cwv"}}, "source de rattrapage"),
        ({"kind": "partition_maintenance", "window": "w", "params": {"x": "y"}}, "paramètres"),
        ({"kind": "partition_maintenance", "window": "w", "extra": 1}, "extra"),
    ],
)
async def test_the_run_payload_is_strictly_validated(worker, body: dict, fragment: str) -> None:
    resp = await worker.post("/internal/tasks/run", json=body, headers=_auth())
    assert resp.status_code == 422
    assert fragment in resp.text


async def test_a_recoverable_failure_asks_cloud_tasks_to_retry(
    worker, worker_app, db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "worker-retry.test")
    failing = FakeSource("probe", error=SourceError("unreachable", recoverable=True))
    worker_app.dependency_overrides[get_job_services] = lambda: fake_services(_sources(failing))
    body = {"kind": "collect_probes", "window": "w", "website_id": str(site.id),
            "workspace_id": str(site.workspace_id)}
    resp = await worker.post("/internal/tasks/run", json=body, headers=_auth())
    assert resp.status_code == 503 and resp.headers["Retry-After"] == "60"
    assert resp.json() == {"claim": "claimed", "status": "failed"}


async def test_a_run_for_a_mismatched_workspace_is_refused(
    worker, db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "worker-mismatch.test")
    body = {"kind": "collect_probes", "window": "w", "website_id": str(site.id),
            "workspace_id": str(uuid4())}
    resp = await worker.post("/internal/tasks/run", json=body, headers=_auth())
    assert resp.status_code == 422


async def test_a_run_for_a_deleted_site_is_acknowledged(worker) -> None:
    body = {"kind": "collect_probes", "window": "w", "website_id": str(uuid4()),
            "workspace_id": str(uuid4())}
    resp = await worker.post("/internal/tasks/run", json=body, headers=_auth())
    assert resp.status_code == 200 and resp.json() == {"claim": "gone", "status": None}


async def test_the_health_summary_is_served(worker) -> None:
    resp = await worker.get("/internal/jobs/health", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["ok"] is True and resp.json()["failing"] == []


async def test_headless_runs_only_for_a_known_https_site(
    worker, db_session: AsyncSession, make_user
) -> None:
    await make_site(db_session, make_user, "worker-headless.test")
    unknown = await worker.post(
        "/internal/headless/verify", json={"url": "https://inconnu.test"}, headers=_auth()
    )
    assert unknown.status_code == 404
    plain = await worker.post(
        "/internal/headless/verify", json={"url": "http://worker-headless.test"}, headers=_auth()
    )
    assert plain.status_code == 422
    ok = await worker.post(
        "/internal/headless/verify", json={"url": "https://worker-headless.test"}, headers=_auth()
    )
    assert ok.status_code == 200 and ok.json()["containers_initialised"] == ["GTM-TEST"]


_STAGING = {
    "environment": "staging",
    # Les arguments priment sur l'environnement du processus (conftest force
    # GOOGLE_OAUTH_MOCK=true, interdit hors local).
    "google_oauth_mock": False,
    "database_url": "postgresql+asyncpg://u:p@h/db",
    "token_enc_keys": {1: "A" * 43 + "="},
    "token_enc_active_version": 1,
    "app_secret_key": "x" * 40,
    "frontend_base_url": "https://app.example.com",
    "cors_origins": ["https://app.example.com"],
}
_WORKER = {
    "task_queue_backend": "cloud_tasks",
    "gcp_project": "guiili",
    "cloud_tasks_location": "us-central1",
    "tasks_invoker_service_account": CALLER,
    "worker_base_url": AUDIENCE,
    "internal_oidc_audience": AUDIENCE,
    "internal_allowed_invokers": [CALLER],
}


def test_worker_problems_name_missing_settings_without_values() -> None:
    assert worker_problems(get_settings()) == []  # local
    problems = worker_problems(Settings(_env_file=None, **_STAGING))
    text = " ".join(problems)
    for name in ("TASK_QUEUE_BACKEND", "GCP_PROJECT", "WORKER_BASE_URL", "INTERNAL_ALLOWED_INVOKERS"):
        assert name in text
    assert worker_problems(Settings(_env_file=None, **_STAGING, **_WORKER)) == []


def test_an_incomplete_worker_refuses_to_start_outside_local() -> None:
    with pytest.raises(RuntimeError, match="worker"):
        create_worker_app(Settings(_env_file=None, **_STAGING))


def test_the_local_tick_tool_refuses_other_environments(capsys: pytest.CaptureFixture[str]) -> None:
    assert jobs_main(["jobs"]) == 2
    assert jobs_main(["jobs", "tick"], settings=Settings(_env_file=None, **_STAGING, **_WORKER)) == 2
    assert "local" in capsys.readouterr().err
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_worker_app.py -v`
Attendu : ÉCHEC (`ImportError: cannot import name 'worker_problems' from 'app.config'`).

- [ ] **Étape 2 : exigences du worker**

À la fin de `backend/app/config.py` (après `get_settings`) :

```python
def worker_problems(settings: Settings) -> list[str]:
    """Réglages exigés par le service worker hors `local` : vérifiés au démarrage du
    worker (`app.worker_main`) et avant déploiement (`check_env --service worker`). Les
    messages ne citent que des noms de variables, jamais de valeur."""
    if settings.environment == "local":
        return []
    problems: list[str] = []
    if settings.task_queue_backend != "cloud_tasks":
        problems.append("TASK_QUEUE_BACKEND doit valoir cloud_tasks")
    for name in (
        "gcp_project",
        "cloud_tasks_location",
        "tasks_invoker_service_account",
        "internal_oidc_audience",
    ):
        if not getattr(settings, name):
            problems.append(f"{name.upper()} est obligatoire")
    if not settings.worker_base_url.startswith("https://"):
        problems.append("WORKER_BASE_URL doit commencer par https://")
    if not settings.internal_allowed_invokers:
        problems.append("INTERNAL_ALLOWED_INVOKERS doit lister au moins un compte de service")
    return problems
```

- [ ] **Étape 3 : services par défaut des tâches**

À la fin de `backend/app/services/jobs/handlers.py`, et imports à ajouter en tête :
`from app.config import Settings`, `from app.security.token_crypto import
load_token_cipher`, `from app.services.google_oauth import get_google_oauth_client`,
`from app.services.measurement.fetch import fetch_page_safe` (remplace l'import de
`PageFetcher` seul par `PageFetcher, fetch_page_safe`),
`from app.services.measurement.google_access import build_reader`,
`from app.services.metrics.sources.factory import SourceFactory, default_source_factory`
(remplace l'import de `SourceFactory` seul), `from app.services.tls_check import
check_certificate` :

```python
def default_job_services(settings: Settings) -> JobServices:
    """Services réels (réseau) : utilisés par le worker et l'outil local, jamais en test."""
    oauth = get_google_oauth_client(settings)
    cipher = load_token_cipher(settings)

    async def reader_factory(session: AsyncSession, website: Website):
        return await build_reader(session, website, oauth=oauth, cipher=cipher)

    return JobServices(
        source_factory=default_source_factory(
            pagespeed_api_key=settings.pagespeed_api_key.get_secret_value() or None,
            oauth=oauth,
            cipher=cipher,
            tls_checker=check_certificate,
            page_fetcher=fetch_page_safe,
        ),
        page_fetcher=fetch_page_safe,
        reader_factory=reader_factory,
    )
```

- [ ] **Étape 4 : authentification des appels internes**

```python
# backend/app/api/internal_auth.py
"""Dépendance des routes internes : jeton OIDC Google obligatoire (Cloud Scheduler,
Cloud Tasks ou compte de service de l'API). Le vérificateur est porté par
l'application worker (`app.state.oidc_verifier`)."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status

from app.security.oidc import OidcError, OidcIdentity, OidcVerifier

logger = logging.getLogger(__name__)


async def require_internal_caller(request: Request) -> OidcIdentity:
    verifier: OidcVerifier | None = getattr(request.app.state, "oidc_verifier", None)
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentification interne non configurée",
        )
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="jeton d'appel interne requis"
        )
    try:
        return await verifier.verify(header[7:].strip())
    except OidcError as exc:
        logger.warning("appel interne refusé", extra={"event": "internal_denied", "reason": exc.reason})
        if exc.reason == "caller_not_allowed":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="appelant interne non autorisé"
            ) from None
        if exc.reason in ("not_configured", "jwks_unavailable"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="authentification interne indisponible",
            ) from None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="jeton d'appel interne invalide"
        ) from None
```

- [ ] **Étape 5 : routes internes**

```python
# backend/app/api/internal.py
"""Routes internes du service worker. Jamais montées dans l'API publique (`app.main`),
jamais dans le schéma OpenAPI, toutes protégées par `require_internal_caller`."""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, Self
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.api.internal_auth import require_internal_caller
from app.config import Settings
from app.models.website import Website
from app.services.gcp_metadata import MetadataTokenProvider
from app.services.gtm_headless import GtmHeadlessVerifier, headless_result_to_dict, verify_gtm
from app.services.jobs.cloud_tasks import CloudTasksQueue
from app.services.jobs.handlers import JobServices, build_handlers, default_job_services
from app.services.jobs.health import compute_jobs_health
from app.services.jobs.kinds import BACKFILL_SOURCES, KINDS, RunSpec
from app.services.jobs.queue import InlineQueue, TaskQueue
from app.services.jobs.runner import JobLimits, RunResult, execute_run
from app.services.jobs.scheduler import tick
from app.services.metrics.types import utc_now

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_internal_caller)])

_WINDOW = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
# Un seul navigateur à la fois par instance du worker (file « lourde »).
_HEADLESS_SLOT = asyncio.Semaphore(1)
_METADATA_TOKENS = MetadataTokenProvider()


def get_worker_settings(request: Request) -> Settings:
    return request.app.state.settings


WorkerSettingsDep = Annotated[Settings, Depends(get_worker_settings)]


def get_job_limits(settings: WorkerSettingsDep) -> JobLimits:
    return JobLimits.from_settings(settings)


def get_job_services(settings: WorkerSettingsDep) -> JobServices:
    return default_job_services(settings)


JobLimitsDep = Annotated[JobLimits, Depends(get_job_limits)]
JobServicesDep = Annotated[JobServices, Depends(get_job_services)]


def get_task_queue(
    settings: WorkerSettingsDep,
    session: SessionDep,
    services: JobServicesDep,
    limits: JobLimitsDep,
) -> TaskQueue:
    if settings.task_queue_backend == "cloud_tasks":
        return CloudTasksQueue(
            project=settings.gcp_project,
            location=settings.cloud_tasks_location,
            queue_prefix=settings.cloud_tasks_queue_prefix,
            target_url=f"{settings.worker_base_url.rstrip('/')}/internal/tasks/run",
            invoker_email=settings.tasks_invoker_service_account,
            audience=settings.internal_oidc_audience,
            tokens=_METADATA_TOKENS,
        )
    handlers = build_handlers(services)

    async def execute(spec: RunSpec) -> RunResult:
        return await execute_run(session, spec, handlers=handlers, limits=limits)

    return InlineQueue(execute)


def get_headless_runner() -> GtmHeadlessVerifier:
    return verify_gtm


TaskQueueDep = Annotated[TaskQueue, Depends(get_task_queue)]
HeadlessRunnerDep = Annotated[GtmHeadlessVerifier, Depends(get_headless_runner)]


class TickOut(BaseModel):
    materialized: int
    enqueued: int
    capped: int
    failed_enqueue: int
    expired_queued: int


class RunTaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    website_id: UUID | None = None
    workspace_id: UUID | None = None
    window: str
    params: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        kind = KINDS.get(self.kind)
        if kind is None:
            raise ValueError("type de tâche inconnu")
        if not _WINDOW.match(self.window):
            raise ValueError("fenêtre invalide")
        has_site = self.website_id is not None and self.workspace_id is not None
        if kind.per_site and not has_site:
            raise ValueError("site et workspace obligatoires pour ce type de tâche")
        if not kind.per_site and (self.website_id is not None or self.workspace_id is not None):
            raise ValueError("tâche globale : ni site ni workspace")
        allowed = {"source"} if self.kind == "backfill" else set()
        if set(self.params) - allowed:
            raise ValueError("paramètres non autorisés pour ce type de tâche")
        if self.kind == "backfill" and self.params.get("source") not in BACKFILL_SOURCES:
            raise ValueError("source de rattrapage invalide (ga4 ou gsc)")
        return self

    def to_spec(self) -> RunSpec:
        return RunSpec(self.kind, self.website_id, self.workspace_id, self.window, dict(self.params))


class RunTaskOut(BaseModel):
    claim: str
    status: str | None


class FailingOut(BaseModel):
    website_id: UUID | None
    kind: str
    failing_since: datetime
    error_code: str | None
    client_action: bool


class JobsHealthOut(BaseModel):
    ok: bool
    checked_at: datetime
    failing: list[FailingOut]
    overdue: int
    stuck_running: int
    stuck_queued: int


class HeadlessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str

    @field_validator("url")
    @classmethod
    def _https_site(cls, value: str) -> str:
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError:
            raise ValueError("URL https d'un site attendue") from None
        if parts.scheme != "https" or not parts.hostname or parts.username or port not in (None, 443):
            raise ValueError("URL https d'un site attendue")
        return value


@router.post("/tick", response_model=TickOut)
async def tick_endpoint(
    session: SessionDep,
    settings: WorkerSettingsDep,
    queue: TaskQueueDep,
    limits: JobLimitsDep,
) -> TickOut:
    result = await tick(
        session,
        queue,
        now=utc_now(),
        batch=settings.jobs_tick_batch,
        daily_cap=settings.jobs_workspace_daily_cap,
        max_attempts=limits.max_attempts,
    )
    return TickOut(**asdict(result))


@router.post("/tasks/run", response_model=RunTaskOut)
async def run_task(
    body: RunTaskIn,
    response: Response,
    session: SessionDep,
    services: JobServicesDep,
    limits: JobLimitsDep,
) -> RunTaskOut:
    spec = body.to_spec()
    if spec.website_id is not None:
        website = await session.get(Website, spec.website_id)
        if website is None:
            # Site supprimé entre le dépôt et l'exécution : rien à faire, pas de reprise.
            await session.commit()
            return RunTaskOut(claim="gone", status=None)
        if website.workspace_id != spec.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="workspace incohérent avec le site",
            )
    result = await execute_run(session, spec, handlers=build_handlers(services), limits=limits)
    if result.retry:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        response.headers["Retry-After"] = "60"
    return RunTaskOut(claim=result.claim, status=result.status)


@router.get("/jobs/health", response_model=JobsHealthOut)
async def jobs_health(session: SessionDep) -> JobsHealthOut:
    health = await compute_jobs_health(session, now=utc_now())
    return JobsHealthOut(
        ok=health.ok,
        checked_at=health.checked_at,
        failing=[FailingOut(**asdict(item)) for item in health.failing],
        overdue=health.overdue,
        stuck_running=health.stuck_running,
        stuck_queued=health.stuck_queued,
    )


@router.post("/headless/verify")
async def headless_verify(
    body: HeadlessIn, session: SessionDep, verifier: HeadlessRunnerDep
) -> dict[str, Any]:
    host = (urlsplit(body.url).hostname or "").lower()
    known = await session.scalar(
        select(func.count()).select_from(Website).where(func.lower(Website.domain) == host)
    )
    # Fin de la transaction de lecture (commit, pas rollback : rien n'est écrit, et un
    # rollback annulerait aussi le SAVEPOINT des tests) : aucune connexion n'est tenue
    # pendant le navigateur.
    await session.commit()
    if not known:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site inconnu")
    async with _HEADLESS_SLOT:
        result = await verifier(body.url)
    return headless_result_to_dict(result)
```

- [ ] **Étape 6 : application worker**

```python
# backend/app/worker_main.py
"""Service `worker` : même code que l'API, autre point d'entrée.

Porte uniquement les routes internes (`/internal/*`, OIDC) et les sondes de santé.
Tourne dans l'image avec Chromium (`Dockerfile.worker`) ; l'API publique (`app.main`)
n'expose aucune de ces routes. Hors `local`, refuse de démarrer si la configuration du
worker est incomplète (`worker_problems`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.internal import router as internal_router
from app.config import Settings, get_settings, worker_problems
from app.db.session import engine, get_session
from app.logging_config import RequestContextMiddleware, configure_logging
from app.observability import init_sentry
from app.security.oidc import OidcVerifier


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_worker_app(
    settings: Settings | None = None, *, oidc_verifier: OidcVerifier | None = None
) -> FastAPI:
    settings = settings or get_settings()
    problems = worker_problems(settings)
    if problems:
        raise RuntimeError("Configuration du worker invalide : " + " ; ".join(problems))
    configure_logging(settings)
    init_sentry(settings)
    application = FastAPI(
        title="Guiili worker",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = settings
    if oidc_verifier is None and settings.internal_oidc_audience:
        oidc_verifier = OidcVerifier(
            audience=settings.internal_oidc_audience,
            allowed_emails=settings.internal_allowed_invokers,
        )
    application.state.oidc_verifier = oidc_verifier
    application.add_middleware(RequestContextMiddleware)
    application.include_router(internal_router, prefix="/internal")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/db", response_model=None)
    async def health_db(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, str] | JSONResponse:
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"database": "error"})
        return {"database": "ok"}

    return application


app = create_worker_app()
```

- [ ] **Étape 7 : outil local**

```python
# backend/app/tools/jobs.py
"""Un passage du planificateur en local, sans Cloud Tasks ni OIDC (développement) :

    cd backend && .venv/Scripts/python.exe -m app.tools.jobs tick

Les tâches dues sont exécutées dans le processus (`InlineQueue`) avec les vraies
sources (réseau). Refusé hors `ENVIRONMENT=local`."""

from __future__ import annotations

import asyncio
import sys

from app.config import Settings, get_settings
from app.db.session import AsyncSessionLocal
from app.services.jobs.handlers import build_handlers, default_job_services
from app.services.jobs.kinds import RunSpec
from app.services.jobs.queue import InlineQueue
from app.services.jobs.runner import JobLimits, RunResult, execute_run
from app.services.jobs.scheduler import TickResult, tick
from app.services.metrics.types import utc_now

_USAGE = "usage: python -m app.tools.jobs tick"


async def _run_tick(settings: Settings) -> TickResult:
    limits = JobLimits.from_settings(settings)
    handlers = build_handlers(default_job_services(settings))
    async with AsyncSessionLocal() as session:

        async def execute(spec: RunSpec) -> RunResult:
            return await execute_run(session, spec, handlers=handlers, limits=limits)

        return await tick(
            session,
            InlineQueue(execute),
            now=utc_now(),
            batch=settings.jobs_tick_batch,
            daily_cap=settings.jobs_workspace_daily_cap,
            max_attempts=limits.max_attempts,
        )


def main(argv: list[str], *, settings: Settings | None = None) -> int:
    if argv[1:] != ["tick"]:
        print(_USAGE, file=sys.stderr)
        return 2
    settings = settings or get_settings()
    if settings.environment != "local":
        print("outil réservé au développement local (ENVIRONMENT=local)", file=sys.stderr)
        return 2
    result = asyncio.run(_run_tick(settings))
    print(
        f"tick : {result.enqueued} tâche(s) exécutée(s), {result.materialized} planning(s) créé(s), "
        f"{result.capped} retenue(s) par la limite quotidienne, {result.failed_enqueue} échec(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Étape 8 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_worker_app.py tests/test_tenant_isolation.py -v
uv run ruff check app tests
```

Attendu : tous verts ; la suite d'isolation reste verte sans modification (aucune
route interne dans l'API publique).

- [ ] **Étape 9 : commit**

```bash
git add backend/app/config.py backend/app/services/jobs/handlers.py backend/app/api/internal_auth.py backend/app/api/internal.py backend/app/worker_main.py backend/app/tools/jobs.py backend/tests/jobs_fakes.py backend/tests/test_worker_app.py
git commit -m "feat(worker): application worker et routes internes OIDC (tick, execution, sante, headless) + outil tick local

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 13 : API de séries temporelles et de planning (+ isolation entre clients)

**Fichiers :**
- Créer : `backend/app/services/metrics/series.py`,
  `backend/app/services/jobs/schedules.py`, `backend/app/api/v1/endpoints/metrics.py`
- Modifier : `backend/app/api/v1/router.py`
- Modifier : `backend/tests/test_tenant_isolation.py` (3 cas + 1 assertion)
- Test : `backend/tests/test_metrics_series.py`, `backend/tests/test_metrics_endpoints.py`

**Interfaces :**
- Consomme : `MetricPoint`, `MetricRollup`, `Schedule` (Tâche 1) ; `METRICS_BY_KEY`,
  `MetricDef`, `aggregate`, `periods_between`, `period_end`, `siblings_needed`,
  `DayRange`, `utc_today`, `utc_now` (Tâche 2) ; `KINDS`, `SCHEDULABLE_KINDS`,
  `FREQUENCY_INTERVALS`, `FREQUENCY_LABELS`, `TaskKind`, `effective_interval` (Tâche 7) ;
  `error_message` (Tâche 8) ; `owned_website`, `require_owner`
  (`app.services.workspaces`) ; `limit_by_user` ; `CurrentUserDep`, `SessionDep`.
- Produit (`app.services.metrics.series`) : `Granularity`, `Compare`,
  `MAX_RANGE_DAYS = 800`, `DEFAULT_RANGE_DAYS = 28`, `SeriesPoint(period_start,
  period_end, value: float | None, days_covered, days_expected)`, `Series(start, end,
  points, total)`, `Freshness(last_collected_at, data_until)` (NamedTuple),
  `shift_year(day)`,
  `comparison_range(start, end, compare) -> tuple[date, date] | None`,
  `build_series(session, *, website_id, defn, start, end, granularity) -> Series`
  (semaines/mois entiers lus dans `metric_rollups`, bords et jours dans
  `metric_points`), `freshness(session, website_id, source) -> Freshness`.
- Produit (`app.services.jobs.schedules`) : `ScheduleView` (champs de `ScheduleOut`
  ci-dessous), `schedule_views(session, website_id) -> list[ScheduleView]` (les 5 types
  planifiables, valeurs par défaut pour ceux pas encore matérialisés),
  `upsert_schedule(session, *, website_id, kind: TaskKind, frequency, enabled, now) ->
  Schedule` (ne committe pas).
- Produit (HTTP, préfixe `/api/v1`) :
  - `GET /websites/{website_id}/metrics/series?metric=ga4.sessions&start=AAAA-MM-JJ&
    end=AAAA-MM-JJ&granularity=day|week|month&compare=none|previous_period|previous_year`
    → `SeriesOut {metric, label, source, unit, direction, granularity, current:
    {start, end, total, points[{period_start, period_end, value|null, days_covered,
    days_expected}]}, comparison|null, last_collected_at, data_until}` ; 422 en français
    pour tout paramètre invalide (après le contrôle d'appartenance) ; limite
    `metrics_read` 120/min.
  - `GET /websites/{website_id}/schedules` → `SchedulesOut {website_id, can_edit,
    frequency_labels, schedules[{kind, label, frequency, enabled, allowed_frequencies,
    floor_hours, next_due_at, last_run_at, last_status, last_success_at, failing_since,
    last_error_code, last_error, backfill_done_at}]}` ; limite `schedules_read` 120/min.
  - `PUT /websites/{website_id}/schedules` corps `{kind, frequency, enabled}`
    (propriétaire seulement, 403 sinon ; 422 français si type inconnu, fréquence
    inconnue ou sous le plancher) → `SchedulesOut` ; limite `schedules_write` 30/min.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_metrics_series.py
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_rollup import MetricRollup
from app.services.metrics.registry import METRICS_BY_KEY
from app.services.metrics.series import build_series, comparison_range, freshness, shift_year
from app.services.metrics.store import store_observations
from app.services.metrics.types import Observation
from tests.jobs_fakes import make_site

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
SESSIONS = METRICS_BY_KEY["ga4.sessions"]


async def _store(session: AsyncSession, site, source: str, observations) -> None:
    await store_observations(
        session, website_id=site.id, source=source, observations=observations, run_id=None, now=NOW
    )


def test_comparison_ranges() -> None:
    assert comparison_range(date(2026, 9, 1), date(2026, 9, 7), "none") is None
    assert comparison_range(date(2026, 9, 8), date(2026, 9, 14), "previous_period") == (
        date(2026, 9, 1), date(2026, 9, 7),
    )
    assert comparison_range(date(2026, 9, 1), date(2026, 9, 7), "previous_year") == (
        date(2025, 9, 1), date(2025, 9, 7),
    )
    assert shift_year(date(2028, 2, 29)) == date(2027, 2, 28)


async def test_daily_series_shows_gaps_as_null(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "series-day.test")
    await _store(db_session, site, "ga4", [
        Observation("sessions", date(2026, 9, 21), 5.0),
        Observation("sessions", date(2026, 9, 23), 7.0),
    ])
    series = await build_series(
        db_session, website_id=site.id, defn=SESSIONS,
        start=date(2026, 9, 21), end=date(2026, 9, 23), granularity="day",
    )
    assert [(p.period_start, p.value, p.days_covered) for p in series.points] == [
        (date(2026, 9, 21), 5.0, 1),
        (date(2026, 9, 22), None, 0),
        (date(2026, 9, 23), 7.0, 1),
    ]
    assert series.total == 12.0


async def test_full_weeks_come_from_the_rollups_and_edges_from_the_points(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "series-week.test")
    await _store(db_session, site, "ga4", [
        Observation("sessions", date(2026, 9, 20), 1.0),  # dimanche : semaine du 14 (bord)
        Observation("sessions", date(2026, 9, 21), 2.0),  # semaine du 21 (entière)
        Observation("sessions", date(2026, 9, 22), 3.0),
    ])
    # Preuve de lecture des cumuls : on remplace le cumul de la semaine entière.
    rollup = await db_session.get(
        MetricRollup, (site.id, "ga4", "sessions", "", "week", date(2026, 9, 21))
    )
    rollup.value = 999.0
    await db_session.flush()
    series = await build_series(
        db_session, website_id=site.id, defn=SESSIONS,
        start=date(2026, 9, 20), end=date(2026, 9, 27), granularity="week",
    )
    edge, full = series.points
    assert (edge.period_start, edge.value, edge.days_covered, edge.days_expected) == (
        date(2026, 9, 14), 1.0, 1, 1,
    )
    assert (full.period_start, full.value, full.days_covered, full.days_expected) == (
        date(2026, 9, 21), 999.0, 2, 7,
    )


async def test_ratio_metrics_are_recomputed_from_their_parts(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "series-ctr.test")
    await _store(db_session, site, "gsc", [
        Observation("clicks", date(2026, 9, 21), 10.0),
        Observation("impressions", date(2026, 9, 21), 100.0),
        Observation("ctr", date(2026, 9, 21), 0.1),
        Observation("clicks", date(2026, 9, 22), 30.0),
        Observation("impressions", date(2026, 9, 22), 100.0),
        Observation("ctr", date(2026, 9, 22), 0.3),
    ])
    series = await build_series(
        db_session, website_id=site.id, defn=METRICS_BY_KEY["gsc.ctr"],
        start=date(2026, 9, 21), end=date(2026, 9, 22), granularity="month",
    )
    assert series.total == pytest.approx(0.2)
    assert series.points[0].value == pytest.approx(0.2)


async def test_freshness_reports_the_last_collection(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "series-fresh.test")
    assert await freshness(db_session, site.id, "ga4") == (None, None)
    await _store(db_session, site, "ga4", [Observation("sessions", date(2026, 9, 25), 1.0)])
    fresh = await freshness(db_session, site.id, "ga4")
    assert fresh.last_collected_at == NOW and fresh.data_until == date(2026, 9, 25)
```

```python
# backend/tests/test_metrics_endpoints.py
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import MetricPoint
from app.models.schedule import Schedule
from app.models.user import User
from app.models.website import Website
from app.models.workspace_member import WorkspaceMember
from app.services.metrics.store import store_observations
from app.services.metrics.types import Observation, utc_now, utc_today
from tests.conftest import owner_workspace_id


async def _own_site(db_session: AsyncSession, user: User, domain: str) -> Website:
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


async def _member_site(db_session: AsyncSession, make_user, user: User, domain: str) -> Website:
    owner = await make_user(sub=f"owner-{domain}")
    site = await _own_site(db_session, owner, domain)
    db_session.add(WorkspaceMember(workspace_id=site.workspace_id, user_id=user.id, role="member"))
    await db_session.flush()
    return site


async def test_series_returns_the_stored_values(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-series.test")
    yesterday = utc_today() - timedelta(days=1)
    await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[Observation("sessions", yesterday, 42.0)], run_id=None, now=utc_now(),
    )
    resp = await client.get(
        f"/api/v1/websites/{site.id}/metrics/series",
        params={"metric": "ga4.sessions", "compare": "previous_period"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["metric"] == "ga4.sessions" and body["unit"] == "count"
    assert body["current"]["end"] == yesterday.isoformat()
    assert len(body["current"]["points"]) == 28
    assert body["current"]["points"][-1]["value"] == 42.0
    assert body["current"]["points"][0]["value"] is None
    assert body["current"]["total"] == 42.0
    assert body["comparison"]["total"] is None
    assert body["data_until"] == yesterday.isoformat()


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({}, "metric"),
        ({"metric": "ga4.inconnue"}, "métrique inconnue"),
        ({"metric": "ga4.sessions", "granularity": "year"}, "granularité"),
        ({"metric": "ga4.sessions", "compare": "hier"}, "comparaison"),
        ({"metric": "ga4.sessions", "start": "26/09/2026"}, "date invalide"),
        ({"metric": "ga4.sessions", "start": "2026-09-20", "end": "2026-09-01"}, "début"),
        ({"metric": "ga4.sessions", "start": "2020-01-01", "end": "2026-01-01"}, "trop longue"),
    ],
)
async def test_series_parameters_are_validated_in_french(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, params: dict, fragment: str
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-series-422.test")
    resp = await client.get(f"/api/v1/websites/{site.id}/metrics/series", params=params)
    assert resp.status_code == 422
    assert fragment in resp.json()["detail"]


async def test_schedules_list_the_five_kinds_with_defaults(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-sched.test")
    resp = await client.get(f"/api/v1/websites/{site.id}/schedules")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_edit"] is True
    kinds = {s["kind"]: s for s in body["schedules"]}
    assert list(kinds) == [
        "collect_ga4", "collect_gsc", "collect_cwv", "collect_probes", "measurement_check",
    ]
    assert kinds["collect_ga4"]["frequency"] == "daily"
    assert kinds["collect_ga4"]["allowed_frequencies"] == [
        "three_daily", "daily", "every_3_days", "weekly",
    ]
    assert kinds["collect_probes"]["floor_hours"] == 1
    assert kinds["collect_probes"]["next_due_at"] is None
    assert body["frequency_labels"]["hourly"] == "Toutes les heures"


async def test_the_owner_changes_a_schedule(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-sched-put.test")
    resp = await client.put(
        f"/api/v1/websites/{site.id}/schedules",
        json={"kind": "collect_probes", "frequency": "hourly", "enabled": False},
    )
    assert resp.status_code == 200, resp.text
    probes = next(s for s in resp.json()["schedules"] if s["kind"] == "collect_probes")
    assert (probes["frequency"], probes["enabled"]) == ("hourly", False)
    row = await db_session.scalar(select(Schedule).where(Schedule.website_id == site.id))
    assert row.kind == "collect_probes" and row.enabled is False


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"kind": "collect_ga4", "frequency": "hourly"}, "fréquence trop élevée"),
        ({"kind": "backfill", "frequency": "daily"}, "type de suivi inconnu"),
        ({"kind": "collect_ga4", "frequency": "monthly"}, "fréquence inconnue"),
        ({"kind": "collect_ga4", "frequency": "daily", "extra": True}, "extra"),
    ],
)
async def test_invalid_schedule_bodies_are_refused(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, body: dict, fragment: str
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-sched-422.test")
    resp = await client.put(f"/api/v1/websites/{site.id}/schedules", json=body)
    assert resp.status_code == 422
    assert fragment in resp.text


async def test_a_member_reads_but_cannot_change_schedules(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user
) -> None:
    client, user = authed_client
    site = await _member_site(db_session, make_user, user, "api-sched-member.test")
    read = await client.get(f"/api/v1/websites/{site.id}/schedules")
    assert read.status_code == 200 and read.json()["can_edit"] is False
    write = await client.put(
        f"/api/v1/websites/{site.id}/schedules",
        json={"kind": "collect_probes", "frequency": "weekly", "enabled": True},
    )
    assert write.status_code == 403
    assert await db_session.scalar(select(func.count()).select_from(Schedule)) == 0


async def test_purging_a_site_deletes_its_series_and_schedules(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-purge.test")
    await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[Observation("sessions", date(2026, 9, 20), 1.0)], run_id=None,
        now=utc_now(),
    )
    await client.put(
        f"/api/v1/websites/{site.id}/schedules",
        json={"kind": "collect_ga4", "frequency": "daily", "enabled": True},
    )
    resp = await client.delete(f"/api/v1/websites/{site.id}", params={"purge": "true"})
    assert resp.status_code == 204
    db_session.expunge_all()
    assert await db_session.scalar(select(func.count()).select_from(MetricPoint)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Schedule)) == 0
```

Dans `backend/tests/test_tenant_isolation.py` :

1. ajouter `from app.models.schedule import Schedule` aux imports ;
2. ajouter à `CASES` (après la ligne `("POST", "/websites/{website_id}/measurement-plan/google-autolink"): None,`) :

```python
    ("GET", "/websites/{website_id}/metrics/series"): None,
    ("GET", "/websites/{website_id}/schedules"): None,
    ("PUT", "/websites/{website_id}/schedules"): {
        "kind": "collect_ga4",
        "frequency": "weekly",
        "enabled": False,
    },
```

3. à la fin de `test_a_stranger_cannot_reach_or_alter_another_workspace`, ajouter :

```python
    assert await db_session.scalar(select(func.count()).select_from(Schedule)) == 0
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_metrics_series.py tests/test_metrics_endpoints.py tests/test_tenant_isolation.py -v`
Attendu : ÉCHEC (`ModuleNotFoundError: No module named 'app.services.metrics.series'`).

- [ ] **Étape 2 : écrire la lecture des séries**

```python
# backend/app/services/metrics/series.py
"""Lecture unique des séries temporelles (tableau de bord, rapports, conseiller).

Semaines et mois entièrement compris dans la période : lus dans `metric_rollups`
(pré-calculés). Périodes coupées par les bornes et granularité journalière : calculées
depuis `metric_points` avec la même agrégation que les cumuls. Une période sans aucune
donnée vaut `None` (jamais zéro) ; `days_covered` / `days_expected` disent si elle est
complète."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, NamedTuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import MetricPoint
from app.models.metric_rollup import MetricRollup
from app.services.metrics.aggregate import aggregate, period_end, periods_between, siblings_needed
from app.services.metrics.registry import MetricDef
from app.services.metrics.types import DayRange

Granularity = Literal["day", "week", "month"]
Compare = Literal["none", "previous_period", "previous_year"]
MAX_RANGE_DAYS = 800
DEFAULT_RANGE_DAYS = 28


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    period_start: date
    period_end: date
    value: float | None
    days_covered: int
    days_expected: int


@dataclass(frozen=True, slots=True)
class Series:
    start: date
    end: date
    points: tuple[SeriesPoint, ...]
    total: float | None


class Freshness(NamedTuple):
    last_collected_at: datetime | None
    data_until: date | None


def shift_year(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29 février
        return day.replace(year=day.year - 1, day=28)


def comparison_range(start: date, end: date, compare: str) -> tuple[date, date] | None:
    if compare == "previous_period":
        length = (end - start).days + 1
        return start - timedelta(days=length), start - timedelta(days=1)
    if compare == "previous_year":
        return shift_year(start), shift_year(end)
    return None


async def _load_daily(
    session: AsyncSession, website_id: UUID, defn: MetricDef, start: date, end: date
) -> dict[str, dict[date, float]]:
    names = (defn.name, *siblings_needed(defn))
    rows = await session.execute(
        select(MetricPoint.metric, MetricPoint.day, MetricPoint.value).where(
            MetricPoint.website_id == website_id,
            MetricPoint.source == defn.source,
            MetricPoint.metric.in_(names),
            MetricPoint.dim_key == "",
            MetricPoint.day >= start,
            MetricPoint.day <= end,
        )
    )
    daily: dict[str, dict[date, float]] = {name: {} for name in names}
    for metric, day, value in rows.all():
        daily[metric][day] = value
    return daily


async def _load_rollups(
    session: AsyncSession, website_id: UUID, defn: MetricDef, grain: str, starts: list[date]
) -> dict[date, tuple[float, int]]:
    if not starts:
        return {}
    rows = await session.execute(
        select(MetricRollup.period_start, MetricRollup.value, MetricRollup.days_covered).where(
            MetricRollup.website_id == website_id,
            MetricRollup.source == defn.source,
            MetricRollup.metric == defn.name,
            MetricRollup.dim_key == "",
            MetricRollup.grain == grain,
            MetricRollup.period_start.in_(starts),
        )
    )
    return {start: (value, covered) for start, value, covered in rows.all()}


def _within(series: dict[date, float], low: date, high: date) -> dict[date, float]:
    return {day: value for day, value in series.items() if low <= day <= high}


async def build_series(
    session: AsyncSession,
    *,
    website_id: UUID,
    defn: MetricDef,
    start: date,
    end: date,
    granularity: str,
) -> Series:
    daily = await _load_daily(session, website_id, defn, start, end)
    values = daily[defn.name]
    siblings = {name: daily[name] for name in siblings_needed(defn)}
    total = aggregate(defn, values, siblings)
    points: list[SeriesPoint] = []
    if granularity == "day":
        for day in DayRange(start, end).days():
            points.append(SeriesPoint(day, day, values.get(day), 1 if day in values else 0, 1))
        return Series(start, end, tuple(points), total)

    grain = "week" if granularity == "week" else "month"
    starts = periods_between(start, end, grain)
    full = [s for s in starts if s >= start and period_end(s, grain) <= end]
    stored = await _load_rollups(session, website_id, defn, grain, full)
    for period in starts:
        low, high = max(period, start), min(period_end(period, grain), end)
        expected = (high - low).days + 1
        if period in stored:
            value, covered = stored[period]
        else:
            window = _within(values, low, high)
            window_siblings = {name: _within(series, low, high) for name, series in siblings.items()}
            value = aggregate(defn, window, window_siblings)
            covered = len(window)
        points.append(SeriesPoint(period, period_end(period, grain), value, covered, expected))
    return Series(start, end, tuple(points), total)


async def freshness(session: AsyncSession, website_id: UUID, source: str) -> Freshness:
    row = (
        await session.execute(
            select(func.max(MetricPoint.collected_at), func.max(MetricPoint.day)).where(
                MetricPoint.website_id == website_id, MetricPoint.source == source
            )
        )
    ).one()
    return Freshness(row[0], row[1])
```

- [ ] **Étape 3 : écrire la vue et l'écriture des plannings**

```python
# backend/app/services/jobs/schedules.py
"""Plannings d'un site pour l'interface « Suivi automatique »."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schedule import Schedule
from app.services.jobs.kinds import SCHEDULABLE_KINDS, TaskKind, effective_interval
from app.services.jobs.messages import error_message


@dataclass(frozen=True, slots=True)
class ScheduleView:
    kind: str
    label: str
    frequency: str
    enabled: bool
    allowed_frequencies: tuple[str, ...]
    floor_hours: int
    next_due_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_success_at: datetime | None
    failing_since: datetime | None
    last_error_code: str | None
    last_error: str | None
    backfill_done_at: datetime | None


async def schedule_views(session: AsyncSession, website_id: UUID) -> list[ScheduleView]:
    rows = {
        row.kind: row
        for row in (
            await session.execute(select(Schedule).where(Schedule.website_id == website_id))
        ).scalars()
    }
    views: list[ScheduleView] = []
    for kind in SCHEDULABLE_KINDS:
        row = rows.get(kind.name)
        views.append(
            ScheduleView(
                kind=kind.name,
                label=kind.label,
                frequency=row.frequency if row else str(kind.default_frequency),
                enabled=row.enabled if row else True,
                allowed_frequencies=kind.allowed_frequencies(),
                floor_hours=int(kind.floor.total_seconds() // 3600),
                next_due_at=row.next_due_at if row else None,
                last_run_at=row.last_run_at if row else None,
                last_status=row.last_status if row else None,
                last_success_at=row.last_success_at if row else None,
                failing_since=row.failing_since if row else None,
                last_error_code=row.last_error_code if row else None,
                last_error=error_message(row.last_error_code) if row else None,
                backfill_done_at=row.backfill_done_at if row else None,
            )
        )
    return views


async def upsert_schedule(
    session: AsyncSession,
    *,
    website_id: UUID,
    kind: TaskKind,
    frequency: str,
    enabled: bool,
    now: datetime,
) -> Schedule:
    await session.execute(
        pg_insert(Schedule)
        .values(
            id=uuid4(),
            website_id=website_id,
            kind=kind.name,
            frequency=frequency,
            enabled=enabled,
            next_due_at=now,
        )
        .on_conflict_do_update(
            index_elements=["website_id", "kind"],
            set_={"frequency": frequency, "enabled": enabled, "updated_at": now},
        )
    )
    schedule = (
        await session.execute(
            select(Schedule)
            .where(Schedule.website_id == website_id, Schedule.kind == kind.name)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if schedule.last_run_at is not None:
        # Une fréquence plus serrée rapproche l'échéance (jamais dans le passé).
        candidate = max(schedule.last_run_at + effective_interval(kind, frequency), now)
        schedule.next_due_at = min(schedule.next_due_at, candidate)
    return schedule
```

- [ ] **Étape 4 : écrire les routes**

```python
# backend/app/api/v1/endpoints/metrics.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select

from app.api.deps import CurrentUserDep, SessionDep
from app.api.rate_limit import limit_by_user
from app.models.website import Website
from app.models.workspace_member import WorkspaceMember
from app.services.jobs.kinds import FREQUENCY_INTERVALS, FREQUENCY_LABELS, KINDS
from app.services.jobs.schedules import schedule_views, upsert_schedule
from app.services.metrics.registry import METRICS_BY_KEY, MetricDef
from app.services.metrics.series import (
    DEFAULT_RANGE_DAYS,
    MAX_RANGE_DAYS,
    Series,
    build_series,
    comparison_range,
    freshness,
)
from app.services.metrics.types import utc_now, utc_today
from app.services.workspaces import owned_website, require_owner

router = APIRouter(tags=["metrics"])

_GRANULARITIES = ("day", "week", "month")
_COMPARES = ("none", "previous_period", "previous_year")


# ---- séries temporelles -------------------------------------------------------
class SeriesPointOut(BaseModel):
    period_start: date
    period_end: date
    value: float | None
    days_covered: int
    days_expected: int


class SeriesBlockOut(BaseModel):
    start: date
    end: date
    total: float | None
    points: list[SeriesPointOut]


class SeriesOut(BaseModel):
    metric: str
    label: str
    source: str
    unit: str
    direction: str
    granularity: str
    current: SeriesBlockOut
    comparison: SeriesBlockOut | None
    last_collected_at: datetime | None
    data_until: date | None


@dataclass(frozen=True, slots=True)
class SeriesQuery:
    defn: MetricDef
    start: date
    end: date
    granularity: str
    compare: str


def _invalid(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def parse_series_query(
    *,
    metric: str | None,
    start: str | None,
    end: str | None,
    granularity: str,
    compare: str,
    today: date,
) -> SeriesQuery:
    if not metric:
        raise _invalid("paramètre « metric » requis (par exemple ga4.sessions)")
    defn = METRICS_BY_KEY.get(metric)
    if defn is None:
        raise _invalid(f"métrique inconnue : {metric}")
    if granularity not in _GRANULARITIES:
        raise _invalid("granularité invalide (day, week ou month)")
    if compare not in _COMPARES:
        raise _invalid("comparaison invalide (none, previous_period ou previous_year)")
    try:
        end_day = date.fromisoformat(end) if end else today - timedelta(days=1)
        start_day = (
            date.fromisoformat(start) if start else end_day - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        )
    except ValueError:
        raise _invalid("date invalide (format AAAA-MM-JJ)") from None
    if start_day > end_day:
        raise _invalid("la date de début doit précéder la date de fin")
    if (end_day - start_day).days + 1 > MAX_RANGE_DAYS:
        raise _invalid(f"période trop longue (au plus {MAX_RANGE_DAYS} jours)")
    return SeriesQuery(defn, start_day, end_day, granularity, compare)


def _block(series: Series) -> SeriesBlockOut:
    return SeriesBlockOut(
        start=series.start,
        end=series.end,
        total=series.total,
        points=[
            SeriesPointOut(
                period_start=p.period_start,
                period_end=p.period_end,
                value=p.value,
                days_covered=p.days_covered,
                days_expected=p.days_expected,
            )
            for p in series.points
        ],
    )


@router.get(
    "/websites/{website_id}/metrics/series",
    response_model=SeriesOut,
    dependencies=[limit_by_user("metrics_read", limit=120, window=60)],
)
async def get_metric_series(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    metric: Annotated[str | None, Query()] = None,
    start: Annotated[str | None, Query()] = None,
    end: Annotated[str | None, Query()] = None,
    granularity: Annotated[str, Query()] = "day",
    compare: Annotated[str, Query()] = "none",
) -> SeriesOut:
    # Appartenance d'abord : un étranger reçoit 404, jamais une erreur de paramètre.
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    query = parse_series_query(
        metric=metric, start=start, end=end, granularity=granularity, compare=compare,
        today=utc_today(),
    )
    current = await build_series(
        session, website_id=site.id, defn=query.defn, start=query.start, end=query.end,
        granularity=query.granularity,
    )
    comparison = None
    other = comparison_range(query.start, query.end, query.compare)
    if other is not None:
        comparison = _block(
            await build_series(
                session, website_id=site.id, defn=query.defn, start=other[0], end=other[1],
                granularity=query.granularity,
            )
        )
    fresh = await freshness(session, site.id, query.defn.source)
    return SeriesOut(
        metric=query.defn.key,
        label=query.defn.label,
        source=query.defn.source,
        unit=query.defn.unit,
        direction=query.defn.direction,
        granularity=query.granularity,
        current=_block(current),
        comparison=comparison,
        last_collected_at=fresh.last_collected_at,
        data_until=fresh.data_until,
    )


# ---- planning (« Suivi automatique ») ------------------------------------------
class ScheduleOut(BaseModel):
    kind: str
    label: str
    frequency: str
    enabled: bool
    allowed_frequencies: list[str]
    floor_hours: int
    next_due_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_success_at: datetime | None
    failing_since: datetime | None
    last_error_code: str | None
    # Texte français décidé par le code, prêt à afficher.
    last_error: str | None
    backfill_done_at: datetime | None


class SchedulesOut(BaseModel):
    website_id: UUID
    can_edit: bool
    frequency_labels: dict[str, str]
    schedules: list[ScheduleOut]


class SchedulePut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    frequency: str
    enabled: bool = True

    @model_validator(mode="after")
    def _valid(self) -> Self:
        kind = KINDS.get(self.kind)
        if kind is None or not kind.schedulable:
            raise ValueError("type de suivi inconnu")
        if self.frequency not in FREQUENCY_INTERVALS:
            raise ValueError("fréquence inconnue")
        if self.frequency not in kind.allowed_frequencies():
            hours = int(kind.floor.total_seconds() // 3600)
            raise ValueError(
                f"fréquence trop élevée pour « {kind.label} » : au plus une fois toutes les {hours} h"
            )
        return self


async def _schedules_out(session, site: Website, user_id: UUID) -> SchedulesOut:
    role = await session.scalar(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == site.workspace_id, WorkspaceMember.user_id == user_id
        )
    )
    views = await schedule_views(session, site.id)
    return SchedulesOut(
        website_id=site.id,
        can_edit=role == "owner",
        frequency_labels=dict(FREQUENCY_LABELS),
        schedules=[
            ScheduleOut(
                kind=view.kind,
                label=view.label,
                frequency=view.frequency,
                enabled=view.enabled,
                allowed_frequencies=list(view.allowed_frequencies),
                floor_hours=view.floor_hours,
                next_due_at=view.next_due_at,
                last_run_at=view.last_run_at,
                last_status=view.last_status,
                last_success_at=view.last_success_at,
                failing_since=view.failing_since,
                last_error_code=view.last_error_code,
                last_error=view.last_error,
                backfill_done_at=view.backfill_done_at,
            )
            for view in views
        ],
    )


@router.get(
    "/websites/{website_id}/schedules",
    response_model=SchedulesOut,
    dependencies=[limit_by_user("schedules_read", limit=120, window=60)],
)
async def get_schedules(website_id: UUID, user: CurrentUserDep, session: SessionDep) -> SchedulesOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    return await _schedules_out(session, site, user.id)


@router.put(
    "/websites/{website_id}/schedules",
    response_model=SchedulesOut,
    dependencies=[limit_by_user("schedules_write", limit=30, window=60)],
)
async def put_schedule(
    website_id: UUID, body: SchedulePut, user: CurrentUserDep, session: SessionDep
) -> SchedulesOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    await require_owner(session, workspace_id=site.workspace_id, user_id=user.id)
    await upsert_schedule(
        session,
        website_id=site.id,
        kind=KINDS[body.kind],
        frequency=body.frequency,
        enabled=body.enabled,
        now=utc_now(),
    )
    await session.commit()
    return await _schedules_out(session, site, user.id)
```

Dans `backend/app/api/v1/router.py`, ajouter `metrics` à la liste importée depuis
`app.api.v1.endpoints` (ordre alphabétique, après `measurement`) et, après
`api_router.include_router(measurement.router)` :

```python
api_router.include_router(metrics.router)
```

- [ ] **Étape 5 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_metrics_series.py tests/test_metrics_endpoints.py tests/test_tenant_isolation.py tests/test_rate_limit_endpoints.py -v
uv run ruff check app tests
```

Attendu : tous verts ; `test_every_tenant_route_has_an_isolation_case` voit les trois
nouvelles routes dans `CASES` ; l'étranger reçoit 404 sur chacune, l'anonyme 401.

- [ ] **Étape 6 : commit**

```bash
git add backend/app/services/metrics/series.py backend/app/services/jobs/schedules.py backend/app/api/v1/endpoints/metrics.py backend/app/api/v1/router.py backend/tests/test_metrics_series.py backend/tests/test_metrics_endpoints.py backend/tests/test_tenant_isolation.py
git commit -m "feat(api): series temporelles unifiees (cumuls, comparaison, granularite) et planning du suivi automatique

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 14 : Délégation de la vérification headless de l'API au worker

**Fichiers :**
- Modifier : `backend/app/services/gtm_headless.py` (ajout de
  `headless_result_from_dict`, rien d'autre ne change)
- Créer : `backend/app/services/worker_client.py`
- Modifier : `backend/app/api/deps.py` (`get_gtm_headless_verifier`)
- Test : `backend/tests/test_headless_delegation.py`

**Interfaces :**
- Consomme : `GtmHeadlessResult`, `GtmHeadlessVerifier`, `headless_result_to_dict`,
  `HEADLESS_FAILED`, `verify_gtm` (`app.services.gtm_headless`) ; `GtmFinding`
  (`app.services.gtm_check`) ; `MetadataTokenProvider`, `MetadataError`,
  `IdentityTokenProvider` (Tâche 10) ; `create_worker_app`, `get_headless_runner`
  (Tâche 12) ; `Settings.worker_base_url`, `Settings.internal_oidc_audience`.
- Produit :
  - `headless_result_from_dict(data: Any) -> GtmHeadlessResult` (inverse exact de
    `headless_result_to_dict` ; `ValueError` si la forme est inattendue).
  - `app.services.worker_client.RemoteHeadlessVerifier(*, base_url: str, audience: str,
    tokens: IdentityTokenProvider, client: httpx.AsyncClient | None = None,
    timeout: float = 150.0)` — appelable `async (url: str) -> GtmHeadlessResult`, ne
    lève jamais (échec ⇒ `error="headless_failed"`, comme `verify_gtm`).
  - `get_gtm_headless_verifier(settings: SettingsDep) -> GtmHeadlessVerifier` :
    `RemoteHeadlessVerifier` si `WORKER_BASE_URL` est réglée, sinon `verify_gtm`
    (développement local inchangé). Les surcharges de test existantes
    (`app.dependency_overrides[get_gtm_headless_verifier] = lambda: ...`) restent
    valables.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_headless_delegation.py
import json
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_gtm_headless_verifier
from app.api.internal import get_headless_runner
from app.config import get_settings
from app.db.session import get_session
from app.security.oidc import OidcVerifier
from app.services.gcp_metadata import MetadataError
from app.services.gtm_check import GtmFinding
from app.services.gtm_headless import (
    HEADLESS_FAILED,
    GtmHeadlessResult,
    headless_result_from_dict,
    headless_result_to_dict,
    verify_gtm,
)
from app.services.worker_client import RemoteHeadlessVerifier
from app.worker_main import create_worker_app
from tests.jobs_fakes import SIGNING_KEY, google_id_token, jwks_for, make_site

WORKER = "https://worker.example.run.app"
API_ACCOUNT = "backend-guiili@guiili.iam.gserviceaccount.com"
RESULT = GtmHeadlessResult(
    gtm_js_loaded=True,
    containers_initialised=("GTM-ABC1234",),
    datalayer_present=True,
    gtm_events=("gtm.js", "gtm.dom"),
    requests_before_consent=True,
    csp_console_errors=("Refused to load 'https://www.googletagmanager.com/gtm.js'",),
    findings=(GtmFinding(code="headless_csp_blocks_gtm", severity="high", title="t", detail="d"),),
    checked_at=datetime(2026, 9, 26, 6, 0, tzinfo=UTC),
    ga4_measurement_ids=("G-ABCDEF12",),
    ads_requests=2,
    consent_default_seen=True,
)


class _Tokens:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.audiences: list[str] = []

    async def identity_token(self, audience: str) -> str:
        self.audiences.append(audience)
        if self.fail:
            raise MetadataError("hors Cloud Run")
        return google_id_token(audience=audience, email=API_ACCOUNT)


def test_the_result_survives_the_round_trip() -> None:
    assert headless_result_from_dict(headless_result_to_dict(RESULT)) == RESULT


@pytest.mark.parametrize(
    "payload",
    [[], {}, {**headless_result_to_dict(RESULT), "gtm_js_loaded": "oui"},
     {**headless_result_to_dict(RESULT), "findings": ["x"]}],
)
def test_an_unexpected_shape_is_rejected(payload) -> None:
    with pytest.raises(ValueError):
        headless_result_from_dict(payload)


async def test_the_remote_verifier_calls_the_worker_with_an_identity_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=headless_result_to_dict(RESULT))

    tokens = _Tokens()
    verifier = RemoteHeadlessVerifier(
        base_url=WORKER, audience=WORKER, tokens=tokens,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await verifier("https://exemple.fr") == RESULT
    assert str(seen[0].url) == f"{WORKER}/internal/headless/verify"
    assert json.loads(seen[0].content) == {"url": "https://exemple.fr"}
    assert seen[0].headers["Authorization"].startswith("Bearer ")
    assert tokens.audiences == [WORKER]


@pytest.mark.parametrize("status", [401, 404, 503])
async def test_a_worker_error_becomes_a_failed_result(status: int) -> None:
    verifier = RemoteHeadlessVerifier(
        base_url=WORKER, audience=WORKER, tokens=_Tokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status))),
    )
    result = await verifier("https://exemple.fr")
    assert result.error == HEADLESS_FAILED and result.gtm_js_loaded is False


async def test_network_and_token_failures_become_failed_results() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lent", request=request)

    network = RemoteHeadlessVerifier(
        base_url=WORKER, audience=WORKER, tokens=_Tokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(boom)),
    )
    assert (await network("https://exemple.fr")).error == HEADLESS_FAILED
    no_token = RemoteHeadlessVerifier(base_url=WORKER, audience=WORKER, tokens=_Tokens(fail=True))
    assert (await no_token("https://exemple.fr")).error == HEADLESS_FAILED


def test_the_api_delegates_only_when_a_worker_is_configured() -> None:
    local = get_settings().model_copy(update={"worker_base_url": ""})
    assert get_gtm_headless_verifier(local) is verify_gtm
    deployed = get_settings().model_copy(
        update={"worker_base_url": WORKER, "internal_oidc_audience": WORKER}
    )
    assert isinstance(get_gtm_headless_verifier(deployed), RemoteHeadlessVerifier)


async def test_the_remote_verifier_speaks_the_real_worker_contract(
    db_session: AsyncSession, make_user
) -> None:
    await make_site(db_session, make_user, "delegation.test")

    async def fetch_jwks() -> dict:
        return jwks_for(SIGNING_KEY)

    async def fake_browser(url: str) -> GtmHeadlessResult:
        return RESULT

    async def _session():
        yield db_session

    worker = create_worker_app(
        get_settings(),
        oidc_verifier=OidcVerifier(
            audience=WORKER, allowed_emails={API_ACCOUNT}, fetch_jwks=fetch_jwks
        ),
    )
    worker.dependency_overrides[get_session] = _session
    worker.dependency_overrides[get_headless_runner] = lambda: fake_browser
    verifier = RemoteHeadlessVerifier(
        base_url=WORKER, audience=WORKER, tokens=_Tokens(),
        client=httpx.AsyncClient(transport=ASGITransport(app=worker), base_url=WORKER),
    )
    assert await verifier("https://delegation.test") == RESULT
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_headless_delegation.py -v`
Attendu : ÉCHEC (`ImportError: cannot import name 'headless_result_from_dict'`).

- [ ] **Étape 2 : désérialiser un résultat headless**

À la fin de `backend/app/services/gtm_headless.py` (imports existants suffisants) :

```python
def _flag(data: dict[str, Any], key: str) -> bool:
    value = data[key]
    if not isinstance(value, bool):
        raise ValueError(f"champ booléen attendu : {key}")
    return value


def _strings(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValueError("liste de chaînes attendue")
    return tuple(values)


def headless_result_from_dict(data: Any) -> GtmHeadlessResult:
    """Inverse exact de `headless_result_to_dict` (réponse du service worker). Toute forme
    inattendue lève `ValueError` : l'appelant la traite comme un échec du navigateur."""
    if not isinstance(data, dict):
        raise ValueError("résultat headless illisible")
    try:
        findings_raw = data["findings"]
        if not isinstance(findings_raw, list) or not all(isinstance(f, dict) for f in findings_raw):
            raise ValueError("findings illisibles")
        findings = tuple(
            GtmFinding(
                code=str(f["code"]),
                severity=f["severity"],
                title=str(f["title"]),
                detail=str(f["detail"]),
            )
            for f in findings_raw
        )
        error = data.get("error")
        ads_requests = data.get("ads_requests", 0)
        if isinstance(ads_requests, bool) or not isinstance(ads_requests, int):
            raise ValueError("ads_requests illisible")
        return GtmHeadlessResult(
            gtm_js_loaded=_flag(data, "gtm_js_loaded"),
            containers_initialised=_strings(data["containers_initialised"]),
            datalayer_present=_flag(data, "datalayer_present"),
            gtm_events=_strings(data["gtm_events"]),
            requests_before_consent=_flag(data, "requests_before_consent"),
            csp_console_errors=_strings(data["csp_console_errors"]),
            findings=findings,
            checked_at=datetime.fromisoformat(str(data["checked_at"])),
            error=str(error) if error is not None else None,
            ga4_measurement_ids=_strings(data.get("ga4_measurement_ids", [])),
            ads_requests=ads_requests,
            consent_default_seen=_flag(data, "consent_default_seen")
            if "consent_default_seen" in data
            else False,
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("résultat headless illisible") from exc
```

- [ ] **Étape 3 : écrire le client du worker**

```python
# backend/app/services/worker_client.py
"""Appel du service worker par l'API : vérification headless (l'image de l'API n'a plus
Chromium). Jeton d'identité du compte de service de l'API (serveur de métadonnées),
vérifié par le worker. Ne lève jamais : toute panne devient un résultat en échec,
exactement comme un échec local de `verify_gtm`."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from app.services.gcp_metadata import IdentityTokenProvider, MetadataError
from app.services.gtm_headless import (
    HEADLESS_FAILED,
    GtmHeadlessResult,
    headless_result_from_dict,
)

logger = logging.getLogger(__name__)


def _failed() -> GtmHeadlessResult:
    return GtmHeadlessResult(
        gtm_js_loaded=False,
        containers_initialised=(),
        datalayer_present=False,
        gtm_events=(),
        requests_before_consent=False,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime.now(UTC),
        error=HEADLESS_FAILED,
    )


class RemoteHeadlessVerifier:
    def __init__(
        self,
        *,
        base_url: str,
        audience: str,
        tokens: IdentityTokenProvider,
        client: httpx.AsyncClient | None = None,
        timeout: float = 150.0,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/internal/headless/verify"
        self._audience = audience
        self._tokens = tokens
        self._client = client
        self._timeout = httpx.Timeout(timeout)

    async def __call__(self, url: str) -> GtmHeadlessResult:
        try:
            token = await self._tokens.identity_token(self._audience)
        except MetadataError:
            logger.warning("jeton d'identité indisponible pour le worker", extra={"event": "headless_delegation"})
            return _failed()
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await http.post(
                self._url, json={"url": url}, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "worker injoignable pour la vérification headless",
                extra={"event": "headless_delegation", "error": type(exc).__name__},
            )
            return _failed()
        finally:
            if owns:
                await http.aclose()
        if response.status_code != 200:
            logger.warning(
                "le worker a refusé la vérification headless",
                extra={"event": "headless_delegation", "status": response.status_code},
            )
            return _failed()
        try:
            return headless_result_from_dict(response.json())
        except ValueError:
            logger.warning("réponse headless illisible", extra={"event": "headless_delegation"})
            return _failed()
```

- [ ] **Étape 4 : brancher la dépendance**

Dans `backend/app/api/deps.py` : ajouter les imports
`from app.services.gcp_metadata import MetadataTokenProvider` et
`from app.services.worker_client import RemoteHeadlessVerifier`, puis remplacer la
fonction `get_gtm_headless_verifier` par :

```python
# Un seul fournisseur par processus : il met en cache le jeton d'identité (50 min).
_METADATA_TOKENS = MetadataTokenProvider()


def get_gtm_headless_verifier(settings: SettingsDep) -> GtmHeadlessVerifier:
    # Jamais gate sur un flag mock : c'est une action explicite (bouton /
    # outil agent), jamais declenchee automatiquement par un scan. Les tests
    # overrident cette dependance pour ne jamais lancer de vrai navigateur.
    # Deploye, l'image de l'API n'a plus Chromium : le navigateur tourne sur le
    # service worker (meme resultat, meme contrat). En local, verify_gtm direct.
    if settings.worker_base_url:
        return RemoteHeadlessVerifier(
            base_url=settings.worker_base_url,
            audience=settings.internal_oidc_audience or settings.worker_base_url,
            tokens=_METADATA_TOKENS,
        )
    return verify_gtm
```

- [ ] **Étape 5 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_headless_delegation.py tests/test_gtm_headless.py tests/test_gtm_endpoints.py tests/test_measurement_endpoints.py tests/test_advisor_tools.py tests/test_tenant_isolation.py -v
uv run ruff check app tests
```

Attendu : tous verts ; les tests existants du headless, des endpoints GTM, du plan de
mesure et du conseiller passent sans modification.

- [ ] **Étape 6 : commit**

```bash
git add backend/app/services/gtm_headless.py backend/app/services/worker_client.py backend/app/api/deps.py backend/tests/test_headless_delegation.py
git commit -m "feat(worker): l'API delegue la verification headless au worker (jeton d'identite, meme contrat)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 15 : Images (API sans Chromium, worker avec), déploiement des deux services, environnement, runbook

**Fichiers :**
- Modifier : `backend/Dockerfile`
- Créer : `backend/Dockerfile.worker`, `backend/cloudbuild.worker.yaml`
- Modifier : `scripts/deploy-backend.sh`, `deploy/env.example.yaml`,
  `backend/app/tools/check_env.py`, `docs/ops/runbook.md`
- Test : `backend/tests/test_deploy_assets.py` (ajouts uniquement)

**Interfaces :**
- Consomme : `worker_problems` (Tâche 12) ; `validate_env`, `main`,
  `check_string_values` (`app.tools.check_env`) ; `app.worker_main:app`.
- Produit :
  - `validate_env(mapping, *, expect=None, service="api")` : `service="worker"` ajoute
    `worker_problems(settings)` ; `INTERNAL_ALLOWED_INVOKERS` est lue comme JSON.
  - `python -m app.tools.check_env FICHIER [--expect ENV] [--service api|worker]`
    (drapeaux dans n'importe quel ordre ; toute autre forme ⇒ code 2).
  - Script : services `<service>` (API, public) et `<service>-worker` (privé,
    `--no-allow-unauthenticated`, 2 Gio, 2 instances au plus, concurrence 10, délai
    900 s, compte de service `WORKER_SERVICE_ACCOUNT` ou `<service>-worker@<projet>`),
    images `<service>:<sha>` et `<service>-worker:<sha>`, variable `DEPLOY_ENV_FILE`
    pour remplacer le fichier d'environnement ; toujours 5 étapes (`== 1/5` … `== 5/5`).

- [ ] **Étape 1 : écrire les tests qui échouent**

À la fin de `backend/tests/test_deploy_assets.py` (ajouter `import os` aux imports) :

```python
# --- Lot B : deux images, deux services, service worker ---------------------------------

_WORKER_ENV = {
    "TASK_QUEUE_BACKEND": "cloud_tasks",
    "GCP_PROJECT": "guiili",
    "CLOUD_TASKS_LOCATION": "us-central1",
    "CLOUD_TASKS_QUEUE_PREFIX": "guiili",
    "TASKS_INVOKER_SERVICE_ACCOUNT": "guiili-tasks@guiili.iam.gserviceaccount.com",
    "WORKER_BASE_URL": "https://backend-guiili-worker-1.us-central1.run.app",
    "INTERNAL_OIDC_AUDIENCE": "https://backend-guiili-worker-1.us-central1.run.app",
    "INTERNAL_ALLOWED_INVOKERS": '["guiili-tasks@guiili.iam.gserviceaccount.com"]',
}


def test_the_api_image_has_no_browser_and_the_worker_image_does() -> None:
    api = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    worker = (ROOT / "backend" / "Dockerfile.worker").read_text(encoding="utf-8")
    assert "playwright install" not in api
    assert "playwright install --with-deps chromium" in worker
    worker_cmd = [line for line in worker.splitlines() if line.startswith("CMD")]
    assert worker_cmd and "app.worker_main:app" in worker_cmd[0]
    assert "alembic" not in worker_cmd[0]


def test_the_worker_build_config_uses_the_worker_dockerfile() -> None:
    config = yaml.safe_load((ROOT / "backend" / "cloudbuild.worker.yaml").read_text(encoding="utf-8"))
    args = config["steps"][0]["args"]
    assert args[:3] == ["build", "-f", "Dockerfile.worker"]
    assert "$_IMAGE" in args and config["images"] == ["$_IMAGE"]


def test_the_example_env_file_is_valid_for_the_worker() -> None:
    example = yaml.safe_load((ROOT / "deploy" / "env.example.yaml").read_text(encoding="utf-8"))
    assert validate_env({k: str(v) for k, v in example.items()}, service="worker") == []


def test_validate_env_names_missing_worker_settings_without_values() -> None:
    problems = validate_env({**_VALID}, service="worker")
    text = " ".join(problems)
    assert "WORKER_BASE_URL" in text and "INTERNAL_ALLOWED_INVOKERS" in text
    assert validate_env({**_VALID, **_WORKER_ENV}, service="worker") == []
    # Le contrôle par défaut (API) n'exige rien de nouveau.
    assert validate_env({**_VALID}) == []


def test_main_service_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_env(tmp_path, {**_VALID, **_WORKER_ENV})
    assert main(["check_env", path, "--service", "worker", "--expect", "production"]) == 0
    assert main(["check_env", path, "--expect", "production", "--service", "worker"]) == 0
    assert main(["check_env", path, "--service", "cron"]) == 2
    incomplete = _write_env(tmp_path, dict(_VALID))
    assert main(["check_env", incomplete, "--service", "worker"]) == 1
    assert "WORKER_BASE_URL" in capsys.readouterr().err


@pytest.mark.skipif(BASH is None, reason="bash indisponible")
def test_the_dry_run_builds_and_deploys_both_services(tmp_path: Path) -> None:
    env_file = tmp_path / "env.staging.yaml"
    env_file.write_text(
        yaml.safe_dump({**_VALID, **_WORKER_ENV, "ENVIRONMENT": "staging"}), encoding="utf-8"
    )
    result = subprocess.run(
        [str(BASH), str(ROOT / "scripts" / "deploy-backend.sh"), "staging", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DEPLOY_ENV_FILE": env_file.as_posix()},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    for step in ("== 1/5", "== 2/5", "== 3/5", "== 4/5", "== 5/5"):
        assert step in out
    assert "cloudbuild.worker.yaml" in out and "_IMAGE=" in out
    assert "gcloud run deploy backend-guiili-staging --image" in out
    assert "gcloud run deploy backend-guiili-staging-worker --image" in out
    worker_line = next(
        line for line in out.splitlines() if "run deploy backend-guiili-staging-worker" in line
    )
    assert "--no-allow-unauthenticated" in worker_line and "--memory 2Gi" in worker_line
    assert "(dry-run" in out


def test_the_deploy_script_checks_the_worker_configuration() -> None:
    script = (ROOT / "scripts" / "deploy-backend.sh").read_text(encoding="utf-8")
    assert '--service worker' in script
    assert "DEPLOY_ENV_FILE" in script
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_deploy_assets.py -v`
Attendu : ÉCHEC (`Dockerfile.worker` introuvable, `validate_env()` sans paramètre
`service`).

- [ ] **Étape 2 : images**

Remplacer `backend/Dockerfile` par :

```dockerfile
# Image de l'API publique (Cloud Run `backend-guiili`).
#
# Sans Chromium depuis le lot B : la verification GTM headless s'execute sur le
# service worker (Dockerfile.worker), que l'API appelle avec un jeton d'identite
# (app/services/worker_client.py). Image plus legere, demarrage a froid plus court.
# Sans WORKER_BASE_URL, le bouton headless renverrait une erreur geree proprement
# (voir app/services/gtm_headless.py) : le script de deploiement l'exige.
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
```

```dockerfile
# backend/Dockerfile.worker
# Image du service worker (Cloud Run `backend-guiili-worker`) : meme code que l'API,
# autre point d'entree (app.worker_main), avec Chromium pour la verification GTM
# headless (app/services/gtm_headless.py). Service prive : seuls Cloud Scheduler,
# Cloud Tasks et l'API l'appellent (IAM + jeton OIDC verifie dans le code).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Chromium + dependances systeme (fonts, libgtk, libnss...) du rendu headless reel.
RUN uv run playwright install --with-deps chromium

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8080

# Jamais de migration ici non plus (Cloud Run Job dedie).
CMD ["sh", "-c", "exec uvicorn app.worker_main:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

```yaml
# backend/cloudbuild.worker.yaml
# Construit l'image du worker a partir de Dockerfile.worker (`gcloud builds submit
# --tag` ne sait utiliser que `Dockerfile`). Appele par scripts/deploy-backend.sh
# avec --substitutions _IMAGE=<region>-docker.pkg.dev/<projet>/.../<service>-worker:<sha>.
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "Dockerfile.worker", "-t", "$_IMAGE", "."]
images:
  - "$_IMAGE"
```

- [ ] **Étape 3 : `check_env --service worker`**

Dans `backend/app/tools/check_env.py` :

1. importer `from app.config import Settings, worker_problems` (remplace
   `from app.config import Settings`) ;
2. `_JSON_KEYS = {"token_enc_keys", "cors_origins", "internal_allowed_invokers"}` ;
3. ajouter `_SERVICES = ("api", "worker")` sous `_ENVIRONMENTS` ;
4. signature `def validate_env(mapping: dict[str, str], *, expect: str | None = None,
   service: str = "api") -> list[str]:`, docstring complétée par « `service="worker"`
   ajoute les exigences du service worker (`worker_problems`) », et juste avant le
   `return problems` final :

```python
    if service == "worker":
        problems.extend(worker_problems(settings))
```

5. le message JSON illisible cite aussi la nouvelle variable :
   `"une variable JSON (TOKEN_ENC_KEYS, CORS_ORIGINS, INTERNAL_ALLOWED_INVOKERS) est illisible : {exc.msg}"` ;
6. remplacer l'analyse des arguments de `main` par :

```python
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
```

- [ ] **Étape 4 : fichier d'environnement modèle**

À la fin de `deploy/env.example.yaml` :

```yaml
# --- Taches planifiees et service worker (lot B) ---
# Meme fichier pour l'API et le worker. L'URL d'un service Cloud Run est
# https://<service>-<numero de projet>.<region>.run.app (connue avant le 1er deploiement).
TASK_QUEUE_BACKEND: "cloud_tasks"
GCP_PROJECT: "guiili"
CLOUD_TASKS_LOCATION: "us-central1"
CLOUD_TASKS_QUEUE_PREFIX: "guiili-staging"
TASKS_INVOKER_SERVICE_ACCOUNT: "guiili-tasks-staging@guiili.iam.gserviceaccount.com"
WORKER_BASE_URL: "https://backend-guiili-staging-worker-000000000000.us-central1.run.app"
INTERNAL_OIDC_AUDIENCE: "https://backend-guiili-staging-worker-000000000000.us-central1.run.app"
INTERNAL_ALLOWED_INVOKERS: '["guiili-tasks-staging@guiili.iam.gserviceaccount.com","guiili-scheduler-staging@guiili.iam.gserviceaccount.com","backend-guiili-staging@guiili.iam.gserviceaccount.com"]'
```

- [ ] **Étape 5 : script de déploiement**

Remplacer `scripts/deploy-backend.sh` par :

```bash
#!/usr/bin/env bash
# Deploie le backend sur Cloud Run : deux images (API sans Chromium, worker avec
# Chromium) -> migrations (Cloud Run Job) -> deux services (API publique, worker prive).
# Un echec de migration arrete tout AVANT de toucher aux services.
#
#   ./scripts/deploy-backend.sh staging
#   ./scripts/deploy-backend.sh production
#   ./scripts/deploy-backend.sh production --dry-run    # affiche sans rien executer
#
# Prerequis : gcloud connecte, deploy/env.<env>.yaml (voir deploy/env.example.yaml et
# scripts/export-service-env.sh), depot Artifact Registry `cloud-run-source-deploy`,
# comptes de service et files Cloud Tasks du lot B (docs/ops/runbook.md §15).
# DEPLOY_ENV_FILE remplace le chemin du fichier d'environnement (utilise par les tests
# du --dry-run) ; WORKER_SERVICE_ACCOUNT remplace le compte de service du worker.
set -euo pipefail

USAGE="usage: deploy-backend.sh <staging|production> [--dry-run]"
ENVIRONMENT_NAME="${1:?$USAGE}"
DRY_RUN=""
if [ "$#" -gt 2 ]; then echo "$USAGE" >&2; exit 2; fi
case "${2:-}" in
  "") ;;
  --dry-run) DRY_RUN=1 ;;
  *) echo "option inconnue : ${2} (seul --dry-run est accepte)" >&2; echo "$USAGE" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${GCP_PROJECT:-guiili}"
REGION="${GCP_REGION:-us-central1}"

case "$ENVIRONMENT_NAME" in
  production) SERVICE="backend-guiili" ;;
  staging) SERVICE="backend-guiili-staging" ;;
  *) echo "environnement inconnu : $ENVIRONMENT_NAME" >&2; exit 2 ;;
esac
WORKER="${SERVICE}-worker"
WORKER_SA="${WORKER_SERVICE_ACCOUNT:-${WORKER}@${PROJECT}.iam.gserviceaccount.com}"
JOB="${SERVICE}-migrate"
ENV_FILE="${DEPLOY_ENV_FILE:-$ROOT/deploy/env.${ENVIRONMENT_NAME}.yaml}"
TAG="$(git -C "$ROOT" rev-parse --short HEAD)"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy"
IMAGE="${REGISTRY}/${SERVICE}:${TAG}"
WORKER_IMAGE="${REGISTRY}/${WORKER}:${TAG}"

run() {
  echo "+ $*"
  if [ -z "$DRY_RUN" ]; then "$@"; fi
}

[ -f "$ENV_FILE" ] || { echo "manquant : $ENV_FILE (voir deploy/env.example.yaml)" >&2; exit 2; }

if ! git -C "$ROOT" diff --quiet || ! git -C "$ROOT" diff --cached --quiet; then
  echo "ATTENTION : des modifications non committees seront absentes des images (tag $TAG)." >&2
fi

echo "== 1/5 Verification du fichier d'environnement (API puis worker)"
PY="$ROOT/backend/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "venv backend introuvable (uv sync dans backend/)" >&2; exit 2; }
( cd "$ROOT/backend" && "$PY" -m app.tools.check_env "$ENV_FILE" --expect "$ENVIRONMENT_NAME" )
( cd "$ROOT/backend" && "$PY" -m app.tools.check_env "$ENV_FILE" --expect "$ENVIRONMENT_NAME" --service worker )

echo "== 2/5 Construction des images $IMAGE et $WORKER_IMAGE"
run gcloud builds submit "$ROOT/backend" --tag "$IMAGE" --project "$PROJECT" --region "$REGION"
run gcloud builds submit "$ROOT/backend" --config "$ROOT/backend/cloudbuild.worker.yaml" \
  --substitutions "_IMAGE=$WORKER_IMAGE" --project "$PROJECT" --region "$REGION"

echo "== 3/5 Migrations (Cloud Run Job $JOB)"
run gcloud run jobs deploy "$JOB" --image "$IMAGE" --project "$PROJECT" --region "$REGION" \
  --command alembic --args upgrade,head --env-vars-file "$ENV_FILE" \
  --max-retries 0 --task-timeout 600 --execute-now --wait

echo "== 4/5 Deploiement des services $SERVICE (public) et $WORKER (prive)"
run gcloud run deploy "$SERVICE" --image "$IMAGE" --project "$PROJECT" --region "$REGION" \
  --env-vars-file "$ENV_FILE" --allow-unauthenticated \
  --memory 512Mi --cpu 1 --cpu-boost --max-instances 3
run gcloud run deploy "$WORKER" --image "$WORKER_IMAGE" --project "$PROJECT" --region "$REGION" \
  --env-vars-file "$ENV_FILE" --no-allow-unauthenticated --service-account "$WORKER_SA" \
  --memory 2Gi --cpu 1 --max-instances 2 --concurrency 10 --timeout 900

echo "== 5/5 Verification"
if [ -n "$DRY_RUN" ]; then
  echo "(dry-run : verification non executee)"; exit 0
fi
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
WORKER_URL="$(gcloud run services describe "$WORKER" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
for attempt in 1 2 3 4 5; do
  if curl -fsS "$URL/health/db" >/dev/null \
    && curl -fsS -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$WORKER_URL/health/db" >/dev/null; then
    echo "OK : $URL/health/db et $WORKER_URL/health/db repondent (images $TAG)."
    exit 0
  fi
  echo "tentative $attempt/5 : pas encore pret, nouvel essai dans 5 s"
  sleep 5
done
echo "ECHEC : un des services ne repond pas. Retour arriere :" >&2
echo "  gcloud run services update-traffic $SERVICE --project $PROJECT --region $REGION --to-revisions=<REVISION_PRECEDENTE>=100" >&2
echo "  gcloud run services update-traffic $WORKER --project $PROJECT --region $REGION --to-revisions=<REVISION_PRECEDENTE>=100" >&2
exit 1
```

(`run` affiche chaque commande sur une seule ligne, `+ gcloud ...`, quel que soit le
découpage du script : le test du `--dry-run` lit les options sur cette ligne.)

- [ ] **Étape 6 : runbook**

Dans `docs/ops/runbook.md` :

1. **§1**, à la fin du paragraphe « Variables clés d'un fichier d'environnement », ajouter :

```markdown
Variables du lot B (tâches planifiées et service worker, obligatoires hors `local` pour
le worker et vérifiées par `check_env --service worker`) : `TASK_QUEUE_BACKEND`
(`cloud_tasks`), `GCP_PROJECT`, `CLOUD_TASKS_LOCATION`, `CLOUD_TASKS_QUEUE_PREFIX`
(`guiili` en production, `guiili-staging` en préproduction), `TASKS_INVOKER_SERVICE_ACCOUNT`,
`WORKER_BASE_URL`, `INTERNAL_OIDC_AUDIENCE` (en général égale à `WORKER_BASE_URL`),
`INTERNAL_ALLOWED_INVOKERS` (JSON : comptes de Cloud Tasks, de Cloud Scheduler et de
l'API). Réglages optionnels : `JOBS_WORKSPACE_CONCURRENCY` (2), `JOBS_WORKSPACE_DAILY_CAP`
(300), `JOBS_TICK_BATCH` (100), `JOBS_LEASE_SECONDS` (900), `JOBS_MAX_ATTEMPTS` (5).
Les deux services lisent le même fichier.
```

2. **§2**, remplacer la liste des cinq étapes par :

```markdown
1. **Vérification du fichier d'environnement**, deux fois : `check_env ... --expect
   <env>` (règles de l'API) puis `check_env ... --expect <env> --service worker`
   (variables du lot B). Mêmes garanties qu'avant : aucune valeur affichée, exécutée
   même avec `--dry-run`.
2. **Construction des images** : `<service>:<sha-court>` (API, `backend/Dockerfile`, sans
   Chromium) et `<service>-worker:<sha-court>` (`backend/Dockerfile.worker`, avec
   Chromium, construite via `backend/cloudbuild.worker.yaml`).
3. **Migrations** : inchangé (Cloud Run Job `<service>-migrate`, image de l'API).
4. **Déploiement des services** : `<service>` comme avant (public, 512 Mi, 3 instances) ;
   puis `<service>-worker`, **privé** (`--no-allow-unauthenticated`), compte de service
   `<service>-worker@<projet>.iam.gserviceaccount.com` (ou `WORKER_SERVICE_ACCOUNT`),
   2 Gi, 1 CPU, 2 instances au plus, concurrence 10, délai de 900 s.
5. **Vérification** : `/health/db` de l'API, puis celui du worker avec
   `gcloud auth print-identity-token` (le worker refuse les appels anonymes).
```

   et ajouter, après « **Exposition** : … » : « Le worker, lui, n'est **jamais** public :
   seuls les comptes ayant `roles/run.invoker` (Cloud Tasks, Cloud Scheduler, API,
   propriétaire) l'atteignent, et le code vérifie en plus le jeton OIDC (audience et
   e-mail). »

3. **§8**, ajouter au tableau :

```markdown
| `GET /websites/{id}/metrics/series` | utilisateur | 120 / min |
| `GET /websites/{id}/schedules` | utilisateur | 120 / min |
| `PUT /websites/{id}/schedules` | utilisateur | 30 / min |
```

4. **§11**, ajouter au point 2 : « et, pour le lot B, le rôle Service Account User sur le
   compte de service du worker (`backend-guiili-staging-worker@…`), sans quoi le
   déploiement du worker échoue ».

5. **§12**, ajouter les points :

```markdown
10. **Collectes en échec ou en retard** : `GET <WORKER_URL>/internal/jobs/health` avec
    `-H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=<WORKER_URL>)"`
    (le compte doit figurer dans `INTERNAL_ALLOWED_INVOKERS`), puis §15.5.
11. **Quota Google atteint en boucle** : le disjoncteur suspend 30 minutes la source d'un
    workspace après 3 échecs `quota` ; vérifier le débit de la file (`gcloud tasks queues
    describe guiili-ga4 ...`) avant de l'augmenter.
```

6. **§13**, remplacer la puce « séparation des services `api` / `worker` et image API
   allégée sans Chromium (lot B) ; aujourd'hui une seule image, avec Chromium pour la
   vérification GTM headless ; » par « séparation des services `api` / `worker` : faite
   au lot B (§15) ; ».

7. Ajouter à la fin du fichier la section suivante :

````markdown
## 15. Tâches planifiées et service worker (lot B)

### 15.1 Architecture

Cloud Scheduler appelle `POST <WORKER_URL>/internal/tick` toutes les 15 minutes (jeton
OIDC du compte `guiili-scheduler`). Le passage matérialise les plannings par défaut,
réserve les échéances dues et dépose une tâche Cloud Tasks par exécution, dans la file
de sa source (`<préfixe>-ga4`, `-gsc`, `-cwv`, `-light`, `-heavy`). Cloud Tasks appelle
`POST <WORKER_URL>/internal/tasks/run` avec un jeton OIDC du compte `guiili-tasks` ;
une réponse 503 déclenche une nouvelle tentative (5 au plus, backoff 60 s → 1 h). Chaque
exécution laisse une ligne `job_runs` (clé d'idempotence `type:site:fenêtre`, bail de
15 minutes). L'API appelle `POST <WORKER_URL>/internal/headless/verify` pour la
vérification GTM en conditions réelles (le navigateur n'existe que dans l'image du
worker). Aucune de ces routes n'existe dans l'API publique.

Fréquences proposées : toutes les heures, 3 fois par jour, tous les jours, tous les 3
jours, toutes les semaines ; planchers : 8 h pour GA4, Search Console, Core Web Vitals
et la vérification du plan de mesure, 1 h pour les sondes (TLS, disponibilité). Limites
par workspace : 2 tâches simultanées, 300 tâches déposées par jour.

### 15.2 Mise en place unique [PROPRIÉTAIRE]

Exemple pour la production (préproduction : suffixe `-staging` sur les comptes, les
files et le job). Remplacer `<NUM>` par le numéro du projet
(`gcloud projects describe guiili --format='value(projectNumber)'`) ; l'URL du worker est
alors `https://backend-guiili-worker-<NUM>.us-central1.run.app`.

```bash
# 1. API Google Cloud
gcloud services enable cloudtasks.googleapis.com cloudscheduler.googleapis.com --project guiili

# 2. Comptes de service
gcloud iam service-accounts create backend-guiili-worker --project guiili --display-name "Guiili worker"
gcloud iam service-accounts create guiili-tasks --project guiili --display-name "Guiili Cloud Tasks (OIDC)"
gcloud iam service-accounts create guiili-scheduler --project guiili --display-name "Guiili Cloud Scheduler (OIDC)"

# 3. Files (une par source ; la file heavy exécute une tâche à la fois)
for spec in "ga4 2 5" "gsc 2 5" "cwv 1 2" "light 5 10" "heavy 1 1"; do
  set -- $spec
  gcloud tasks queues create "guiili-$1" --location us-central1 --project guiili \
    --max-dispatches-per-second "$2" --max-concurrent-dispatches "$3" \
    --max-attempts 5 --min-backoff 60s --max-backoff 3600s --max-doublings 4
done

# 4. Le worker dépose des tâches et les signe au nom de guiili-tasks
gcloud projects add-iam-policy-binding guiili \
  --member serviceAccount:backend-guiili-worker@guiili.iam.gserviceaccount.com \
  --role roles/cloudtasks.enqueuer
gcloud iam service-accounts add-iam-policy-binding guiili-tasks@guiili.iam.gserviceaccount.com \
  --member serviceAccount:backend-guiili-worker@guiili.iam.gserviceaccount.com \
  --role roles/iam.serviceAccountUser
```

5. Compléter `deploy/env.production.yaml` avec les variables du lot B (§1) :
   `WORKER_BASE_URL` et `INTERNAL_OIDC_AUDIENCE` =
   `https://backend-guiili-worker-<NUM>.us-central1.run.app`,
   `TASKS_INVOKER_SERVICE_ACCOUNT` = `guiili-tasks@guiili.iam.gserviceaccount.com`,
   `INTERNAL_ALLOWED_INVOKERS` = les e-mails de `guiili-tasks`, `guiili-scheduler` et du
   compte d'exécution de l'API (par défaut `<NUM>-compute@developer.gserviceaccount.com`,
   visible dans `gcloud run services describe backend-guiili --format='value(spec.template.spec.serviceAccountName)'`).
6. Déployer : `./scripts/deploy-backend.sh production --dry-run`, puis sans `--dry-run`
   (le premier passage crée le service worker).

```bash
# 7. Qui peut appeler le worker (après sa création)
for member in \
  serviceAccount:guiili-tasks@guiili.iam.gserviceaccount.com \
  serviceAccount:guiili-scheduler@guiili.iam.gserviceaccount.com \
  serviceAccount:<COMPTE_DE_L_API>; do
  gcloud run services add-iam-policy-binding backend-guiili-worker \
    --region us-central1 --project guiili --member "$member" --role roles/run.invoker
done

# 8. Le passage du planificateur, toutes les 15 minutes
gcloud scheduler jobs create http guiili-tick --location us-central1 --project guiili \
  --schedule "*/15 * * * *" --http-method POST \
  --uri "https://backend-guiili-worker-<NUM>.us-central1.run.app/internal/tick" \
  --oidc-service-account-email guiili-scheduler@guiili.iam.gserviceaccount.com \
  --oidc-token-audience "https://backend-guiili-worker-<NUM>.us-central1.run.app"

# 9. Alerte : métrique basée sur les logs, puis règle d'alerte (console Monitoring)
gcloud logging metrics create guiili-jobs-health-alert --project guiili \
  --description "Tâches planifiées en échec ou en retard" \
  --log-filter 'jsonPayload.message="jobs_health_alert" AND severity>=ERROR'
```

10. Dans la console Cloud Monitoring, créer une règle d'alerte sur la métrique
    `logging/user/guiili-jobs-health-alert` (seuil > 0 sur 30 minutes) avec la
    notification de l'équipe. Sentry reçoit en plus l'événement « Tâches planifiées en
    échec ou en retard » si `SENTRY_DSN` est réglé.

### 15.3 Vérifier que tout tourne

```bash
WORKER_URL=https://backend-guiili-worker-<NUM>.us-central1.run.app
TOKEN=$(gcloud auth print-identity-token --audiences="$WORKER_URL")
curl -fsS -H "Authorization: Bearer $TOKEN" "$WORKER_URL/internal/jobs/health"
gcloud scheduler jobs run guiili-tick --location us-central1 --project guiili   # passage immédiat
```

Le compte utilisé pour `print-identity-token` doit figurer dans
`INTERNAL_ALLOWED_INVOKERS` (sinon 403) et avoir `roles/run.invoker` sur le worker.

### 15.4 En local

Pas de Cloud Tasks ni d'OIDC : `TASK_QUEUE_BACKEND` reste `inline` (défaut). Un passage
du planificateur, avec exécution immédiate des tâches dues dans le processus :

```bash
cd backend && .venv/Scripts/python.exe -m app.tools.jobs tick
```

(refusé hors `ENVIRONMENT=local` ; appelle réellement Google, PageSpeed et les sites.)

### 15.5 Lire les logs des tâches

```text
# Alertes de santé (ERROR : à traiter par nous ; WARNING : seul le client peut agir)
jsonPayload.message="jobs_health_alert"
# Échecs typés d'exécution
jsonPayload.event="job_failed"
# Plantages inattendus (trace complète)
jsonPayload.event="job_crashed"
# Dépôts Cloud Tasks en échec
jsonPayload.event="job_enqueue_failed"
# Appels internes refusés (jeton absent, mauvaise audience, compte non autorisé)
jsonPayload.event="internal_denied"
```

Codes d'erreur (`job_runs.error_code`) : `quota`, `network`, `api_error` (repris
automatiquement) ; `token_unavailable`, `permission_or_api_disabled`, `not_found`,
`site_unreachable` (le client doit agir : reconnecter Google, droits, site) ;
`circuit_open` (disjoncteur de quota, 30 min) ; `not_dispatched`, `enqueue_failed`,
`lease_expired` (exploitation) ; `internal_error` (bogue : voir `job_crashed`). Une
source non reliée donne une exécution `skipped`, jamais une alerte.

### 15.6 Données et rétention

`metric_points` est partitionnée par mois (`metric_points_pAAAA_MM`, plus
`metric_points_default`) ; la tâche quotidienne `partition_maintenance` crée les mois
M-4 à M+3, supprime les partitions de plus de 25 mois et les `job_runs` terminés depuis
plus de 90 jours. Les cumuls (`metric_rollups`) sont conservés sans limite. Supprimer
un site (purge) supprime toutes ses lignes (cascade).
````

- [ ] **Étape 7 : lancer les tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_deploy_assets.py tests/test_ci_workflows.py -v
uv run ruff check app tests
bash -n ../scripts/deploy-backend.sh
```

Attendu : tous verts (les tests existants du script — options refusées, `== 1/5`
absent avant toute action, `--expect "$ENVIRONMENT_NAME"` — passent sans
modification).

- [ ] **Étape 8 : commit**

```bash
git add backend/Dockerfile backend/Dockerfile.worker backend/cloudbuild.worker.yaml backend/app/tools/check_env.py backend/tests/test_deploy_assets.py scripts/deploy-backend.sh deploy/env.example.yaml docs/ops/runbook.md
git commit -m "build(worker): image API sans Chromium, image et service worker, deploiement des deux services, runbook du lot B

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 16 : Frontend « Suivi automatique »

**Fichiers :**
- Créer : `frontend/lib/api/schedules.ts`, `frontend/components/plan/auto-tracking-card.tsx`
- Modifier : `frontend/components/plan/plan-view.tsx`

**Interfaces :**
- Consomme : `GET/PUT /api/v1/websites/{website_id}/schedules` (Tâche 13) ; `apiGet`,
  `apiPut`, `ApiError` (`frontend/lib/api/client.ts`) ; `formatDateTime`
  (`frontend/components/plan/format.ts`).
- Produit : `fetchSchedules(websiteId) -> Promise<SchedulesDto>`,
  `updateSchedule(websiteId, {kind, frequency, enabled}) -> Promise<SchedulesDto>`,
  `describeScheduleError(error) -> string` ; composant `<AutoTrackingCard websiteId />`
  affiché dans la page Plan de mesure (sites réels uniquement : la page n'affiche pas le
  plan pour un site de démonstration). Lecture seule quand `can_edit` est faux ; lignes
  clés par `kind`.

Direction artistique (rappel des Contraintes globales) : aucune couleur décorative,
uniquement les couleurs de statut (`text-ok`, `text-warn`, `text-danger`), cartes
`rounded-xl border border-white/[0.08] bg-surface/60`.

- [ ] **Étape 1 : écrire le client**

```ts
// frontend/lib/api/schedules.ts
import { ApiError, apiGet, apiPut } from "./client";

// Types alignés sur `backend/app/api/v1/endpoints/metrics.py` (le backend fait foi).

export type ScheduleKind =
  | "collect_ga4"
  | "collect_gsc"
  | "collect_cwv"
  | "collect_probes"
  | "measurement_check";

export type ScheduleFrequency =
  | "hourly"
  | "three_daily"
  | "daily"
  | "every_3_days"
  | "weekly";

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "skipped";

export interface ScheduleDto {
  kind: ScheduleKind;
  label: string;
  frequency: ScheduleFrequency;
  enabled: boolean;
  /** Fréquences permises par le plancher de la source (quotas Google : 8 h). */
  allowed_frequencies: ScheduleFrequency[];
  floor_hours: number;
  next_due_at: string | null;
  last_run_at: string | null;
  last_status: RunStatus | null;
  last_success_at: string | null;
  failing_since: string | null;
  last_error_code: string | null;
  /** Texte français décidé par le backend : à afficher tel quel. */
  last_error: string | null;
  backfill_done_at: string | null;
}

export interface SchedulesDto {
  website_id: string;
  /** Vrai seulement pour le propriétaire du workspace (le backend fait foi). */
  can_edit: boolean;
  frequency_labels: Record<ScheduleFrequency, string>;
  schedules: ScheduleDto[];
}

export interface ScheduleUpdate {
  kind: ScheduleKind;
  frequency: ScheduleFrequency;
  enabled: boolean;
}

export function fetchSchedules(websiteId: string): Promise<SchedulesDto> {
  return apiGet<SchedulesDto>(`/websites/${websiteId}/schedules`);
}

/** Réservé au propriétaire (403 pour un membre). */
export function updateSchedule(websiteId: string, body: ScheduleUpdate): Promise<SchedulesDto> {
  return apiPut<SchedulesDto>(`/websites/${websiteId}/schedules`, body);
}

/**
 * Message français pour une erreur du suivi automatique : une limite de débit (429), un
 * refus de droits (403) ou une panne (5xx) ne sont jamais présentés comme « API hors ligne ».
 */
export function describeScheduleError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return "Trop de demandes, réessaie dans un instant.";
    if (error.status === 403) {
      return "Seul le propriétaire du workspace peut modifier le suivi automatique.";
    }
    if (error.status === 0) return "Le service est injoignable ou trop lent, réessaie.";
    if (error.status === 422) {
      return "Fréquence refusée : elle est plus rapide que ce que permet cette source.";
    }
    if (error.status >= 500) {
      return "Le service a rencontré une erreur, réessaie dans un instant.";
    }
    return error.message;
  }
  return "Une erreur inattendue est survenue, réessaie.";
}
```

- [ ] **Étape 2 : écrire la carte**

```tsx
// frontend/components/plan/auto-tracking-card.tsx
"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  describeScheduleError,
  fetchSchedules,
  updateSchedule,
  type ScheduleDto,
  type ScheduleFrequency,
  type SchedulesDto,
} from "@/lib/api/schedules";

import { formatDateTime } from "./format";

const SELECT =
  "h-8 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2 text-xs text-ink focus:border-ink/40 focus:outline-none disabled:opacity-60";
const SECONDARY =
  "inline-flex h-8 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink";

interface SchedulePatch {
  frequency: ScheduleFrequency;
  enabled: boolean;
}

function statusOf(schedule: ScheduleDto): { label: string; tone: string } {
  if (!schedule.enabled) return { label: "En pause", tone: "text-ink-faint" };
  switch (schedule.last_status) {
    case "succeeded":
      return { label: "À jour", tone: "text-ok" };
    case "failed":
      return { label: "En échec", tone: "text-danger" };
    case "skipped":
      return { label: "En attente", tone: "text-warn" };
    case "queued":
    case "running":
      return { label: "En cours", tone: "text-ink-muted" };
    default:
      return { label: "Pas encore exécuté", tone: "text-ink-faint" };
  }
}

function ScheduleRow({
  schedule,
  labels,
  canEdit,
  saving,
  onPatch,
}: {
  schedule: ScheduleDto;
  labels: Record<ScheduleFrequency, string>;
  canEdit: boolean;
  saving: boolean;
  onPatch: (patch: SchedulePatch) => void;
}) {
  const status = statusOf(schedule);
  const lastRun = formatDateTime(schedule.last_run_at);
  const nextRun = schedule.enabled ? formatDateTime(schedule.next_due_at) : null;
  const showError = schedule.last_error !== null && schedule.last_status !== "succeeded";

  return (
    <li className="flex flex-wrap items-start justify-between gap-3 px-5 py-3">
      <div className="min-w-0 space-y-1">
        <p className="text-sm text-ink">{schedule.label}</p>
        <p className="text-2xs text-ink-faint">
          <span className={status.tone}>{status.label}</span>
          {lastRun ? ` · dernier passage le ${lastRun}` : ""}
          {nextRun ? ` · prochain vers le ${nextRun}` : ""}
        </p>
        {showError && <p className="text-2xs text-ink-muted">{schedule.last_error}</p>}
      </div>
      <div className="flex items-center gap-3">
        {saving && <Loader2 className="size-3.5 animate-spin text-ink-muted" aria-hidden />}
        <select
          aria-label={`Fréquence : ${schedule.label}`}
          className={SELECT}
          value={schedule.frequency}
          disabled={!canEdit || saving}
          onChange={(event) =>
            onPatch({
              frequency: event.target.value as ScheduleFrequency,
              enabled: schedule.enabled,
            })
          }
        >
          {schedule.allowed_frequencies.map((frequency) => (
            <option key={frequency} value={frequency}>
              {labels[frequency] ?? frequency}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-ink-muted">
          <input
            type="checkbox"
            className="size-3.5 accent-zinc-200"
            checked={schedule.enabled}
            disabled={!canEdit || saving}
            onChange={(event) =>
              onPatch({ frequency: schedule.frequency, enabled: event.target.checked })
            }
          />
          Actif
        </label>
      </div>
    </li>
  );
}

export function AutoTrackingCard({ websiteId }: { websiteId: string }) {
  const [data, setData] = useState<SchedulesDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingKind, setSavingKind] = useState<string | null>(null);
  // Numéro du chargement en cours : une réponse arrivée après un changement de site est ignorée.
  const runId = useRef(0);

  const load = useCallback(async () => {
    const run = ++runId.current;
    try {
      const next = await fetchSchedules(websiteId);
      if (runId.current === run) {
        setData(next);
        setError(null);
      }
    } catch (err) {
      if (runId.current === run) setError(describeScheduleError(err));
    }
  }, [websiteId]);

  useEffect(() => {
    void load();
    return () => {
      runId.current += 1;
    };
  }, [load]);

  async function change(schedule: ScheduleDto, patch: SchedulePatch) {
    setSavingKind(schedule.kind);
    try {
      setData(await updateSchedule(websiteId, { kind: schedule.kind, ...patch }));
      toast("Suivi automatique mis à jour");
    } catch (err) {
      toast.error(describeScheduleError(err));
    } finally {
      setSavingKind(null);
    }
  }

  return (
    <section className="rounded-xl border border-white/[0.08] bg-surface/60">
      <div className="space-y-1 p-5 pb-3">
        <p className="text-sm font-medium text-ink">Suivi automatique</p>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          On relève tes données et on revérifie ton site tout seuls, à la fréquence choisie.
          Les sources Google et les Core Web Vitals sont relevés au plus toutes les 8 heures
          (quotas de Google).
        </p>
      </div>

      {data === null && error === null && (
        <p className="flex items-center gap-2 px-5 pb-5 text-xs text-ink-muted" role="status">
          <Loader2 className="size-3.5 animate-spin" />
          Chargement du suivi automatique…
        </p>
      )}

      {data === null && error !== null && (
        <div className="flex flex-wrap items-center gap-3 px-5 pb-5">
          <p className="text-xs text-ink-muted">Impossible de charger le suivi automatique : {error}</p>
          <button type="button" onClick={() => void load()} className={SECONDARY}>
            Réessayer
          </button>
        </div>
      )}

      {data !== null && (
        <>
          <ul className="divide-y divide-white/[0.06] border-t border-white/[0.06]">
            {data.schedules.map((schedule) => (
              <ScheduleRow
                key={schedule.kind}
                schedule={schedule}
                labels={data.frequency_labels}
                canEdit={data.can_edit}
                saving={savingKind === schedule.kind}
                onPatch={(patch) => void change(schedule, patch)}
              />
            ))}
          </ul>
          {!data.can_edit && (
            <p className="border-t border-white/[0.06] px-5 py-3 text-2xs text-ink-faint">
              Seul le propriétaire du workspace peut modifier le suivi automatique.
            </p>
          )}
        </>
      )}
    </section>
  );
}
```

- [ ] **Étape 3 : l'afficher dans la page Plan de mesure**

Dans `frontend/components/plan/plan-view.tsx` :

1. ajouter l'import (ordre alphabétique des imports locaux, après `./ads-settings`) :

```tsx
import { AutoTrackingCard } from "./auto-tracking-card";
```

2. juste après `<StarterPackCard websiteId={websiteId} plan={plan} />`, ajouter :

```tsx
      <AutoTrackingCard websiteId={websiteId} />
```

- [ ] **Étape 4 : construire et vérifier le lint**

```bash
cd frontend
npm run build
npm run lint
```

Attendu : build réussi, lint à 0 erreur / 0 avertissement.

- [ ] **Étape 5 : vérification visuelle (facultative mais recommandée)**

Lancer `./scripts/dev.sh`, se connecter, ouvrir `/plan` sur un site réel : la carte
« Suivi automatique » liste 5 lignes (GA4, Search Console, Core Web Vitals, certificat et
disponibilité, vérification du plan) avec « Pas encore exécuté » ; changer une fréquence
affiche le toast « Suivi automatique mis à jour » ; la liste de GA4 ne propose pas
« Toutes les heures ». Avec un compte membre (non propriétaire), les contrôles sont
désactivés et la mention « Seul le propriétaire… » s'affiche.

- [ ] **Étape 6 : commit**

```bash
git add frontend/lib/api/schedules.ts frontend/components/plan/auto-tracking-card.tsx frontend/components/plan/plan-view.tsx
git commit -m "feat(front): carte « Suivi automatique » (frequence, dernier passage, statut, lecture seule hors proprietaire)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Tâche 17 : Vérification finale et mémoire

**Fichiers :**
- Modifier : `C:\Users\DELL\.claude\projects\C--Users-DELL-Downloads-Guiili\memory\roadmap-v3-and-production-foundation.md`
  et `C:\Users\DELL\.claude\projects\C--Users-DELL-Downloads-Guiili\memory\MEMORY.md`
  (hors dépôt, pas de commit)

**Interfaces :**
- Consomme : tout le lot.
- Produit : preuve que la branche `feat/data-platform` est prête pour la revue finale.

- [ ] **Étape 1 : suite backend complète, deux fois**

```bash
cd backend
.venv/Scripts/python.exe -m pytest -W error -q
.venv/Scripts/python.exe -m pytest -W error -q
```

Attendu : deux passages verts identiques, 809 tests de départ + ceux du lot (environ
150 de plus), aucun avertissement.

- [ ] **Étape 2 : lint et schéma**

```bash
cd backend
uv run ruff check app tests
ALEMBIC_DATABASE_URL="postgresql+asyncpg://cc:cc@localhost:55432/control_center_migrations" .venv/Scripts/python.exe -m alembic upgrade head
ALEMBIC_DATABASE_URL="postgresql+asyncpg://cc:cc@localhost:55432/control_center_migrations" .venv/Scripts/python.exe -m alembic check
ALEMBIC_DATABASE_URL="postgresql+asyncpg://cc:cc@localhost:55432/control_center_migrations" .venv/Scripts/python.exe -m alembic downgrade 8f2a6c41d7b3
ALEMBIC_DATABASE_URL="postgresql+asyncpg://cc:cc@localhost:55432/control_center_migrations" .venv/Scripts/python.exe -m alembic upgrade head
```

Attendu : ruff propre, « No new upgrade operations detected », descente puis remontée
sans erreur (la migration est réversible). Les identifiants de la base de migrations
viennent de `backend/.env` (`DATABASE_URL_MIGRATIONS_TEST`) ; ne jamais viser la base de
développement ni une base distante.

- [ ] **Étape 3 : frontend**

```bash
cd frontend
npm run build
npm run lint
```

Attendu : build réussi, 0 erreur / 0 avertissement.

- [ ] **Étape 4 : contrôles de périmètre**

```bash
git diff main --stat
git grep -n "internal" -- backend/app/main.py backend/app/api/v1
git diff main -- backend/app/services/google_oauth
```

Attendu : aucun fichier hors de la « Structure des fichiers » (hors `uv.lock`) ; aucune
route `/internal` dans l'API publique ; aucun changement dans `google_oauth` (donc aucun
nouveau scope : seuls `analytics.readonly` et `webmasters.readonly`).

- [ ] **Étape 5 : essai local de bout en bout (facultatif, réseau réel)**

Sur la base de développement locale (jamais la production) :

```bash
cd backend
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.tools.jobs tick
```

Attendu : « tick : N tâche(s) exécutée(s) … » ; dans la base, des lignes `job_runs`
(`succeeded` ou `skipped` pour les sites sans GA4/Search Console reliés) et des
`metric_points` `probe`/`cwv` pour les sites joignables. Puis, dans l'interface (`/plan`),
la carte « Suivi automatique » montre « À jour » et la date du dernier passage.

- [ ] **Étape 6 : revue finale de branche**

Utiliser `superpowers:requesting-code-review` sur l'ensemble de la branche
(`git diff main...feat/data-platform`), en demandant en particulier : isolation entre
clients des 3 nouvelles routes, absence de jeton dans les logs, verrous pris avant
lecture, transactions non tenues pendant le réseau, idempotence du stockage et des
tâches, comportement inchangé des endpoints existants. Corriger les constats confirmés
(un commit par correction), puis relancer les étapes 1 à 3.

- [ ] **Étape 7 : mémoire**

Mettre à jour `roadmap-v3-and-production-foundation.md` (état du lot B : branche
`feat/data-platform`, nombre de tests, non mergé, non déployé, liste [PROPRIÉTAIRE]
ci-dessous) et la ligne correspondante de `MEMORY.md`. Ne pas committer ces fichiers
(ils sont hors dépôt). Ne pas pousser la branche : le merge et le déploiement
attendent l'accord explicite du propriétaire.

- [ ] **Étape 8 : compte rendu**

Lister dans le compte rendu : nombre de tests (avant/après), résultat de la revue
finale, et les actions **[PROPRIÉTAIRE]** restantes :

1. créer les comptes de service, les 5 files Cloud Tasks par environnement, les
   liaisons IAM et le job Cloud Scheduler (runbook §15.2) ;
2. compléter `deploy/env.staging.yaml` puis `deploy/env.production.yaml` avec les
   variables du lot B (URL du worker, audience, appelants autorisés) ;
3. donner au compte de déploiement GitHub le rôle Service Account User sur le compte du
   worker de préproduction (runbook §11) ;
4. déployer la préproduction (`./scripts/deploy-backend.sh staging --dry-run`, puis
   sans), vérifier `/internal/jobs/health` et la vérification headless depuis l'API ;
5. créer l'alerte Cloud Monitoring sur `jobs_health_alert` (runbook §15.2, point 10) ;
6. décider du merge, puis du déploiement de production.

---

## Points ouverts (hors lot B, à reprendre plus tard)

- **Rapports périodiques par e-mail** : aucun fournisseur d'e-mail dans le produit ;
  reportés au lot C avec le tableau de bord (la spec §8 les listait au lot B).
- **Secret Manager** : les nouvelles variables sont des valeurs non secrètes (e-mails de
  comptes de service, URL) ; le passage des secrets existants à Secret Manager reste
  [PROPRIÉTAIRE] (runbook §10).
- **RLS Postgres** : toujours à évaluer après l'isolation applicative.
- **Utilisateurs uniques GA4** par semaine/mois : non additifs, donc absents du lot ; à
  lire directement dans GA4 (requête par période) si le tableau de bord en a besoin.
- **Ventilation par dimension** dans l'API de séries (top pages, requêtes, événements) :
  les données sont stockées, l'API les exposera au lot C ou D.
- **Search Console au-delà de 25 000 lignes** par tranche (grands sites) : pas de
  pagination au lot B ; le top 25 par jour peut alors manquer des pages de faible trafic.
- **Étalement des échéances** : tous les plannings quotidiens tombent sur le même
  créneau (minuit UTC) ; le tick en dépose au plus 100 par passage. Ajouter un décalage
  par site si la charge le justifie.
- **Tâches lourdes planifiées** : la file `heavy` existe mais aucun type planifié ne
  l'utilise (le navigateur n'est jamais lancé automatiquement, décision du lot A).
- **Limiteur de débit partagé entre instances** : toujours par instance (runbook §8).
- **Sauvegardes Neon et test de restauration** (spec §6 mesure 8) : relèvent de
  l'exploitation Neon, [PROPRIÉTAIRE], non traitées par ce plan (le mode dégradé et le
  disjoncteur de la même mesure le sont).
- **Un navigateur à la fois** : garanti par instance du worker (sémaphore) et par le
  plafond de 2 instances ; un verrou global (base) serait nécessaire si l'on montait ce
  plafond.
