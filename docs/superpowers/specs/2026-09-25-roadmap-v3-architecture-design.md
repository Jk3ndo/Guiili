# Feuille de route v3 et architecture de production

Remplace `2026-09-24-roadmap-v2.md` pour l'ordre des lots et l'architecture. Les
décisions produit de la v2 restent valables sauf mention contraire. Les faits sur
Amplitude et Matomo sont dans `2026-09-25-benchmark-amplitude-matomo.md`.

## 1. Objet

Devenir la référence du **copilote de mesure et de performance** pour les
propriétaires de sites : analytics, SEO, Core Web Vitals, tracking de conversions,
publicité. Atteindre puis dépasser la profondeur d'Amplitude (analyse
comportementale, IA) et de Matomo (données souveraines, non échantillonnées,
Tag Manager) sans perdre notre avantage propre : **vérifier, installer et corriger**
là où eux se contentent de collecter et d'afficher.

Contraintes de fond : architecture prête pour la production, multi-clients dès le
départ, qualité de l'analyse des données comme critère principal.

## 2. Décisions actées

Reprises de la v2 :
- Bêta fermée d'abord ; vérification OAuth Google lancée en parallèle.
- Google en lecture seule tant que la vérification n'est pas obtenue.
- Google Ads sans API au départ.
- L'IA explique, le code décide : aucun statut ni criticité ne dépend d'un modèle
  de langage.
- Interface en français.

Nouvelles (2026-09-25) :
- **Stratégie de collecte :** socle de données d'abord (sources Google, sondes),
  puis un pixel first-party comme source supplémentaire. Ni moteur d'analytics
  complet maintenant, ni dépendance définitive aux seules données Google.
- **Prise en main en paliers** (section 7), avec de la valeur à chaque palier.
- **Loader Guiili** (installation en une ligne) en début du lot F, pas avant.
- **Production d'abord :** un lot 0 court précède tout le reste.

## 3. Architecture cible

Principe : toute donnée entre par une abstraction `MetricSource`.

```
Sources (adaptateurs)         Exécution                  Stockage               Lecture
GA4 Data / Admin       ┐                                 ┌ metric_points        ┌ API séries temporelles
Search Console         │  Cloud Scheduler                │ metric_rollups       │ tableau de bord multi-sites
PageSpeed / CrUX       ├─►  → /internal/tick  ─► Cloud   ├ measurement_*        ├ rapports et alertes
Sondes (HTML, TLS,     │     (OIDC)            Tasks ──► ├ issue_items (étendu) ├ conseiller et outils
headless, robots)      │                       (par     │ schedules, job_runs  └ serveur MCP (plus tard)
[plus tard] Pixel,     ┘                       source)   └ audit_snapshots (preuves brutes)
Google Ads, imports                              │
                                                 ▼
                                         service worker (image dédiée, Chromium)
```

- **Source :** interface `MetricSource.collect(website, day_range) -> list[Observation]`.
  Chaque source déclare ses quotas, sa fraîcheur, ses dimensions permises et ses
  erreurs récupérables. Une observation est `(site, source, métrique, dimensions,
  jour, valeur)`. Rejouer un jour est idempotent.
- **Stockage :** Postgres (Neon) porte tout l'agrégé, ce qui suffit car GA4, Search
  Console et CWV sont des données journalières. Les événements bruts du pixel
  (lot F) iront dans un moteur colonne (ClickHouse ou BigQuery, choix repoussé au
  lot F) ; le contrat de lecture `metric_points` ne change pas.
- **Exécution :** Cloud Scheduler appelle un point d'entrée interne authentifié
  par OIDC ; il sélectionne les tâches dues et les dépose dans Cloud Tasks, qui
  gère les nouvelles tentatives, le backoff et le débit par source (quotas Google).
  Le service `worker` les exécute. Cloud Run ne calcule pas hors requête, d'où ce
  schéma.
- **Lecture :** une API de séries temporelles unique (métrique, période,
  comparaison, granularité) lit des cumuls pré-calculés. Tableau de bord, rapports
  et conseiller lisent tous la même couche.
- **Isolation des clients :** chaque table porte `workspace_id` ; les lectures
  passent par une couche cadrée par workspace ; une suite de tests d'isolation
  tente l'accès inter-clients sur chaque route.

## 4. Modèle de données

Existant conservé : `audit_snapshots` (blob JSONB par capture, preuve brute) et
`issue_items` (dédupliqué par `fingerprint`).

Nouvelles tables :

