# Refonte du plan "Control Center Marketing Agentique" — v3

### Critique technique + architecture OAuth multi-comptes + module d'instrumentation multi-stack

**Contexte retenu :** projet personnel, développement solo à temps partiel, stack Python/FastAPI + Next.js + Claude.

**Décisions actées depuis la v2 (résumé) :**

1. Le MVP reste **100% lecture seule** côté Google APIs (`analytics.readonly`, `webmasters.readonly`) — pas de scope restreint, pas de CASA pour la V1.
2. La "configuration GTM" ne se fait **pas** via écriture live sur l'API : l'agent génère un **fichier JSON importable** via la fonctionnalité native "Import Container" de GTM, que l'utilisateur importe lui-même en quelques secondes. Ça change la donne : ça veut dire qu'on peut délivrer presque toute la valeur de "l'agent qui configure GTM" **sans jamais sortir du scope lecture seule** (voir section 3bis).
3. La rétention du produit ne repose pas sur l'audit ponctuel mais sur le **suivi continu** : historique/backlog de correctifs avec statut, alertes de régression, et benchmark concurrentiel dans le temps.
4. L'instrumentation code (dataLayer.push depuis le code applicatif du client, sur Next.js/WordPress/Angular/Vue/autre) est traitée par un **module de détection de stack + bibliothèque de snippets par framework** — l'agent génère le code exact et son point d'insertion, le développeur du client l'applique lui-même (voir section 6).

---

## 1. Ce qui ne va pas survivre au contact du réel (solo, temps partiel)

Le document de Gemini est un bon brainstorm, mais il a été écrit comme un cahier des charges d'agence pour une équipe de 2 personnes à temps plein. Trois hypothèses cassent tout si on ne les corrige pas maintenant :

**a) Le planning de 12 semaines est basé sur 2 ETP.** Seul et à temps partiel (disons 8-10h/semaine), le même périmètre prend réalistement 6 à 9 mois, pas 3. Ce n'est pas grave en soi, mais il faut le dire clairement pour ne pas se décourager en semaine 12 en constatant qu'on est à 25% du plan.

**b) Le vrai bloqueur n'est pas technique, il est administratif : la vérification Google OAuth.** C'est le point que Gemini n'a pas du tout traité et qui doit piloter tout le phasage (détail en section 3). En résumé : les scopes d'écriture (GTM edit/publish, GA4 edit) sont des scopes "sensibles/restreints" chez Google. Passer en production avec ces scopes pour du grand public déclenche une vérification d'app (identité de marque, ~2-3 jours) et, pour les scopes restreints, un audit de sécurité annuel (CASA) qui peut prendre plusieurs semaines. Tant que l'app reste en mode "Testing" (max 100 utilisateurs test ajoutés manuellement), aucune vérification n'est nécessaire, mais l'app affiche un écran "application non validée" — acceptable pour un cercle de beta-testeurs, invendable au grand public.

→ **Conséquence directe sur le scope du MVP : commencer avec des scopes strictement en lecture seule** (`analytics.readonly`, `webmasters.readonly`, PageSpeed n'a pas besoin d'OAuth utilisateur). Ça évite complètement la case CASA pour la V1, et ça permet de lancer un vrai produit utile (audit + conseils) à un public large sans attendre des semaines de vérification. L'écriture GTM/GA4 (auto-configuration) devient une V2 assumée, lancée seulement quand tu es prêt à entamer le processus de vérification Google.

**c) L'architecture multi-agents LangGraph dès la V1 est une sur-ingénierie.** Un "agent" façon Gemini n'est concrètement qu'un system prompt + un sous-ensemble d'outils (tool use Claude) + un historique de conversation. Tu n'as pas besoin d'un graphe d'orchestration multi-agents pour ça : un seul service Python qui charge une config d'agent (system prompt + liste de tools autorisés) selon le persona sélectionné dans l'UI suffit très largement pour la V1, et c'est le même code pour "4 agents". Réserve LangGraph (ou un simple state machine maison) pour le jour où tu as un vrai besoin d'orchestration asynchrone (ex : l'agent de veille qui tourne en cron et déclenche lui-même une analyse, sans utilisateur dans la boucle) — ça, c'est un vrai cas d'usage multi-agents, pas la sélection d'un persona dans un chat.

