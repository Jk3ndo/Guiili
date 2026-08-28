# Réserves & compléments sur le plan v3 (analyse Claude — 2026-08-28)

Points à intégrer au fil des phases. Ne remettent pas en cause la roadmap, mais
corrigent des angles morts.

## 1. Refresh token de 7 jours en mode "Testing" — angle mort majeur

Tant que l'app OAuth est en statut **Testing**, Google expire les refresh tokens
au bout de **7 jours**. P2 (suivi continu via cron) suppose des tokens qui vivent
des semaines.

**Conséquence :** le monitoring continu n'est réellement utilisable pour des
beta-testeurs qu'après passage "In production" (donc après vérification de
marque). **P3 doit précéder ou chevaucher P2**, pas venir après. À reséquencer.

Pour le dev solo pendant P0–P1 : le compte propriétaire du projet Cloud n'est pas
soumis à cette expiration → OK pour développer.

## 2. Les scopes readonly sont "sensibles", pas anodins

`analytics.readonly` et `webmasters.readonly` = scopes **sensibles** (pas
restreints). En Testing avec ≤100 users : OK, écran "app non vérifiée". Ouverture
publique = vérification de marque obligatoire (quelques jours à quelques
semaines). Rédiger privacy policy + Limited Use disclosure **avant** de soumettre.

## 3. Détection de stack sans navigateur headless : limite réelle

Fingerprinting HTML/HTTP OK pour Next.js SSR (`__NEXT_DATA__`), WordPress, Nuxt.
Mais Angular / Vue **purement client-side** servent un HTML quasi vide :
`ng-version` / `data-v-*` n'apparaissent qu'après exécution du JS. Sans headless,
ces cas tombent en "inconnu/générique". Prévoir soit ce fallback assumé, soit un
Playwright optionnel pour cette seule étape (P1).

## 4. Détection d'anomalie : la saisonnalité hebdo génère des faux positifs

Moyenne mobile + écart-type brut sur métriques GA4/GSC → lundi vs dimanche
déclenche des alertes. Minimum : baseline **par jour de semaine** ou comparaison
semaine sur semaine. (P2)

## 5. Benchmark concurrentiel : cadrer ce qui est faisable avec des données publiques

Pas d'accès au GA4/GSC du concurrent. Réaliste : PageSpeed sur ses URLs, stack
détectée, tags visibles. Positionnement SERP = source de rank-tracking (souvent
payante). Ne pas surpromettre. (P2)

## 6. Chiffrement enveloppe KMS→DEK par ligne : trop pour la V1

Master key en secret manager + AES-256-GCM applicatif avec `encryption_key_version`
suffit pour le MVP. L'enveloppe DEK-par-ligne arrive en P2–P3 si besoin. Le schéma
reste compatible (colonne de version déjà là).

## 7. Coûts récurrents à budgéter dès P1

- Coût API Claude par audit (fonction du volume de tokens d'un audit type).
- Quotas GA4 Data API (tokens par propriété/jour).
- PageSpeed Insights : 25 000 req/jour avec clé API.
- Cache Redis déjà prévu — chiffrer l'ordre de grandeur avant P1.

## 8. RGPD (utilisateur en France + données Google d'utilisateurs)

Politique de rétention des données, localisation d'hébergement (UE de
préférence), registre de traitement, DPA. À intégrer à P3, pas après.

---

## Décisions d'implémentation actées (2026-08-28)

- **Auth appli** : Google OIDC uniquement (`openid email profile`). Pas de
  mot de passe géré. `users.auth_provider = 'google'` + `users.google_sub`.
  Email/password possible plus tard sans casser le schéma.
- **Outillage backend** : `uv` (pyproject.toml + uv.lock).
- **Infra locale** : Docker Compose (postgres:16, redis:7).
- **Chiffrement refresh tokens** : AES-256-GCM via `cryptography`, une master key
  par version chargée depuis l'environnement, `encryption_key_version` dénormalisée
  en colonne. Enveloppe DEK-par-ligne repoussée à P2.
- **Tables MVP** : `users`, `google_connections`, `websites`,
  `website_google_links`, `audit_snapshots`, `issue_items`, `audit_log`.
