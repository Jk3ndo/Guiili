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

1. **Vérification du fichier d'environnement** :
   `python -m app.tools.check_env deploy/env.<env>.yaml --expect <env>` (mêmes règles que
   le démarrage du service, plus les variables obligatoires). Aucune valeur du fichier
   n'est affichée, seulement des noms de variables et des messages. Cette étape est
   exécutée même avec `--dry-run`. Trois contrôles s'y ajoutent :
   `--expect` refuse un fichier dont `ENVIRONMENT` est absent (il vaudrait `local` et
   toutes les règles de production seraient sautées) ou différent de la cible ;
   `TOKEN_ENC_KEYS` est chargé comme le fait l'API (JSON, base64 valide, 32 octets par
   clé, version active présente) ; toute valeur non textuelle (`true`, `42`, `null` sans
   guillemets) est refusée, car `gcloud --env-vars-file` n'accepte que des chaînes.
2. **Construction de l'image** : `gcloud builds submit backend --tag
   <région>-docker.pkg.dev/<projet>/cloud-run-source-deploy/<service>:<sha-court>`.
3. **Migrations** : déploie puis exécute immédiatement le Cloud Run Job
   `<service>-migrate` (`backend-guiili-migrate` en production,
   `backend-guiili-staging-migrate` en préproduction) avec la commande
   `alembic upgrade head`, `--max-retries 0`, délai de 10 minutes, `--wait`. **Un échec de
   migration arrête tout avant de toucher au service** : l'ancienne révision continue de
   servir. Le conteneur du service n'exécute plus les migrations au démarrage.
4. **Déploiement du service** : `gcloud run deploy <service>` avec la même image,
   512 Mi, 1 CPU, `--cpu-boost`, 3 instances maximum, `--allow-unauthenticated`.
5. **Vérification** : lit l'URL du service et appelle `GET /health/db` jusqu'à 5 fois
   (5 secondes d'écart). En cas d'échec, le script sort en erreur et affiche la commande de
   retour arrière (voir §5). Non exécutée avec `--dry-run`.

**Attention après un retour arrière (§5)** : si le trafic a été épinglé sur une ancienne
révision, `gcloud run deploy` crée la nouvelle révision **sans lui envoyer de trafic**.
Le contrôle final de `/health/db` interroge l'URL du service, qui sert encore l'ancienne
révision : le « OK » du script ne prouve donc pas que le nouveau code est en ligne. Pour
reprendre les déploiements normaux :

```bash
gcloud run services update-traffic backend-guiili --to-latest --region us-central1 --project guiili
```

**Exposition** : le script passe **toujours** `--allow-unauthenticated`. Le service de
préproduction est donc joignable publiquement : utiliser une URL de service non devinable,
des secrets différents de la production et `ADVISOR_MOCK: "true"`.

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
   Account User et Artifact Registry Writer.
3. Un environnement GitHub `staging` (Settings, Environments) contenant les secrets :
   - `GCP_WORKLOAD_IDENTITY_PROVIDER` : nom complet du fournisseur d'identité ;
   - `GCP_SERVICE_ACCOUNT` : adresse du compte de service ;
   - `STAGING_ENV_YAML` : contenu **complet** de `deploy/env.staging.yaml`.
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

## 13. Hors périmètre du lot 0

Renvoi vers la spec `docs/superpowers/specs/2026-09-25-roadmap-v3-architecture-design.md` :

- séparation des services `api` / `worker` et image API allégée sans Chromium (lot B) ;
  aujourd'hui une seule image, avec Chromium pour la vérification GTM headless ;
- Secret Manager effectif (le §10 décrit seulement la marche à suivre) ;
- export et suppression RGPD d'un workspace ;
- sécurité au niveau des lignes de Postgres (RLS), évaluée après l'isolation applicative ;
- limiteur de débit partagé entre instances (aujourd'hui par instance, §8).

## 14. Validation du conteneur GTM du plan de mesure [PROPRIÉTAIRE]

Le conteneur GTM généré par le plan de mesure (« Générer mon pack de démarrage ») n'a
jamais été importé dans un vrai GTM : ne le propose pas aux utilisateurs avant la
procédure décrite dans `docs/ops/gtm-container-import-check.md` (fichier d'exemple :
`docs/ops/gtm-sample-container.json`).