---

## 2. Roadmap révisée (solo, temps partiel, ~8-10h/semaine)

| Phase | Contenu | Durée réaliste solo | Scopes Google requis |
|---|---|---|---|
| **P0 — Fondations** | Repo Next.js + FastAPI, DB (Postgres), OAuth Google basique (1 seul type de connexion : lecture), modèle de données comptes/sites | 3-4 semaines | `analytics.readonly`, `webmasters.readonly` |
| **P1 — MVP diagnostic + export** | Dashboard unifié (scores SEO/GA4/CWV via PageSpeed Insights), un seul agent Claude "conseiller" (persona changeable par prompt), détection de stack (Next.js/WordPress/Angular/Vue/autre), génération de snippets dataLayer + export JSON GTM importable | 8-10 semaines | idem (toujours lecture seule) |
| **P2 — Rétention : historique, backlog & alertes** | Journal de bord (snapshots de scores dans le temps + marqueurs sur les graphiques), backlog de correctifs avec statut (à faire/en cours/corrigé), détection d'anomalie *statistique* (moyenne mobile + écart-type, pas de ML), alertes email, benchmark concurrentiel simple | 4-5 semaines | idem |
| **P3 — Lancement beta publique** | Politique de confidentialité, vérification de marque Google (scopes readonly = pas de CASA), ouverture au-delà de 100 users test | 1-2 semaines admin | idem |
| **P4 — Auto-configuration live (optionnelle, pas indispensable)** | Uniquement si, une fois le produit lancé, une vraie demande utilisateur pour du "zéro-clic" apparaît : scopes d'écriture (`tagmanager.edit.containers`, `tagmanager.publish`, `analytics.edit`) en autorisation incrémentale, processus de vérification + CASA, human-in-the-loop obligatoire | Plusieurs semaines de dev + plusieurs semaines d'attente Google | scopes restreints |
| **P5 — Veille & agents avancés** | Agent de veille Google Search Central, vrai multi-agents si un besoin d'orchestration autonome apparaît | Continu | — |

Changement important par rapport à la v2 : grâce à l'export JSON (section 3bis), **P4 n'est plus un passage obligé du plan** — c'est une option premium à activer seulement si la demande existe, une fois que tu as des utilisateurs et des retours réels. Le produit complet (diagnostic + configuration assistée + suivi dans le temps) tient entièrement dans des scopes lecture seule, donc aucune démarche de vérification lourde n'est sur le chemin critique.

---

## 3. Architecture OAuth multi-comptes Google (approfondissement demandé)

### 3.1 Le problème concret

Un même utilisateur de ta plateforme peut vouloir connecter :

- son compte Google personnel pour Search Console,
- un compte Google différent (celui de son client, ou un compte "agence") pour GTM,
- et potentiellement plusieurs propriétés GA4 différentes selon les sites.

Il ne faut donc **jamais** modéliser "1 utilisateur = 1 token Google". Il faut modéliser "1 utilisateur = N connexions Google, chacune avec ses propres scopes et ses propres ressources (comptes GA4, conteneurs GTM, sites GSC) accessibles".

### 3.2 Modèle de données proposé

