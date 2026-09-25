# Benchmark Amplitude et Matomo (référence)

Synthèse **reformulée** de ce que proposent https://www.amplitude.com/fr-fr et
https://fr.matomo.org/, lue le 2026-09-25. Sert de base à la feuille de route v3
(`2026-09-25-roadmap-v3-architecture-design.md`).

## Limites de cette lecture

- Les deux pages d'accueil ont été refusées par le contrôle de domaine de l'outil
  de lecture ; leur navigation complète et une trentaine de pages produit, tarifs
  et plugins ont été lues à la place.
- Aucune interface connectée n'a été vue (comptes non créés). Le parcours de prise
  en main est déduit des pages publiques, pas observé.
- Les chiffres marketing (« 76 % des demandes résolues », « 217 % de ROI »,
  « 1 million d'organisations ») sont des affirmations des éditeurs, non vérifiées.

## Amplitude : plateforme d'analyse comportementale de produit

Positionnement : « produits qui s'auto-améliorent », tout-en-un et IA d'abord.
Organisée en quatre couches.

| Couche | Contenu |
|---|---|
| Collecter (Sense) | Événements, propriétés, utilisateurs ; SDK et « une seule ligne de code » ; gouvernance des données : plan de tracking, assistant IA de qualité, permissions par rôle, synchronisation avec Snowflake ou Databricks |
| Décider (Decide) | Analyse de produit (entonnoirs, rétention, cohortes, segments, formules, tableaux de bord par secteur), analyse marketing (regroupement automatique des UTM et référents en canaux, attribution multi-touch, tableaux de bord préconstruits, compatible GTM), Session Replay (texte masqué par défaut, résumés IA, mobile et web), Heatmaps (clics, défilement, sélection), Zoning Insights (métriques par zone de page : taux de clic, exposition, attractivité, revenu par clic) |
| Agir (Act) | Expérimentation de fonctionnalités et web (A/B, tests séquentiels, CUPED, bandits, feature flags), guides et enquêtes (visites guidées, checklists, annonces, bulles, bannières ; ciblage comportemental, no-code), Activation (audiences et cohortes synchronisées vers e-mail, publicité, produit) |
| Agents IA | Boucle détecter, analyser, agir ; Global Agent (analyste permanent) et agents spécialisés ; recommandations que l'utilisateur approuve ; serveur MCP pour Claude, Cursor, Figma, GitHub ; analytique des agents IA eux-mêmes |

Autres traits : 159 intégrations (entrepôts, CDP, e-mail, publicité dont Google Ads,
Meta, TikTok) ; centres de données UE et US, ISO 27001, SOC 2 Type II, API de
demandes d'accès RGPD, contrôle de la durée de rétention ; **aucun module SEO**.

Tarifs : offre gratuite jusqu'à 2 millions d'événements par mois sans limite de durée ;
plans Plus, Growth et Enterprise facturés à l'événement (pas à l'utilisateur actif) ;
modules avancés facturés en pourcentage du forfait ; programme startup.

## Matomo : alternative souveraine à Google Analytics

Positionnement : propriété à 100 % des données, respect de la vie privée par
conception, **aucun échantillonnage**, cloud (hébergé à Francfort) ou auto-hébergé,
code ouvert. Sans cookie et exempté de consentement par la CNIL (selon leur
documentation). ISO 27001:2022. Plus de 100 intégrations (CMS, e-commerce,
frameworks, SDK mobiles, Looker, Grafana).

| Domaine | Contenu |
|---|---|
| Gratuit (cœur) | Rapports temps réel, plus de 30 rapports standard, tableaux de bord, vue tous sites, événements et contenu, recherche interne, dimensions personnalisées, plus de 110 segments, objectifs, e-commerce, campagnes, transitions de pages, Tag Manager |
| Premium (plugins payants) | Entonnoirs (rétroactifs sur les objectifs), cohortes, rapports personnalisés (plus de 200 dimensions et métriques, envoi planifié par e-mail, SMS, Slack, Teams), heatmaps (clic, survol, défilement) et enregistrements de sessions (échantillonnage, masquage des saisies), analytics de formulaires et de médias, A/B, attribution multi-touch (linéaire, en position), alertes personnalisées (seuils et variations, e-mail, SMS, Slack), roll-up multi-sites, marque blanche |
| SEO | Plugin « Search Engine Keywords Performance » : mots-clés, impressions, clics, CTR et position depuis Google Search Console, Bing et Yandex, reliés aux visites et aux conversions, avec erreurs d'exploration et pages indexées ; plugin « SEO Web Vitals » : Core Web Vitals et score de vitesse, audit des causes, historique, alertes |
| Migration | Importeur Google Analytics ; page de comparaison avec neuf concurrents |

Tag Manager : balises, déclencheurs et variables, versions et publication,
interface par clic, sans développeur.

Tarifs : cloud à partir de 29 €/mois (50 000 hits) avec 21 jours d'essai gratuit ;
auto-hébergé gratuit (Community) ou par bundles annuels ; plugins vendus à l'unité
avec essai de 30 jours.

## Prise en main (déduite des pages publiques)

| | Amplitude | Matomo |
|---|---|---|
| Première valeur | Un extrait de code ; suivi automatique des pages vues, sessions, clics ; tableaux de bord préconstruits | Une ligne JavaScript ; Tag Manager prêt à l'emploi ; essai gratuit de 21 jours sans carte |
| Configuration avancée | Plan de tracking, gouvernance, événements personnalisés | Objectifs, segments, plugins |
| Migration | Intégrations et entrepôts | Importeur GA, plugins CMS |

## Ce que ni l'un ni l'autre ne fait

- Vérifier que la mesure d'un site fonctionne réellement, avec une preuve, puis
  dire quoi installer, dans quel ordre.
- Ouvrir une pull request qui instrumente le dépôt du client.
- Classer SEO, Core Web Vitals, tracking et publicité dans un seul backlog priorisé
  par impact.
- Un SEO profond : Amplitude n'en a pas, Matomo se limite aux mots-clés et aux
  Web Vitals.

## Sources principales

Amplitude : `/fr-fr/amplitude-analytics`, `/web-analytics`, `/session-replay`,
`/heatmaps`, `/zoning-insights`, `/data-governance`, `/ai-agents`,
`/ai-analytics-platform`, `/amplitude-experiment`, `/guides-and-surveys`,
`/activation`, `/integrations`, `/mcp-server`, `/security-and-privacy`, `/pricing`.
Matomo : `/features/`, `/feature-overview/`, `/product-features/`, `/guide/tag-manager/`,
`/multi-attribution/`, `/cookie-consent-banners/`, `/no-data-sampling/`, `/integrate/`,
`/matomo-cloud/`, `/google-analytics-alternative/`, `/pricing/`, et les fiches de
plugins (SEOWebVitals, SearchEngineKeywordsPerformance, CustomAlerts,
HeatmapSessionRecording, Funnels, CustomReports).
