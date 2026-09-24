# Plan de mesure guidé (lot A) — spec de conception

**Décisions de périmètre actées en discussion :**
- **Lancement** : bêta fermée d'abord (≤ 100 testeurs approuvés côté Google,
  aucune vérification OAuth requise au départ). Voir la feuille de route
  `2026-09-24-roadmap-v2.md`.
- **Premier lot** : A (ce document). B (suivi planifié) suit immédiatement.
- **Type de site** : détection automatique + confirmation en un clic, profil
  **multi-types** (un site peut être boutique ET contenu).
- **Preuve** : deux niveaux — « présent sur la page » puis « reçu par GA4 ».
- **Google Ads** : guide + conteneur GTM pré-rempli. **Aucune API Ads** dans ce
  lot (developer token hors périmètre).
- **Aucune écriture** dans les comptes Google (GA4, GTM, Ads) : lecture seule,
  comme aujourd'hui. Toute « configuration » passe par des fichiers à importer,
  des snippets et des guides.
- **L'IA n'a jamais le dernier mot sur un statut** : le conseiller explique, le
  moteur de vérification décide.
- Interface en **français** uniquement pour ce lot.

## 1. But

Un utilisateur novice ajoute son site et obtient, sans connaître GA4 ni GTM, un
**plan de mesure** : ce qui est en place, ce qui manque pour observer son trafic
et suivre ses conversions, dans quel ordre le faire, et un moyen concret de le
faire (guide, snippet, conteneur GTM à importer).

**Critère de réussite** : un site avec GTM et GA4 partiellement en place obtient
un plan priorisé et juste où chaque « fait » est prouvé, et l'utilisateur repart
avec un conteneur GTM à importer qui comble les manques.

**Hors périmètre** : suivi planifié et historique (lot B), dashboard (C), analyse
SEO dans le temps (D), PR automatiques (E), écriture Google / API Ads (F),
internationalisation, autres outils que GA4/GTM/Google Ads (Meta, TikTok…).

## 2. Ce qui existe déjà et est réutilisé

| Module | Usage dans ce lot |
|---|---|
| `services/page_fetch.py` | HTML de la page, base des vérifications « présent » statiques |
| `services/gtm_check.py` | Détection GTM (conteneurs, position du snippet, CMP, `dataLayer` renommé, GA4 codé en dur) |
| `services/gtm_headless.py` | Navigateur réel pour les vérifications « en conditions réelles » |
| `services/ga4.py` + connexion Google workspace | Lecture GA4 (niveau « reçu ») |
| `services/gtm_generator.py` | Base du conteneur GTM sur mesure |
| `services/snippet_library.py` | Base des snippets par stack |
| `services/stack_detector.py` | Stack du site, indice pour le type de site |
| `services/advisor/*` | Explication d'un item (action « demander au conseiller ») |

### Extensions nécessaires (constatées dans le code)

1. **`gtm_headless`** ne capture aujourd'hui que les requêtes vers
   `googletagmanager.com`. Il doit aussi enregistrer : les requêtes de collecte
   GA4 (`google-analytics.com/g/collect`, `analytics.google.com`), les requêtes
   publicitaires (`googleadservices.com`, `doubleclick.net`), le contenu du
   `dataLayer` (noms d'événements) et les signaux de consentement (état par
   défaut de Consent Mode). `GtmHeadlessResult` gagne des champs additifs avec
   valeurs par défaut (rétro-compatible).
2. **`ga4.py`** n'expose que `fetch_event_metrics -> Ga4Signals` (signaux ciblés).
   Ajouter `fetch_event_counts(access_token, property_id, days=30) ->
   dict[str, int]` (runReport `eventName × eventCount`), plus des lectures Admin
   API (voir §7).
3. **`snippet_library.SnippetEvent`** ne connaît que `purchase`, `lead`,
   `custom`. Étendre aux événements du catalogue (§4).