```
users
  id, email, password_hash / auth_provider, created_at

google_connections            -- une ligne par identité Google liée
  id, user_id (FK),
  google_account_email,
  granted_scopes (text[]),     -- ce qui a été réellement accordé, pas ce qui a été demandé
  refresh_token_encrypted,     -- jamais en clair
  encryption_key_version,      -- pour la rotation de clé
  status (active | needs_reauth | revoked),
  created_at, last_refreshed_at

websites                      -- l'entité métier "site web suivi"
  id, user_id (FK), domain, display_name

website_google_links          -- table de jointure : quelle ressource Google pour quel site
  id, website_id (FK), google_connection_id (FK),
  resource_type (ga4_property | gtm_container | gsc_site),
  resource_id (ex: "properties/123456789", "GTM-XXXXX", "sc-domain:example.com"),
  linked_at

audit_log                     -- indispensable pour le "journal de bord" ET la sécurité
  id, user_id, google_connection_id, action, resource_id,
  request_payload_hash, result (success|error), created_at
```

Ce découpage permet à un utilisateur de lier son site "monsite.com" à un GA4 property venant d'une connexion Google A, un conteneur GTM venant d'une connexion Google B, et un site GSC venant d'une connexion C, sans ambiguïté.

### 3.3 Flow d'autorisation — autorisation incrémentale

Ne demande **pas** tous les scopes (lecture + écriture) dès l'inscription. Utilise le pattern Google "incremental authorization" :

1. À la connexion d'un compte Google : demander uniquement `analytics.readonly` + `webmasters.readonly` (+ `openid email` pour l'identité).
2. Quand l'utilisateur clique sur "Laisser l'agent configurer ce tag" (fonctionnalité V2/P4), déclencher une **nouvelle** requête OAuth qui ajoute `tagmanager.edit.containers` + `tagmanager.publish` (Google fusionne les scopes sur le même refresh token si le même client OAuth et le même utilisateur sont utilisés, avec `include_granted_scopes=true`).

Avantages : (1) la majorité des utilisateurs qui ne veulent que le diagnostic ne voient jamais l'écran "scopes sensibles", (2) ça te permet de sortir P1-P3 sans même avoir soumis de dossier de scopes restreints à Google, (3) c'est meilleure UX — on ne demande l'accès qu'au moment où on en a besoin.

### 3.4 Stockage et chiffrement des tokens

- **Access tokens** : jamais stockés en base. Ils sont éphémères (< 1h) — soit gardés en cache mémoire/Redis avec expiration, soit simplement régénérés à chaque appel via le refresh token.
- **Refresh tokens** : chiffrement au repos obligatoire. Pattern recommandé — enveloppe de chiffrement : une clé maîtresse (KMS géré par ton cloud provider, ou à défaut un secret manager comme HashiCorp Vault / AWS Secrets Manager / GCP Secret Manager) chiffre une clé de données (DEK) par ligne ou par lot ; la DEK chiffre le refresh token. Ça permet de faire tourner (rotate) la clé maîtresse sans devoir déchiffrer/rechiffrer toute la table à chaque rotation.
- Ne jamais mettre la clé de chiffrement dans le même endroit que les sauvegardes de la base de données.
- `encryption_key_version` dans le schéma permet une rotation progressive sans downtime.

### 3.5 Sécurité additionnelle (au-delà de "AES-256")

- **PKCE** sur le flow d'autorisation même si ton backend est confidentiel (défense en profondeur, recommandé par Google même pour les apps serveur).
- **State parameter** anti-CSRF systématique sur chaque redirection OAuth.
- **Détection de token révoqué** : un appel API qui retourne `invalid_grant` doit marquer la connexion `needs_reauth` et notifier l'utilisateur — ne jamais laisser un cron job échouer silencieusement nuit après nuit.
- **Clients OAuth séparés par environnement** (dev / staging / prod) pour qu'une fuite en dev n'expose pas la prod.
- **Journal d'audit systématique** (table `audit_log` ci-dessus) de toute action d'écriture faite via un token délégué — utile à la fois pour la fonctionnalité "journal de bord" et comme preuve de contrôle en cas d'incident ou d'audit CASA.
- **Plan de réponse à incident** documenté (même minimal) : que fait-on si un refresh token fuite ? → révocation immédiate côté Google (`https://oauth2.googleapis.com/revoke`), rotation de la clé de chiffrement, ré-authentification forcée des utilisateurs concernés.
- **Politique de confidentialité et "Limited Use" disclosure** conformes à la Google API Services User Data Policy — obligatoires pour passer la vérification, à rédiger avant de soumettre le dossier (pas après).

