# Runbook d'exploitation Guiili

Document destiné à la personne qui déploie et surveille le backend. Il décrit ce qui
existe dans le dépôt (scripts, workflow, code) ; les étapes qui touchent à la production
ou à un compte externe sont marquées **[PROPRIÉTAIRE]** : elles ne se font pas
automatiquement et ne sont pas exécutées par l'outillage du dépôt.

Repères : projet GCP `guiili`, région `us-central1` (surchargeables par les variables
d'environnement `GCP_PROJECT` et `GCP_REGION` des scripts), dépôt GitHub
`github.com/Jk3ndo/Guiili`.

## 1. Environnements

| Environnement | Backend | Frontend | Base de données | Démarrage / déploiement |
|---|---|---|---|---|
| `local` | API sur `127.0.0.1:8020` | Next.js sur `127.0.0.1:4000` | Postgres du `docker compose` | `./scripts/dev.sh` |
| `staging` | Cloud Run `backend-guiili-staging` | prévisualisation ou projet Vercel dédié, `BACKEND_ORIGIN` = URL du service de préproduction | branche Neon dédiée (`staging`) ou base vide | `./scripts/deploy-backend.sh staging` |
| `production` | Cloud Run `backend-guiili` | `frontend-guiili.vercel.app` | base Neon de production | `./scripts/deploy-backend.sh production` |

L'environnement est choisi par la variable `ENVIRONMENT` (`local`, `staging` ou
`production`, défaut `local`). Hors `local`, `Settings._enforce_environment_rules`
(`backend/app/config.py`) refuse de démarrer si l'une de ces règles est violée :

- `GOOGLE_OAUTH_MOCK` doit être `false` (sinon les routes `/dev` seraient exposées) ;
- `APP_SECRET_KEY` : au moins 32 caractères, valeur réelle (une valeur commençant par
  `REMPLACER` est refusée) ;
- `FRONTEND_BASE_URL` doit commencer par `https://` ;
- `CORS_ORIGINS` ne doit contenir que des origines `https://` ;
- en `production` uniquement : `AUDIT_PROBE_MOCK` et `ADVISOR_MOCK` doivent être `false`
  (données et réponses factices sinon). En `staging`, `ADVISOR_MOCK: "true"` est permis
  et recommandé (pas de coût Anthropic).

Hors `local`, `DATABASE_URL_TEST` et `DATABASE_URL_MIGRATIONS_TEST` sont forcées à vide
par le code : elles ne servent qu'aux tests et une base de test pointant sur la vraie
base serait détruite par `drop_all`. `REDIS_URL` n'est pas utilisée.

Variables clés d'un fichier d'environnement (modèle : `deploy/env.example.yaml`) :
`ENVIRONMENT`, `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_DATA_REDIRECT_URI`, `GOOGLE_OAUTH_MOCK`,
`AUDIT_PROBE_MOCK`, `ADVISOR_MOCK`, `PAGESPEED_API_KEY`, `ANTHROPIC_API_KEY`,
`FRONTEND_BASE_URL`, `CORS_ORIGINS`, `TOKEN_ENC_KEYS`, `TOKEN_ENC_ACTIVE_VERSION`,
`APP_SECRET_KEY`, `SENTRY_DSN`. Variables optionnelles utiles : `RATE_LIMIT_ENABLED`
(défaut `true`), `LOG_JSON` (défaut : JSON hors `local`), `ENABLE_API_DOCS` (défaut :
`/docs`, `/redoc` et `/openapi.json` exposés en `local` seulement),
`SENTRY_TRACES_SAMPLE_RATE` (défaut `0.0`), `ADVISOR_DAILY_BRIEF_CAP` (défaut 5),
`ADVISOR_DAILY_MESSAGE_CAP` (défaut 40).