| Table | Rôle |
|---|---|
| `metric_points` | Série temporelle étroite : `(website_id, source, metric, dim_key, day) -> value`, clé primaire sur ces cinq colonnes (idempotence), `dims` JSONB, `collected_at`, `run_id`. Partitionnée par mois. Dimensions à forte cardinalité (requêtes et pages Search Console) plafonnées à un top N par jour. |
| `metric_rollups` | Cumuls semaine et mois écrits après chaque collecte ; lus par le tableau de bord. |
| `measurement_item_events` | Historique des changements d'état des items du plan de mesure (`website_id, item_id, from_state, to_state, at, evidence`). |
| `schedules` | Par site et type de tâche : fréquence choisie, prochaine échéance, dernier passage. |
| `job_runs` | Une ligne par exécution : clé d'idempotence, bail, statut, durée, erreur. Source des alertes d'exploitation. |

Un **registre de métriques en code** déclare, pour chaque métrique : unité, sens
d'amélioration, dimensions permises, source, seuils d'anomalie.

Extension de `issue_items`, qui devient le registre unique des constats :
`rule_code` stable, `last_seen_at`, `impact_score` calculé par le code, `evidence`
JSONB. La criticité (critique, haute, moyenne, basse) découle de la règle et de
l'impact. Un constat absent d'un scan devient automatiquement « résolu ».

Rétention : points journaliers 25 mois (comparaison annuelle), cumuls sans limite.
Isolation : `workspace_id` reste porté par `websites` ; les tables filles s'y
rattachent par `website_id`.

## 5. Exécution et planification

- `schedules` porte la fréquence choisie par l'utilisateur : toutes les heures,
  3 fois par jour, quotidienne, tous les 3 jours ou hebdomadaire. Plancher :
  8 heures pour les sources à quota (Search Console, GA4), 1 heure pour les
  sondes légères.
- Chaque tâche a une clé d'idempotence `(site, type, fenêtre)` et un bail ; un
  worker qui meurt libère son bail à l'expiration.
- Limites par workspace (tâches simultanées et par jour) pour qu'un gros client
  n'épuise pas les quotas des autres.
- Tâches lourdes (navigateur headless, futur crawler) : file dédiée, une à la fois,
  sur le service `worker` uniquement.

## 6. Production : robustesse, sécurité, exploitation

État constaté : pas de CI ; déploiement manuel par `gcloud run deploy --source` ;
migrations exécutées à chaque démarrage de conteneur (risque de course entre
instances) ; Chromium embarqué dans l'image de l'API ; ni logs structurés, ni suivi
d'erreurs, ni limitation de débit.

Mesures (lot 0, sauf mention) :
1. **CI/CD :** GitHub Actions (tests, lint, build, `alembic check`) à chaque PR,
   déploiement automatique en préproduction, promotion manuelle en production.
2. **Migrations hors démarrage :** Cloud Run Job exécuté avant chaque déploiement ;
   le conteneur ne migre plus.