### 3.6 Découverte des ressources après connexion

Après l'échange OAuth, appelle en séquence (avec le token frais) :

- GA4 Admin API `accountSummaries.list` → liste des comptes/propriétés visibles,
- GTM API `accounts.list` puis `containers.list` par compte,
- Search Console `sites.list`.

Présente ces listes à l'utilisateur dans l'UI Next.js pour qu'il choisisse explicitement quoi lier à quel `website` interne — ne jamais lier automatiquement "la première propriété trouvée", le risque de mélanger les données de deux clients différents est réel dès qu'un utilisateur gère plusieurs sites.

---

## 4bis. Export GTM en JSON plutôt qu'écriture live (nouveau)

GTM propose nativement une fonctionnalité **"Import Container"** dans son UI : elle accepte un fichier JSON décrivant des tags, triggers et variables, et l'importe dans un workspace choisi par l'utilisateur — sans jamais passer par l'API en écriture, donc sans scope restreint.

Flow proposé :

1. L'agent analyse le site (dataLayer existant, structure HTML) avec les mêmes outils de lecture que prévu (Search Console, crawler léger, PageSpeed).
2. Il génère le JSON exact du tag/trigger/variable manquant, au format attendu par GTM (`{"exportFormatVersion": 2, "containerVersion": {...}}`).
3. L'UI Next.js propose un bouton "Télécharger la configuration GTM" + un mini-guide ("Admin > Import Container > choisis ce fichier > workspace > Merge > preview avant publication").
4. L'utilisateur garde la main sur l'import et la publication finale dans son interface GTM habituelle — ce qui est aussi, de fait, ta protection "human-in-the-loop" la plus simple possible : zéro action automatique de ta part sur son compte.