4. **`gtm_generator.build_gtm_container`** produit 3 événements fixes. Il doit
   accepter une **sélection d'items** et des paramètres Ads (§6).

## 3. Modèle de données

Deux nouvelles tables, aucune modification des tables existantes. Une migration
Alembic (hand-codée si besoin, comme les précédentes).

### `website_profile` (1 ligne par site)
| Colonne | Type | Rôle |
|---|---|---|
| `website_id` | UUID PK/FK `websites.id` (cascade) | |
| `detected_types` | JSONB | liste ordonnée `[{type, confidence}]` + signaux ayant conduit au choix |
| `confirmed_types` | JSONB nullable | types validés par le propriétaire (liste) |
| `confirmed_at` | timestamptz nullable | |
| `params` | JSONB | `ga4_measurement_id` (optionnel, sinon lu depuis GA4), `ads_conversion_id`, `ads_conversion_label` |
| `updated_at` | timestamptz | |

Types autorisés : `ecommerce`, `lead_gen`, `saas`, `content`, `other`.
Types effectifs pour le plan = `confirmed_types` si présent, sinon
`detected_types` avec confiance ≥ 0,5, sinon `other`.

### `measurement_item_status` (1 ligne par site et par item)
| Colonne | Type | Rôle |
|---|---|---|
| `website_id` | UUID FK (cascade) | |
| `item_id` | String(64) | identifiant du catalogue (§4) |
| `state` | String | `unknown` \| `missing` \| `on_page` \| `received` \| `unverifiable` \| `not_applicable` \| `dismissed` |
| `evidence` | JSONB | faits techniques uniquement (noms d'événements, ID de balises, comptages) |
| `reason` | String nullable | pourquoi `unverifiable` (site injoignable, GA4 non connecté…) |
| `checked_at` | timestamptz | |
| `dismissed_at` | timestamptz nullable | écarté par le propriétaire |

Contrainte unique `(website_id, item_id)`. Les états sont des `String` validés
côté code (comme `advisor_messages.role`), pas des `pg_enum`, pour éviter les
migrations de contrainte CHECK quand le catalogue évolue.

L'**historique** des statuts dans le temps est le sujet du lot B ; cette
structure ne l'empêche pas (le lot B ajoutera une table d'historique).

## 4. Le catalogue