3. **Deux services, deux images :** `api` léger ; `worker` avec Chromium (lot B
   pour la séparation effective, l'image API allégée dès le lot 0 si possible).
4. **Isolation :** couche de requêtes cadrée par workspace et suite de tests
   d'isolation ; sécurité au niveau des lignes de Postgres (RLS) évaluée ensuite.
5. **Limitation de débit** par IP et par workspace sur l'API.
6. **Observabilité :** logs JSON avec identifiant de trace, suivi d'erreurs
   (Sentry), métriques de tâches, alerte sur `job_runs` en échec ou en retard
   (une collecte en échec depuis plus de 24 h doit être vue par nous avant le client).
7. **Secrets et conformité :** Secret Manager, journal d'audit des actions
   sensibles, procédures d'export et de suppression d'un workspace (RGPD).
8. **Résilience :** sauvegardes Neon avec test de restauration, mode dégradé quand
   une source est indisponible, disjoncteur par connexion Google.

Hors périmètre : Kubernetes, bus de messages maison, multi-région.

## 7. Prise en main en paliers

Diagnostic : le parcours actuel demande six décisions avant toute valeur au-delà
de l'audit public. Principe : ne jamais demander ce qu'on peut détecter ; repousser
la configuration intense après les premiers résultats.

| Palier | Durée cible | Action de l'utilisateur | Valeur obtenue |
|---|---|---|---|
| 1 | ~1 min | Saisir son domaine | Audit public immédiat (stack, GTM, GA4, CWV, robots, TLS) et « tes 3 prochaines actions » |
| 2 | ~2 min | Un clic sur « Connecter Google » | Liaison **automatique** de la propriété GA4 et du site Search Console qui correspondent au domaine (question posée seulement si ambigu) ; vraies données ; lignes du plan qui passent à « Reçu par GA4 » |
| 3 | ~5 min | Importer un fichier | **Pack de démarrage** pré-choisi selon le type de site : un conteneur GTM avec GA4 et les événements essentiels, sans case à cocher ; vérification automatique jusqu'au passage au vert |
| Ensuite | à la demande | Rien d'obligatoire | Reste du catalogue, Ads, consentement, agent PR, repliés sous « Pour aller plus loin » et proposés quand la donnée les justifie |

Le **Loader Guiili** (une ligne à coller, GA4 préconfiguré, événements
automatiques selon le type de site, santé des balises et CWV des vrais visiteurs
renvoyés à Guiili) est traité au début du lot F, car il dépend du socle de données.
Il respectera le consentement, ne collectera aucune donnée personnelle et laissera
les données dans le GA4 de l'utilisateur.

## 8. Feuille de route

| Lot | Contenu | Dépend de |
|---|---|---|
| **0. Socle de production** | CI/CD, migrations hors démarrage, tests d'isolation entre clients, logs structurés, suivi d'erreurs, limitation de débit, préproduction | rien |
| **A. Plan de mesure guidé** | Spécifié et planifié ; ajusté (section 9) : prise en main en paliers, auto-liaison Google, pack de démarrage, historique des statuts | 0 |
| **B. Socle de données et suivi planifié** | `MetricSource`, `metric_points`, cumuls, `schedules`, `job_runs`, service `worker`, alertes, rapports périodiques | 0, A |
| **C. Tableau de bord multi-projets** | KPIs évolutifs sur tous les sites, comparaisons, annotations ; ensuite serveur MCP en lecture seule | B |
| **D. SEO** | Search Console en profondeur (indexation, opportunités de clic, pages en déclin, cannibalisation), crawler technique maison (liens cassés, canonicals, hreflang, balises, données structurées), CWV par groupe d'URL, tout classé par criticité et impact | B |
| **E. Agent PR** | GitHub App (puis GitLab), PR uniquement, galerie des diffs avec points clés | A ; C et D pour cibler |
| **F. Pixel first-party et analytique comportementale** | Loader Guiili, collecteur sans cookie hébergé en UE, stockage colonne, entonnoirs, cohortes, rétention, parcours ; heatmaps et replays ensuite | B, C |
| **G. Configuration Google en écriture** | Écriture GA4 et GTM, API Ads | Vérification Google, developer token |

Ordre : 0, A, B, puis C et D, puis E, puis F, puis G. Chaque lot suit le cycle
spec, plan, exécution par sous-agents avec revue par tâche, revue finale de
branche, et aucun merge, push ni déploiement sans accord explicite.

Hors horizon actuel : expérimentation, guides et enquêtes, activation vers les
régies publicitaires. Ils exigent le pixel et n'apportent rien au copilote tant
que la collecte n'existe pas.

## 9. Ajustements au lot A

1. **Historique :** la Tâche 1 ajoute `measurement_item_events` ; le service
   d'actualisation écrit une ligne à chaque changement d'état d'un item.
2. **Auto-liaison Google :** nouveau service qui, après une connexion de données,
   fait correspondre le domaine d'un site à un site Search Console (`sc-domain:` ou
   préfixe d'URL, avec ou sans `www`) et à une propriété GA4 (flux web dont l'hôte
   correspond), et crée la liaison quand la correspondance est unique.
3. **Prochaines actions :** la vue du plan expose `next_actions` (trois items les
   plus prioritaires non faits, gains rapides en premier) ; l'interface les affiche
   avant la liste complète.
4. **Type de site appliqué d'office :** le type détecté est utilisé tout de suite ;
   un bandeau non bloquant permet de le corriger (la carte de confirmation
   obligatoire disparaît).
5. **Couche Ads masquée par défaut :** elle ne s'applique que si l'utilisateur
   indique faire de la publicité Google Ads.
6. **Pack de démarrage :** le conteneur se génère en un clic à partir d'une
   sélection recommandée par type de site ; la sélection manuelle des lignes passe
   en option avancée.
7. **« Pour aller plus loin » :** les items hors prochaines actions sont repliés.
8. **Vérification automatique :** dans le lot A, les vérifications légères se
   relancent à l'ouverture de la page si la dernière date de plus de 5 minutes ;
   la relance planifiée arrive avec le lot B.

## 10. Risques et points à trancher plus tard

- **Quotas Google :** GA4 et Search Console limitent le débit ; le planificateur
  et les files par source sont la parade, à valider en charge réelle.
- **Auto-liaison ambiguë :** plusieurs propriétés ou sites pour un même domaine ;
  règle retenue : ne lier que si le choix est unique, sinon demander.
- **Loader (lot F) :** revue de sécurité, consentement, hébergement et disponibilité
  du script ; à cadrer dans sa propre spec.
- **Moteur colonne (lot F) :** ClickHouse ou BigQuery, choisi sur coût et exploitation.
- **Facturation et quotas par plan,** fournisseur d'e-mail réel pour les rapports,
  politique de confidentialité et dossier de vérification Google : inchangés (v2).
- **Plugin WordPress** pour les utilisateurs non techniques : idée à évaluer après
  le lot E.