Variables du lot B (tâches planifiées et service worker, obligatoires hors `local` pour
le worker et vérifiées par `check_env --service worker`) : `TASK_QUEUE_BACKEND`
(`cloud_tasks`), `GCP_PROJECT`, `CLOUD_TASKS_LOCATION`, `CLOUD_TASKS_QUEUE_PREFIX`
(`guiili` en production, `guiili-staging` en préproduction), `TASKS_INVOKER_SERVICE_ACCOUNT`,
`WORKER_BASE_URL`, `INTERNAL_OIDC_AUDIENCE` (en général égale à `WORKER_BASE_URL`),
`INTERNAL_ALLOWED_INVOKERS` (JSON : comptes de Cloud Tasks, de Cloud Scheduler et de
l'API). Réglages optionnels : `JOBS_WORKSPACE_CONCURRENCY` (2), `JOBS_WORKSPACE_DAILY_CAP`
(300), `JOBS_TICK_BATCH` (100), `JOBS_LEASE_SECONDS` (900), `JOBS_MAX_ATTEMPTS` (5).
Les deux services lisent le même fichier. L'API a elle aussi besoin de `WORKER_BASE_URL`
(en `https://`) et de `INTERNAL_OIDC_AUDIENCE` : elle s'en sert pour déléguer la
vérification GTM headless au worker.

Chaque environnement a ses **propres** secrets : ne jamais réutiliser
`APP_SECRET_KEY`, `TOKEN_ENC_KEYS` ni la base de production en préproduction.

## 2. Déployer

```bash
./scripts/deploy-backend.sh staging
./scripts/deploy-backend.sh production
./scripts/deploy-backend.sh production --dry-run   # affiche les commandes sans les exécuter
```

Prérequis : `gcloud` connecté, `git` propre (sinon un avertissement rappelle que les
modifications non committées ne sont pas dans l'image), venv backend installé
(`cd backend && uv sync`), dépôt Artifact Registry `cloud-run-source-deploy`, fichier
`deploy/env.<env>.yaml`. Seul `--dry-run` est accepté comme option : toute autre option
(ou tout argument supplémentaire) est rejetée avec le code 2. Un environnement autre que
`staging` ou `production` est rejeté.

Le script fait cinq étapes, dans l'ordre, et s'arrête à la première erreur (`set -e`) :

1. **Vérification du fichier d'environnement**, deux fois : `check_env ... --expect
   <env>` (règles de l'API) puis `check_env ... --expect <env> --service worker`
   (variables du lot B). Mêmes garanties qu'avant : aucune valeur affichée, exécutée
   même avec `--dry-run`. Trois contrôles s'y ajoutent :
   `--expect` refuse un fichier dont `ENVIRONMENT` est absent (il vaudrait `local` et
   toutes les règles de production seraient sautées) ou différent de la cible ;
   `TOKEN_ENC_KEYS` est chargé comme le fait l'API (JSON, base64 valide, 32 octets par
   clé, version active présente) ; toute valeur non textuelle (`true`, `42`, `null` sans
   guillemets) est refusée, car `gcloud --env-vars-file` n'accepte que des chaînes.
2. **Construction des images** : `<service>:<sha-court>` (API, `backend/Dockerfile`, sans
   Chromium) et `<service>-worker:<sha-court>` (`backend/Dockerfile.worker`, avec
   Chromium, construite via `backend/cloudbuild.worker.yaml`). Le paquet Python
   `playwright` reste dans l'image de l'API (le code l'importe) ; seul le navigateur
   n'y est pas installé.
3. **Migrations** : inchangé (Cloud Run Job `<service>-migrate`, image de l'API) :
   `backend-guiili-migrate` en production, `backend-guiili-staging-migrate` en
   préproduction, commande `alembic upgrade head`, `--max-retries 0`, délai de 10
   minutes, `--wait`. **Un échec de migration arrête tout avant de toucher aux
   services** : les anciennes révisions continuent de servir. Les conteneurs ne
   migrent jamais au démarrage. Le lot B ajoute deux migrations additives
   (`c3a9e5f1b8d2` : tables du lot B dont `metric_points` partitionnée ;
   `a7d41c9e2b56` : `source_quota_events`), appliquées par ce Job.
4. **Déploiement des services, le worker d'abord** : `<service>-worker`, **privé**
   (`--no-allow-unauthenticated`), compte de service
   `<service>-worker@<projet>.iam.gserviceaccount.com` (ou `WORKER_SERVICE_ACCOUNT`),
   2 Gi, 1 CPU, 2 instances au plus, concurrence 10, délai de 900 s ; puis `<service>`
   comme avant (public, 512 Mi, 3 instances). L'ordre est voulu : l'API sans Chromium
   délègue la vérification headless au worker, elle ne doit donc jamais être en ligne
   avant lui (au premier déploiement le worker n'existe pas, et son déploiement peut
   échouer, par exemple faute du rôle Service Account User, §11). Si le worker échoue,
   le script s'arrête et l'API n'est pas touchée. L'URL du worker est déterministe et
   déjà dans le fichier d'environnement, aucune donnée du déploiement du worker n'est
   nécessaire à celui de l'API.
5. **Vérification** : lit d'abord un jeton d'identité (`gcloud auth print-identity-token`,
   le script échoue clairement s'il n'en obtient pas), puis appelle `/health/db` de l'API
   et celui du worker avec ce jeton (le worker refuse les appels anonymes). Jusqu'à 5
   essais (5 secondes d'écart). En cas d'échec, le script sort en erreur et affiche les
   commandes de retour arrière des deux services (voir §5). Non exécutée avec `--dry-run`.

Variable `DEPLOY_ENV_FILE` : remplace le chemin du fichier d'environnement (par défaut
`deploy/env.<env>.yaml`) ; elle sert aux tests du `--dry-run`.

**Réglages du worker et leur justification.** Un seul processus `uvicorn` par instance
(`--workers 1`, imposé dans `Dockerfile.worker`) : le sémaphore « un seul navigateur à la
fois » est propre au processus, plusieurs processus multiplieraient les Chromium et
dépasseraient 2 Gi. Concurrence Cloud Run 10 (les tâches de collecte sont surtout des
attentes réseau ; la vérification headless, elle, est limitée à une à la fois par
processus et renvoie 503 « occupée » au-delà de 5 secondes d'attente ; l'API l'appelle
directement, sans Cloud Tasks : c'est l'utilisateur qui relance la vérification). 2 instances au plus : au pire deux navigateurs en
parallèle. Délai de requête 900 s = `dispatchDeadline` des tâches Cloud Tasks (900 s) =
`JOBS_LEASE_SECONDS` (900 s) : un gestionnaire ne peut pas durer plus que le bail ; si
Cloud Run coupe une requête à 900 s, le bail expire au même instant et l'exécution est
reprise (`lease_expired` si elle ne l'est pas). Ne jamais réduire le bail sous le délai de
requête du worker.

**Attention après un retour arrière (§5)** : si le trafic a été épinglé sur une ancienne
révision, `gcloud run deploy` crée la nouvelle révision **sans lui envoyer de trafic**.
Le contrôle final de `/health/db` interroge l'URL du service, qui sert encore l'ancienne
révision : le « OK » du script ne prouve donc pas que le nouveau code est en ligne. Pour
reprendre les déploiements normaux :

```bash
gcloud run services update-traffic backend-guiili --to-latest --region us-central1 --project guiili
```

**Exposition** : le script passe **toujours** `--allow-unauthenticated` pour l'API. Le
service de préproduction est donc joignable publiquement : utiliser une URL de service non
devinable, des secrets différents de la production et `ADVISOR_MOCK: "true"`. Le worker,
lui, n'est **jamais** public : seuls les comptes ayant `roles/run.invoker` (Cloud Tasks,
Cloud Scheduler, API, propriétaire) l'atteignent, et le code vérifie en plus le jeton OIDC
(audience et e-mail). Son `/health` et son `/health/db` ne demandent pas de jeton dans le
code : ils ne sont protégés que par l'IAM Cloud Run (service privé).

**Actions réservées au propriétaire** : `./scripts/deploy-backend.sh production` et le
retour arrière `update-traffic` (§5) ne sont exécutés que par le propriétaire du projet
GCP.

**Le fichier `deploy/env.<env>.yaml` est la source de vérité** : `--env-vars-file`
*remplace* toutes les variables du service (et du Job de migration). Une variable absente
du fichier disparaît du service au prochain déploiement. Ces fichiers sont ignorés par git
(`deploy/env.*.yaml`, ainsi que les fichiers temporaires `deploy/.env-export.*`) ; seul
`deploy/env.example.yaml` (valeurs factices) est versionné.

Le fichier est généré **une fois** à partir du service existant, puis relu et maintenu à
la main :

```bash
./scripts/export-service-env.sh production     # écrit deploy/env.production.yaml (mode 600)
cd backend
.venv/Scripts/python.exe -m app.tools.check_env ../deploy/env.production.yaml --expect production   # Windows
.venv/bin/python -m app.tools.check_env ../deploy/env.production.yaml --expect production           # Linux/macOS
```

`export-service-env.sh` refuse d'écraser un fichier existant (le supprimer d'abord pour
régénérer), n'exporte pas `DATABASE_URL_TEST`, `DATABASE_URL_MIGRATIONS_TEST` ni
`REDIS_URL`, et signale sur la sortie d'erreur toute variable provenant d'un secret Cloud
Run (à renseigner à la main). `check_env` sort avec le code 0 si le fichier est valide,
1 s'il ne l'est pas (liste des problèmes), 2 en cas d'usage incorrect (par exemple
`--expect` avec une valeur autre que `local`, `staging` ou `production`).

## 3. Amorçage unique de la production [PROPRIÉTAIRE]

À faire une seule fois, par la personne qui a accès au projet GCP `guiili`.

1. **[PROPRIÉTAIRE]** Exporter les variables actuelles du service :
   `./scripts/export-service-env.sh production`.
2. **[PROPRIÉTAIRE]** Relire `deploy/env.production.yaml`. `DATABASE_URL_TEST`,
   `DATABASE_URL_MIGRATIONS_TEST` et `REDIS_URL` n'y sont volontairement plus : les deux
   premières pointaient sur la base de production (un `pytest` lancé avec cet
   environnement aurait exécuté `drop_all` dessus), la troisième sur `localhost`. Ajouter
   à la main les valeurs qui viendraient de secrets Cloud Run (message « ATTENTION » du
   script), et éventuellement `SENTRY_DSN` (voir §7).
3. **[PROPRIÉTAIRE]** Valider :
   `cd backend && .venv/Scripts/python.exe -m app.tools.check_env ../deploy/env.production.yaml --expect production`.
4. **[PROPRIÉTAIRE]** Premier déploiement : `./scripts/deploy-backend.sh production`
   (idéalement précédé d'un `--dry-run`). Il crée le Cloud Run Job de migration
   `backend-guiili-migrate`, l'exécute, puis met à jour le service et **retire du service
   les variables obsolètes** (bases de test, Redis) puisque le fichier remplace tout.

## 4. Créer la préproduction [PROPRIÉTAIRE]

Rien dans le dépôt ne crée cet environnement. Étapes manuelles :

1. **[PROPRIÉTAIRE]** Créer dans Neon une branche `staging` depuis la production (les
   données copiées sont alors réelles : à éviter si elles contiennent des données de
   clients) ou une base vide.
2. **[PROPRIÉTAIRE]** `cp deploy/env.example.yaml deploy/env.staging.yaml`, puis le remplir :
   `DATABASE_URL` de la branche staging, secrets **différents** de la production
   (`APP_SECRET_KEY`, `TOKEN_ENC_KEYS`), `ADVISOR_MOCK: "true"`, URLs `https://` de
   l'environnement de préproduction (`FRONTEND_BASE_URL`, `CORS_ORIGINS`, les deux
   redirections Google).
3. **[PROPRIÉTAIRE]** `cd backend && .venv/Scripts/python.exe -m app.tools.check_env
   ../deploy/env.staging.yaml --expect staging`, puis `./scripts/deploy-backend.sh staging` (le service
   `backend-guiili-staging` et son Job de migration sont créés au premier passage).
4. **[PROPRIÉTAIRE]** Créer un projet Vercel (ou une prévisualisation) dont la variable
   `BACKEND_ORIGIN` pointe sur l'URL du service de préproduction.
5. **[PROPRIÉTAIRE]** Déclarer dans la console Google Cloud (identifiants OAuth) les deux
   redirections de préproduction : `GOOGLE_OAUTH_REDIRECT_URI` et
   `GOOGLE_DATA_REDIRECT_URI`.

## 5. Retour arrière

Lister les révisions puis rediriger tout le trafic vers la précédente :

```bash
gcloud run revisions list --service backend-guiili --region us-central1 --project guiili
gcloud run services update-traffic backend-guiili \
  --to-revisions=<REVISION>=100 --region us-central1 --project guiili
```

(en préproduction, remplacer par `backend-guiili-staging`). Le retour arrière ne défait
pas les migrations. Règle : **toute migration doit rester compatible avec la version
précédente du code** : ajouter une colonne ou une table avant de l'utiliser, ne supprimer
ou renommer qu'au déploiement suivant. Sinon la révision précédente échoue sur le schéma
migré et le retour arrière casse.

**Piège de Cloud Run** : après `update-traffic --to-revisions=<REVISION>=100`, le trafic
reste épinglé sur cette révision. Le `gcloud run deploy` suivant (donc
`deploy-backend.sh`) crée la nouvelle révision sans lui envoyer de trafic, et son
contrôle `/health/db` répond « OK » depuis l'ancienne révision. Une fois le problème
corrigé, pour reprendre les déploiements normaux (le trafic suit de nouveau la dernière
révision) :

```bash
gcloud run services update-traffic backend-guiili --to-latest --region us-central1 --project guiili
```

Le retour arrière et cette commande sont des actions réservées au propriétaire.

**Worker (lot B)** : la même commande s'applique à `backend-guiili-worker` (préproduction :
`backend-guiili-staging-worker`), mais **au premier déploiement il n'existe aucune
révision précédente du worker** : il n'y a alors rien vers quoi revenir. Le déploiement
étant fait worker d'abord, un échec du worker laisse l'API intacte ; seul un échec de
l'API après un worker réussi impose un retour arrière de l'API seule (le worker déjà
déployé reste compatible : il n'ajoute que des routes internes).

**Arrêt d'urgence du planificateur** : pour arrêter toute nouvelle collecte automatique
(boucle d'erreurs, quota, worker défaillant), mettre le job Cloud Scheduler en pause ; les
tâches déjà déposées dans les files continuent, les vider au besoin (`gcloud tasks queues
purge <file>`) :

```bash
gcloud scheduler jobs pause guiili-tick --location us-central1 --project guiili
gcloud scheduler jobs pause guiili-tick-staging --location us-central1 --project guiili   # préproduction
gcloud scheduler jobs resume guiili-tick --location us-central1 --project guiili          # reprise
```

**Retour arrière = trafic uniquement.** On redirige le trafic vers une révision existante ;
on ne redéploie pas un commit antérieur à ce lot avec le nouveau fichier d'environnement.
Ce code plus ancien exige encore `DATABASE_URL_TEST` et `REDIS_URL` dans ses `Settings` :
il échouerait au démarrage avec le nouveau fichier (qui ne les contient plus). Une
révision existante garde ses propres variables d'environnement, donc rediriger le trafic
vers une ancienne révision fonctionne.

## 6. Lire les logs

En production (et préproduction), chaque événement est une ligne JSON (`severity`,
`message`, `logger`, `time`, `request_id`) que Cloud Logging structure seul. Une ligne
d'accès par requête (logger `app.access`) porte `method`, `path` (le **gabarit** de route tel
qu'observé, relatif au routeur, donc **sans** le préfixe `/api/v1` : par exemple
`/auth/me` ou `/websites/{website_id}/scan`, jamais l'URL brute ; `unmatched` si aucune
route ne correspond), `status` et
`duration_ms`. Il n'y a ni chaîne de requête, ni corps, ni cookie, ni en-tête
d'autorisation dans les logs ; `/health` et `/health/db` ne sont pas journalisés au niveau
INFO. Les logs d'accès de uvicorn sont coupés et `httpx`/`httpcore` sont réduits à
WARNING (leurs URL sortantes contiendraient des clés).

Requêtes à coller dans l'explorateur de journaux de Cloud Logging :

```text
# Erreurs
resource.type="cloud_run_revision" AND severity>=ERROR

# Une requête précise : l'identifiant est dans l'en-tête de réponse x-request-id
jsonPayload.request_id="<id>"

# Lenteurs (plus de 2 secondes)
jsonPayload.duration_ms>2000

# Une route précise (gabarit relatif, sans /api/v1)
jsonPayload.path="/auth/me" AND jsonPayload.status>=400
```

Un client peut fournir son propre `x-request-id` (8 à 64 caractères
`A-Za-z0-9._-`) ; sinon l'identifiant vient de `x-cloud-trace-context` ou est généré.
Une exception non gérée est journalisée en ERROR avec sa trace : **Cloud Error Reporting**
les regroupe sans configuration.

## 7. Suivi d'erreurs Sentry [PROPRIÉTAIRE, optionnel]

1. **[PROPRIÉTAIRE]** Créer un projet Sentry (plateforme Python / FastAPI).
2. **[PROPRIÉTAIRE]** Copier le DSN dans `SENTRY_DSN` du fichier `deploy/env.<env>.yaml`,
   puis redéployer (`./scripts/deploy-backend.sh <env>`).

Sans DSN (valeur vide, cas par défaut), Sentry est désactivé et rien n'est envoyé.
`SENTRY_TRACES_SAMPLE_RATE` (défaut `0.0`) commande l'échantillonnage des traces.

Ce qui n'est **jamais** envoyé (`backend/app/observability.py`) : corps de requête
(`max_request_body_size="never"`), cookies, en-têtes, chaîne de requête, variables
locales, données personnelles (`send_default_pii=False`). En plus, chaque événement et
chaque transaction passent par un nettoyage : clés sensibles (`code`, `state`, `key`,
`password`, `secret`, `token`, `authorization`, `cookie`, `api_key`, `refresh`,
`*query`, `*fragment`) remplacées par `[Filtered]`, chaîne de requête des URL retirée des
messages, valeurs d'exception et spans. La révision Cloud Run (`K_REVISION`) sert de
`release`.

## 8. Limites de débit

Limiteur en mémoire à fenêtre glissante (`backend/app/security/rate_limit.py`). Au
dépassement : réponse HTTP 429 « trop de tentatives, réessaie dans quelques instants »
avec un en-tête `Retry-After`. Les chemins ci-dessous sont relatifs à `/api/v1`.

| Route | Clé | Limite |
|---|---|---|
| `POST /auth/login` | IP | 30 requêtes / 15 min |
| `POST /auth/login` | e-mail | 10 échecs / 15 min (seuls les échecs comptent) |
| `POST /auth/register` | IP | 10 / heure |
| `POST /auth/password-reset/request` | IP | 20 / heure |
| `POST /auth/password-reset/request` | e-mail | 5 / heure |
| `GET /auth/google/start` | IP | 30 / 10 min |
| `GET /auth/google/callback` | IP | 60 / 10 min |
| `GET /connections/google/start` | IP | 30 / 10 min |
| `POST /websites` (création de site) | utilisateur | 20 / heure |
| `POST /websites/{id}/scan` | utilisateur | 10 / min |
| `POST /websites/{id}/gtm/headless` | utilisateur | 3 / 10 min |
| `POST /websites/{id}/advisor/brief` | utilisateur | 5 / min |
| `POST /advisor/threads/{id}/messages` | utilisateur | 20 / min |
| `GET /websites/{id}/metrics/series` | utilisateur | 120 / min |
| `GET /websites/{id}/schedules` | utilisateur | 120 / min |
| `PUT /websites/{id}/schedules` | utilisateur | 30 / min |

En plus, le conseiller applique des plafonds quotidiens configurables :
`ADVISOR_DAILY_BRIEF_CAP` (5 briefs par jour) et `ADVISOR_DAILY_MESSAGE_CAP` (40 messages
par jour).

`RATE_LIMIT_ENABLED` (défaut `true`) désactive tout le limiteur quand il vaut `false` ;
à réserver aux tests et au diagnostic, jamais à la production.

**La limite est par instance** : l'état est en mémoire du processus. Avec `--max-instances
3`, la limite effective peut être jusqu'à trois fois supérieure, et elle repart de zéro
à chaque nouvelle instance ; c'est suffisant contre la force brute et les boucles
clientes. Les compteurs par IP et ceux par e-mail ou utilisateur sont dans deux stockages
distincts : une inondation d'IP forgées qui sature le premier ne remet pas à zéro les
verrous de connexion par e-mail.

**L'IP n'est pas fiable.** `X-Forwarded-For` est pris tel quel (premier maillon, meilleur
effort). Quiconque appelle directement l'URL publique `*.run.app` (sans passer par le
proxy Vercel) choisit lui-même cet en-tête : la clé par IP est alors **forgeable** et
contournable. La clé par e-mail / utilisateur est le frein fiable.

L'inverse est un risque de disponibilité : si le rewrite Vercel ne relaie pas l'IP du
vrai client, tous les utilisateurs partagent les IP de sortie de Vercel, et les limites
par IP (inscription 10/h, connexion 30/15 min, démarrage OAuth 30/10 min, par instance)
deviennent une panne d'inscription.

**[PROPRIÉTAIRE] Avant le premier déploiement de production**, en préproduction :
inspecter la forme brute de l'en-tête `X-Forwarded-For` reçu par le backend à travers le
rewrite Vercel (par exemple en le journalisant temporairement, ou en appelant une route
qui l'affiche) et vérifier que Vercel transmet bien l'IP du vrai client. Si ce n'est pas
le cas, un réglage `TRUSTED_PROXY_HOPS` (nombre de proxys de confiance dont on saute les
maillons à droite de l'en-tête) sera nécessaire : **il n'est pas implémenté**, à traiter
avant d'ouvrir les inscriptions.

## 9. Protection de la branche `main` [PROPRIÉTAIRE]

À régler dans GitHub (Settings, Branches, règle sur `main`) :

- **[PROPRIÉTAIRE]** exiger les contrôles de la CI (`.github/workflows/ci.yml`) : les
  jobs `backend` et `frontend` ;
- **[PROPRIÉTAIRE]** exiger une pull request avant fusion ;
- **[PROPRIÉTAIRE]** interdire le push forcé (et la suppression de la branche).

La CI s'exécute sur chaque pull request et à chaque push sur `main` : backend (Postgres
16, `ruff check`, `alembic upgrade head` puis `alembic check`, `pytest -W error`) et
frontend (`npm ci`, `npm run lint`, `npm run build`). Dependabot surveille les
dépendances uv, npm et les actions GitHub.

## 10. Secrets

**État actuel** : les secrets (`APP_SECRET_KEY`, `TOKEN_ENC_KEYS`, `GOOGLE_CLIENT_SECRET`,
`ANTHROPIC_API_KEY`, `DATABASE_URL`, `PAGESPEED_API_KEY`) sont des **variables
d'environnement en clair** du service Cloud Run, alimentées par le fichier
`deploy/env.<env>.yaml` (jamais versionné, mode 600). Secret Manager n'est pas activé.

**Prochaine étape recommandée [PROPRIÉTAIRE]** :

1. `gcloud services enable secretmanager.googleapis.com --project guiili` ;
2. créer un secret par valeur sensible (`APP_SECRET_KEY`, `TOKEN_ENC_KEYS`,
   `GOOGLE_CLIENT_SECRET`, `ANTHROPIC_API_KEY`, `DATABASE_URL`) et donner au compte de
   service d'exécution de Cloud Run le rôle `Secret Manager Secret Accessor` ;
3. passer à `--set-secrets` dans `scripts/deploy-backend.sh` (les variables concernées
   quittent alors le fichier d'environnement).

Ce changement n'est pas fait dans le lot 0.

**Rotation** :

- `APP_SECRET_KEY` : la changer invalide les sessions, donc **déconnecte tous les
  utilisateurs**. À faire hors heures d'usage.
- Clés de chiffrement des jetons Google : versionnées. `TOKEN_ENC_KEYS` est un JSON
  `{"<version>": "<clé base64 de 32 octets>"}` et `TOKEN_ENC_ACTIVE_VERSION` désigne la
  version utilisée pour chiffrer. Pour faire tourner : ajouter une nouvelle version dans
  `TOKEN_ENC_KEYS` **en gardant les anciennes** (pour continuer à déchiffrer), passer
  `TOKEN_ENC_ACTIVE_VERSION` à la nouvelle, déployer.
- Un secret exposé : le renouveler chez le fournisseur (Google, Anthropic, Neon, Sentry),
  mettre à jour le fichier d'environnement, redéployer.

## 11. Déploiement continu vers la préproduction [PROPRIÉTAIRE]

`.github/workflows/deploy-staging.yml` déploie la préproduction **à la demande**
(`workflow_dispatch` uniquement : jamais automatiquement, jamais vers la production). Il
utilise l'environnement GitHub `staging`, un seul déploiement à la fois
(`concurrency: deploy-staging`), et appelle `./scripts/deploy-backend.sh staging`.

Prérequis, tous **[PROPRIÉTAIRE]** :

1. Workload Identity Federation entre GitHub et GCP (pool et fournisseur d'identité
   limités au dépôt `Jk3ndo/Guiili`).
2. Un compte de service avec les rôles Cloud Run Admin, Cloud Build Editor, Service
   Account User et Artifact Registry Writer, et, pour le lot B, le rôle Service Account
   User sur le compte de service du worker (`backend-guiili-staging-worker@…`), sans quoi
   le déploiement du worker échoue.
3. Un environnement GitHub `staging` (Settings, Environments) contenant les secrets :
   - `GCP_WORKLOAD_IDENTITY_PROVIDER` : nom complet du fournisseur d'identité ;
   - `GCP_SERVICE_ACCOUNT` : adresse du compte de service ;
   - `STAGING_ENV_YAML` : contenu **complet** de `deploy/env.staging.yaml`, variables du
     lot B comprises (sans elles, la deuxième vérification de l'étape 1 refuse le
     déploiement).
4. La préproduction existe déjà (§4).
5. Recommandé : restreindre l'environnement GitHub `staging` aux branches de déploiement
   autorisées (Settings, Environments, Deployment branches, par exemple `main`
   seulement). Sans cela, un workflow manuel peut être lancé depuis n'importe quelle
   branche et recevrait les secrets de l'environnement.

Le workflow écrit `STAGING_ENV_YAML` dans `deploy/env.staging.yaml` (mode 600) sur le
runner, installe le venv (`uv sync --frozen`, nécessaire à `check_env`) et lance le
script de déploiement : mêmes cinq étapes qu'en local. Aucun secret n'est écrit dans le
workflow lui-même.

## 12. Incidents

Liste de contrôle, dans l'ordre :

1. **La base répond-elle ?** `curl -fsS <URL_DU_SERVICE>/health/db` : `{"database":"ok"}`
   attendu, 503 `{"database":"error"}` sinon (Neon suspendu, quota, mauvais
   `DATABASE_URL`). `/health` ne teste que le processus.
2. **Dernière migration** : `gcloud run jobs executions list --job backend-guiili-migrate
   --region us-central1 --project guiili` (une exécution en échec signifie que le service
   n'a pas été mis à jour lors du dernier déploiement).
3. **Erreurs applicatives** : requête d'erreurs du §6, puis Cloud Error Reporting et
   Sentry si activé.
4. **Quota Google ou PageSpeed** : sans `PAGESPEED_API_KEY`, l'appel PageSpeed est
   « keyless » à quota public limité et retombe en mode dégradé (scores CWV à 0). Une
   limite GA4 / Search Console dégrade la sonde correspondante sans casser l'audit.
5. **Jeton Google révoqué** : la connexion de données passe à l'état `needs_reauth` ;
   l'utilisateur doit reconnecter son compte Google depuis l'application.
6. **429 en rafale** : voir §8 ; identifier la clé (IP ou utilisateur) dans les logs
   d'accès.
7. **Quelle révision reçoit le trafic ?** Après un retour arrière, le trafic peut rester
   épinglé sur une ancienne révision et un déploiement récent ne serait pas en ligne :
   `gcloud run services describe backend-guiili --region us-central1 --project guiili
   --format="value(status.traffic)"`. Si besoin, `--to-latest` (voir §5).
8. **Retour arrière** : §5, si le problème vient de la dernière révision.
9. **Contacter** : le propriétaire du projet GCP `guiili` et, pour la base, le
   propriétaire du projet Neon ; noter l'heure, le `x-request-id` d'une requête en échec
   et la révision Cloud Run en cours.
10. **Collectes en échec ou en retard** : `GET <WORKER_URL>/internal/jobs/health` avec
    `-H "Authorization: Bearer $TOKEN"`, le jeton s'obtenant comme au §15.3 (emprunt
    d'identité du compte de service `guiili-scheduler`, qui figure dans
    `INTERNAL_ALLOWED_INVOKERS`), puis §15.5.
11. **Quota Google atteint en boucle** : le disjoncteur suspend 30 minutes la source d'un
    workspace après 3 échecs `quota` ; vérifier le débit de la file (`gcloud tasks queues
    describe guiili-ga4 ...`, `guiili-staging-ga4` en préproduction) avant de l'augmenter.

## 13. Hors périmètre du lot 0

Renvoi vers la spec `docs/superpowers/specs/2026-09-25-roadmap-v3-architecture-design.md` :

- séparation des services `api` / `worker` : faite au lot B (§15) ;
- Secret Manager effectif (le §10 décrit seulement la marche à suivre) ;
- export et suppression RGPD d'un workspace ;
- sécurité au niveau des lignes de Postgres (RLS), évaluée après l'isolation applicative ;
- limiteur de débit partagé entre instances (aujourd'hui par instance, §8).

## 14. Validation du conteneur GTM du plan de mesure [PROPRIÉTAIRE]

Le conteneur GTM généré par le plan de mesure (« Générer mon pack de démarrage ») n'a
jamais été importé dans un vrai GTM : ne le propose pas aux utilisateurs avant la
procédure décrite dans `docs/ops/gtm-container-import-check.md` (fichier d'exemple :
`docs/ops/gtm-sample-container.json`).

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

Comportement des tentatives (à connaître avant de modifier une file) :

- `max-attempts` de chaque file vaut 5. Les réponses « occupé » (`busy`), « ralenti »
  (`throttled`) et les 503 ne consomment pas de tentative côté `job_runs` : elles ne sont
  bornées que par la limite de la file.
- Une erreur définitive (422, corps de tâche invalide) est elle aussi rejouée par la file
  jusqu'à sa limite de 5 tentatives, puis abandonnée : ce n'est pas un bogue, c'est le
  comportement de Cloud Tasks pour toute réponse non 2xx.
- Cloud Tasks réserve le nom d'une tâche pendant environ une heure après son exécution ou
  sa suppression. Pour relancer à la main une exécution déjà passée, changer la
  fenêtre (`window`) de la clé d'idempotence ; redéposer la même clé dans l'heure serait
  refusé (nom de tâche déjà réservé).
- Le bail (`JOBS_LEASE_SECONDS`, 900) est égal au délai de requête du worker et au
  `dispatchDeadline` des tâches (voir §2) : ne jamais le réduire sous le délai de requête.

### 15.2 Mise en place unique [PROPRIÉTAIRE]

Exemple pour la production ; les noms de préproduction sont donnés ci-dessous et ne suivent
PAS une règle de suffixe uniforme (le code construit `{CLOUD_TASKS_QUEUE_PREFIX}-{file}` et
le script déploie `backend-guiili-staging-worker`) :

| Objet | Production | Préproduction |
|---|---|---|
| Service worker | `backend-guiili-worker` | `backend-guiili-staging-worker` |
| Compte du worker | `backend-guiili-worker` | `backend-guiili-staging-worker` |
| Compte Cloud Tasks | `guiili-tasks` | `guiili-tasks-staging` |
| Compte Cloud Scheduler | `guiili-scheduler` | `guiili-scheduler-staging` |
| Préfixe des files (`CLOUD_TASKS_QUEUE_PREFIX`) | `guiili` | `guiili-staging` |
| Files | `guiili-{ga4,gsc,cwv,light,heavy}` | `guiili-staging-{ga4,gsc,cwv,light,heavy}` |
| Job Cloud Scheduler | `guiili-tick` | `guiili-tick-staging` |

Remplacer `<NUM>` par le numéro du projet
(`gcloud projects describe guiili --format='value(projectNumber)'`) : l'URL du worker est
alors `https://backend-guiili-worker-<NUM>.us-central1.run.app` (préproduction :
`https://backend-guiili-staging-worker-<NUM>.us-central1.run.app`, à utiliser aussi comme
URI et audience du job `guiili-tick-staging`). **Les `<NUM>` et `<COMPTE_DE_L_API>` des
commandes ci-dessous sont à remplacer AVANT de les exécuter** (sinon l'URL est invalide).
Les boucles supposent bash (`set -- $spec` ne découpe pas la chaîne sous zsh). Rien de ceci
n'est exécuté par l'outillage du dépôt.

```bash
# 1. API Google Cloud
gcloud services enable cloudtasks.googleapis.com cloudscheduler.googleapis.com \
  iamcredentials.googleapis.com --project guiili

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

# 4. Le worker dépose des tâches et les signe au nom de guiili-tasks. Le rôle
#    enqueuer est donné PAR FILE, jamais au niveau du projet (sinon les workers de
#    préproduction et de production pourraient déposer dans les files l'un de l'autre).
for queue in ga4 gsc cwv light heavy; do
  gcloud tasks queues add-iam-policy-binding "guiili-$queue" \
    --location us-central1 --project guiili \
    --member serviceAccount:backend-guiili-worker@guiili.iam.gserviceaccount.com \
    --role roles/cloudtasks.enqueuer
done
gcloud iam service-accounts add-iam-policy-binding guiili-tasks@guiili.iam.gserviceaccount.com \
  --member serviceAccount:backend-guiili-worker@guiili.iam.gserviceaccount.com \
  --role roles/iam.serviceAccountUser

# 4bis. Le propriétaire peut émettre un jeton au nom de guiili-scheduler (contrôles du §15.3)
gcloud iam service-accounts add-iam-policy-binding guiili-scheduler@guiili.iam.gserviceaccount.com \
  --member user:<EMAIL_DU_PROPRIETAIRE> --role roles/iam.serviceAccountTokenCreator
```

5. Compléter `deploy/env.production.yaml` avec les variables du lot B (§1) :
   `WORKER_BASE_URL` et `INTERNAL_OIDC_AUDIENCE` =
   `https://backend-guiili-worker-<NUM>.us-central1.run.app`,
   `TASKS_INVOKER_SERVICE_ACCOUNT` = `guiili-tasks@guiili.iam.gserviceaccount.com`,
   `INTERNAL_ALLOWED_INVOKERS` = les e-mails de `guiili-tasks`, `guiili-scheduler` et du
   compte d'exécution de l'API : le script déploie l'API sans `--service-account`, c'est
   donc le compte par défaut de Compute Engine, `<NUM>-compute@developer.gserviceaccount.com`
   (à confirmer par `gcloud run services describe backend-guiili --format='value(spec.template.spec.serviceAccountName)'`).
   Le fichier reste en clair comme au §10 : Secret Manager n'est pas dans le périmètre du
   lot B ([PROPRIÉTAIRE], §10).
6. Déployer : `./scripts/deploy-backend.sh production --dry-run`, puis sans `--dry-run`
   (le premier passage crée le service worker et applique les deux migrations du lot B
   par le Job de migration). Les partitions futures de `metric_points` sont créées par la
   tâche planifiée `partition_maintenance` : tant qu'elle n'a pas tourné, les lignes d'un
   mois sans partition atterrissent dans la partition par défaut (toléré, la
   maintenance les traite ensuite).

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
    échec ou en retard » si `SENTRY_DSN` est réglé (à renseigner en production, §7).

Le compte de service d'exécution de l'API doit pouvoir invoquer le worker (étape 7) : sans
cela, le bouton « Vérifier en conditions réelles » de `/audit` renvoie une erreur gérée
côté interface. Le worker est **privé** : ne jamais lui donner `allUsers` ni
`--allow-unauthenticated`.

### 15.3 Vérifier que tout tourne

```bash
WORKER_URL=https://backend-guiili-worker-<NUM>.us-central1.run.app
# Jeton d'identité au nom de guiili-scheduler (--audiences est refusé pour un compte
# utilisateur, --include-email est nécessaire pour que le jeton porte l'e-mail vérifié)
TOKEN=$(gcloud auth print-identity-token \
  --impersonate-service-account=guiili-scheduler@guiili.iam.gserviceaccount.com \
  --audiences="$WORKER_URL" --include-email)
curl -fsS -H "Authorization: Bearer $TOKEN" "$WORKER_URL/internal/jobs/health"
gcloud scheduler jobs run guiili-tick --location us-central1 --project guiili   # passage immédiat
```

Prérequis : le propriétaire a `roles/iam.serviceAccountTokenCreator` sur
`guiili-scheduler` (étape 4bis) et l'API `iamcredentials.googleapis.com` est activée
(étape 1). Le compte dont on emprunte l'identité (`guiili-scheduler`) figure dans
`INTERNAL_ALLOWED_INVOKERS` (sinon 403) et a `roles/run.invoker` sur le worker (étape 7) ;
l'e-mail personnel du propriétaire, lui, n'y figure pas. Sans `--audiences`, l'audience du
jeton serait fausse (403) ; sans `--include-email`, le jeton n'a ni `email` ni
`email_verified`. En préproduction : compte `guiili-scheduler-staging`, URL du worker de
préproduction et job `guiili-tick-staging`.

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
# Plafond quotidien de tâches atteint pour un workspace
jsonPayload.event="job_daily_cap_reached"
# Bail perdu : l'exécution a été reprise ailleurs, l'ancienne est ignorée
jsonPayload.event="job_lease_lost"
# Passage du planificateur en échec (Cloud Scheduler retentera au passage suivant)
jsonPayload.event="tick_failed"
# Vérification headless trop longue (503, la file ou l'utilisateur réessaie)
jsonPayload.event="headless_timeout"
# Exécution de tâche en échec inattendu côté base (503, la file réessaie)
jsonPayload.event="task_run_failed"
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