Défini **en code**, versionné, testé. Un item (`MeasurementItem`, dataclass gelée) :
`id`, `layer`, `applies_to` (ensemble de types ou `all`), `weight` (priorité),
`quick_win` (bool), `title`, `why` (explication novice en français),
`checks` (liste de vérifications), `actions` (liste d'actions).

Couches : `foundations`, `events`, `conversions`, `ads`, `seo`.

Environ 30 items :

- **Fondations (tous)** : GTM dans `<head>` · balise GA4 qui se déclenche · pas de
  double comptage (GA4 codé en dur + GTM) · consentement cookies + Consent Mode v2 ·
  `dataLayer` standard · Search Console connectée.
- **Événements boutique** : `view_item`, `add_to_cart`, `begin_checkout`,
  `purchase` (avec `value`, `currency`, `transaction_id`).
- **Événements prise de contact** : `generate_lead`, clic téléphone, clic e-mail,
  clic WhatsApp, téléchargement de fichier.
- **Événements SaaS** : `sign_up`, `login`, démarrage d'essai, abonnement,
  étapes d'onboarding.
- **Événements contenu** : inscription newsletter, clics sortants, recherche
  interne, partage.
- **Conversions** : événements clés marqués comme conversions dans GA4 · valeur
  de conversion renseignée.
- **Publicité** : GA4 lié à Google Ads · balise de conversion Ads présente ·
  Conversion Linker · balisage automatique (gclid) · audiences de remarketing.
- **SEO de base** : propriété Search Console vérifiée · sitemap soumis ·
  `robots.txt` accessible · HTTPS valide.

Le **texte utilisateur** (`title`, `why`, étapes de guide) est du contenu produit :
il est relu et validé par le propriétaire du produit avant mise en ligne, pas
seulement par les tests.

### Vérifications (`checks`)

Chaque vérification est une fonction pure ou injectable qui renvoie
`(state, evidence)` ou lève `Unverifiable(reason)`.

- **Niveau « présent »** : `on_page_static` (HTML / `GtmCheck`) et
  `on_page_headless` (requêtes observées, `dataLayer`, consentement).
- **Niveau « reçu »** : `ga4_event_received(name)` (comptage sur 30 jours),
  `ga4_sessions`, `ga4_key_event(name)`, `ga4_ads_link`.
- **Niveau SEO** : `gsc_property`, `gsc_sitemaps`, `http_robots`, `tls_valid`.

L'état d'un item est le **niveau de preuve le plus haut atteint** : `received`
> `on_page` > `missing`. Si un niveau est inaccessible (GA4 non connecté), l'item
reste au niveau inférieur atteint et `reason` indique ce qui manque pour aller
plus loin ; on n'affiche jamais « fait » sans preuve.

## 5. Détection du type de site

Signaux et types candidats :
- `ecommerce` : stack Shopify/WooCommerce, pages panier / paiement, données
  structurées produit (JSON-LD `Product`), boutons « ajouter au panier ».
- `lead_gen` : formulaires, liens `tel:` et `mailto:`, mots « devis », « contact ».
- `saas` : page de tarifs, « créer un compte », `/login`, `/app`.
- `content` : données structurées `Article`, nombreuses pages de type blog.

Sortie : liste triée `[{type, confidence, signals}]`. Fonction pure, testée sur
des fixtures HTML. Le propriétaire confirme en un clic (choix multiple) ; la
confirmation prime toujours sur la détection.

## 6. Actions

Chaque item propose une ou plusieurs actions :

1. **Guide** : étapes courtes en français avec case à cocher (état côté client,
   non persisté dans ce lot).
2. **Snippet** : code adapté à la stack détectée.
3. **Mon conteneur GTM** : l'utilisateur sélectionne les items manquants ;
   `POST /websites/{id}/measurement-plan/gtm-container` renvoie **un JSON unique**
   en mode « fusion », construit depuis le profil : ID de mesure GA4 lu depuis
   la propriété GA4 connectée (repli : `params.ga4_measurement_id`), ID et
   libellé de conversion Ads issus de `params`. Conversion Linker et consentement
   par défaut inclus selon les items choisis.
4. **Demander au conseiller** : ouvre un fil préchargé avec le contexte de l'item
   (l'IA explique, elle ne change jamais un statut).
5. **Ouvrir une PR** : emplacement réservé et désactivé (« bientôt ») pour le
   lot E ; aucune logique derrière.

## 7. Vérifications à faire pendant l'implémentation

Ces points dépendent d'API Google et ne peuvent pas être affirmés d'avance :
- Que la lecture de `keyEvents`, de `googleAdsLinks` et des `dataStreams`
  (pour l'ID de mesure) fonctionne avec le scope **`analytics.readonly`** déjà
  demandé, et quelle version de l'Admin API (`v1beta` ou `v1alpha`) les expose.
  Si un item ne peut pas être lu, il reste au niveau « déclaratif »
  (`unverifiable`, raison explicite) et on le documente ; on n'élargit pas les
  scopes dans ce lot.
- Que les API Google restent activées sur le projet Google Cloud `guiili`
  (état vérifié le 2026-09-24 : Analytics Admin, Analytics Data et Search
  Console). Elles doivent aussi l'être sur tout projet Google Cloud futur
  utilisé pour la bêta.

## 8. API

- `GET /websites/{id}/measurement-plan` → profil, progression par couche, items
  ordonnés (couche, puis poids), avec état, preuve, raison, actions. Membres du
  workspace.
- `POST /websites/{id}/measurement-plan/refresh` → relance les vérifications
  (statiques + GA4) ; `?headless=true` ajoute la vérification navigateur
  (rate-limitée comme `POST .../gtm/headless`). Membres.
- `PATCH /websites/{id}/measurement-plan/profile` → confirme les types, saisit
  `ads_conversion_id`/`ads_conversion_label`. **Propriétaire uniquement**
  (`require_owner`).
- `PATCH /websites/{id}/measurement-plan/items/{item_id}` → écarter / rétablir un
  item. **Propriétaire uniquement.**
- `POST /websites/{id}/measurement-plan/gtm-container` → conteneur sur mesure
  (téléchargement JSON). Membres.

`refresh` est idempotent et écrit par upsert sur `(website_id, item_id)`.

## 9. Gestion des erreurs

- Chaque vérification est indépendante : l'échec de l'une ne bloque pas les
  autres ; le résultat d'un `refresh` partiel est enregistré.
- `Unverifiable(reason)` → état `unverifiable` + raison affichée (site
  injoignable, headless en échec, GA4 non connecté, quota ou erreur Google) ;
  jamais un « fait » par défaut.
- Un item peut **régresser** (`received` → `on_page` → `missing`) à chaque
  nouvelle vérification.
- Timeouts explicites sur tous les appels réseau ; aucun scan ne fait tomber
  l'endpoint (même politique que `scan_website`).
- Les preuves ne contiennent aucune donnée personnelle.

## 10. Interface

- Nouvelle page **Plan de mesure** dans la navigation : progression par couche,
  liste ordonnée avec « gains rapides » en tête, tiroir par item (explication,
  preuve, niveau atteint, actions), bouton « Vérifier maintenant » et option
  « en conditions réelles » (headless).
- Étape de **confirmation du type de site** au premier affichage (détection
  pré-sélectionnée, choix multiple, un clic).
- Indicateur de progression sur la vue d'ensemble.
- Respecte la direction artistique en vigueur (Linear / Knock, aucune couleur
  décorative, couleurs de statut uniquement).

## 11. Tests (aucun appel réseau)

- **Catalogue** : identifiants uniques ; chaque item a `why`, ≥ 1 vérification et
  des types applicables ; chaque action référence un snippet / une recette
  existants ; couverture des 5 couches.
- **Vérifications** : fixtures HTML, résultat headless simulé, réponses GA4
  (Data et Admin) simulées ; cas « GA4 non connecté » → niveau « présent »
  seulement, jamais « reçu ».
- **Machine d'états** : `missing → on_page → received`, régression, `dismissed`,
  `not_applicable` selon le profil.
- **Détection du type** : fixtures par type, multi-types, cas ambigu.
- **API** : droits par rôle (membre vs propriétaire), isolation entre
  workspaces, idempotence du `refresh`, conteneur GTM valide (import « fusion »).
- **Extensions** : `gtm_headless` (nouveaux champs, rétro-compatibilité),
  `ga4.fetch_event_counts`, `gtm_generator` avec sélection d'items, snippets
  des nouveaux événements.
- **Frontend** : build + lint sans erreur ; vérification dans le navigateur sur
  un vrai site (qaopscareer.com, où `generate_lead` est connu comme manquant).
- **Suite complète** `pytest -W error` verte deux fois de suite, `ruff` et
  `alembic check` propres.

## 12. Livraison

Purement additif : une migration (2 tables), aucun changement de comportement
existant. Le déploiement sur Cloud Run reste une étape validée explicitement par
le propriétaire. Aucun changement de scopes OAuth, donc aucune reconsentement
utilisateur.

## 13. Risques

- **Contenu du catalogue** : sa qualité fait la valeur du produit ; il doit être
  relu avant mise en ligne (§4).
- **Faux « présent »** : la détection statique peut manquer un tracking injecté
  tard ; d'où le niveau headless et le niveau « reçu » comme preuve finale.
- **API Admin GA4** : périmètre exact de lecture à confirmer (§7).
- **Coût du headless** : reste une action explicite et limitée en fréquence.