Avantage direct : ce que Gemini appelait "Phase 2 — Écriture & Automatisation" (nécessitant l'API GTM en écriture) devient réalisable **dès la P1**, dans le scope lecture seule. La V2 "live" (P4 du tableau ci-dessus) ne devient utile que pour l'utilisateur qui veut vraiment du zéro-clic — un cas d'usage premium, pas une condition pour avoir un produit complet.

---

## 4ter. Ce qui reste valable du plan Gemini (pas besoin d'y retoucher)

- Le choix de stack (FastAPI, Next.js, Claude) est solide.
- Le paradigme "human-in-the-loop" obligatoire avant toute publication GTM/GA4 est la bonne décision et doit rester non négociable, quelle que soit la phase.
- Le cache Redis pour respecter les quotas d'API (GA4 Data API, PageSpeed) reste une bonne idée dès P1, car même en lecture seule ces API ont des quotas par propriété/jour.
- L'idée du "journal de bord" (timeline corrélant actions et performance) est un vrai différenciateur et se construit naturellement à partir de la table `audit_log` proposée ci-dessus, avec des marqueurs sur les graphiques.

---

## 5. Module de détection de stack & bibliothèque de snippets (nouveau)

### 5.1 Deux catégories d'événements à distinguer

- **Sans code** : clics, soumissions de formulaire standard, scroll, liens sortants, téléchargements, et surtout les **changements de page en SPA** — captés par le trigger natif GTM "History Change", qui écoute `pushState`/`replaceState`/`popstate`. Comme Next.js, Angular et Vue passent tous par cette même API navigateur pour le routing, ce cas fonctionne **sans écrire une ligne de code**, quel que soit le framework.
- **Avec code obligatoire** : tout ce qui n'existe pas dans le DOM — valeur exacte d'une transaction e-commerce, succès d'un envoi de formulaire en AJAX, identifiant utilisateur après connexion. Ça nécessite un `window.dataLayer.push({...})` déclenché depuis le code applicatif, au bon moment métier.

### 5.2 Détection automatique de la stack

Fingerprinting léger par requête HTTP + parsing du HTML/JS exposé (même principe que Wappalyzer, pas besoin de navigateur headless pour cette étape) :

- Next.js : présence de `__NEXT_DATA__`, chemins `/_next/static/`.
- WordPress : `wp-content`, `wp-json` dans les requêtes réseau, meta generator.
- Angular : attribut `ng-version` sur l'élément racine.
- Vue/Nuxt : `__NUXT__`, attributs `data-v-*`.
- Autre/inconnu : fallback générique.

### 5.3 Bibliothèque de patterns par framework

Une config (pas du code dupliqué) associant à chaque stack détectée : où placer le snippet, comment l'appeler, un exemple minimal.

- **Next.js** : helper `lib/analytics.ts` exposant `trackEvent()`, appelé dans le handler de succès de l'action métier ; pour un pageview SPA si jamais le History Change ne suffit pas, hook basé sur `usePathname`/`useSearchParams`.
- **WordPress** : si WooCommerce, pointer vers le plugin officiel Google plutôt que réinventer du code ; sinon, snippet inline positionné via le hook PHP pertinent (ex. `woocommerce_thankyou`).
- **Angular** : un `AnalyticsService` injectable encapsulant le push, appelé depuis le service métier concerné.
- **Vue/Nuxt** : composable ou plugin équivalent, hook `afterEach` du router.
- **Générique** : snippet vanilla JS + explication en langage naturel du point d'appel.

### 5.4 Livraison à l'utilisateur

Même philosophie que l'export GTM : l'agent ne touche jamais au dépôt du client (il n'y a de toute façon pas accès — seulement le site en ligne et les comptes Google). Il génère une carte "snippet + instructions de placement" dans l'UI Next.js, que le développeur du client copie-colle lui-même.

### 5.5 Piste future (pas pour le MVP)

Une connexion GitHub optionnelle où l'agent ouvrirait directement une Pull Request avec le snippet inséré au bon endroit (façon Dependabot/Copilot). Ça demande de comprendre un dépôt arbitraire par analyse statique — un chantier à part entière, à garder en tête pour une V3+.

---

## 6. Prochaines étapes possibles (à choisir ensemble)

1. Rédiger le schéma de base de données complet (SQL) pour P0-P1, incluant le backlog de correctifs et le journal de bord.
2. Écrire le system prompt + la liste d'outils (tool use Claude) pour l'agent "conseiller" unique de la P1, y compris les outils de détection de stack et de génération de snippets/export GTM.
3. Détailler le flow FastAPI complet de l'autorisation OAuth incrémentale (endpoints, gestion des redirections, code d'exemple).
4. Spécifier le format exact du JSON d'export GTM et le générateur de snippets par framework.
5. (Optionnel, à garder pour plus tard) Lister les documents à préparer pour une future vérification Google si l'auto-configuration live devient nécessaire.

---

### Sources consultées pour les points de conformité Google

- [Restricted scope verification – Google for Developers](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
- [OAuth App Verification FAQ – Google Cloud Platform Console Help](https://support.google.com/cloud/answer/13463817?hl=en)
- [Annual Recertification – Google Cloud Platform Console Help](https://support.google.com/cloud/answer/13463816?hl=en)
- [Tag Manager API v2 Authorization – Google for Developers](https://developers.google.com/tag-platform/tag-manager/api/v2/authorization)

*Note : Google ne publie pas de liste figée et exhaustive des scopes "sensibles" vs "restreints" en dehors de la Cloud Console elle-même — au moment de configurer l'écran de consentement OAuth, chaque scope demandé y est classé automatiquement. Vérifie la classification exacte de `tagmanager.edit.containers`, `tagmanager.publish` et `analytics.edit` directement dans ta Google Cloud Console au moment de P4, la classification pouvant évoluer.*
