# Validation du conteneur GTM généré par le plan de mesure [PROPRIÉTAIRE]

**Le conteneur GTM généré ne doit pas être proposé aux utilisateurs avant cette
validation.** Le générateur (`backend/app/services/gtm_generator.py`, fonction
`build_selected_container`) construit le JSON à la main d'après la structure d'un export
GTM. Aucun import dans un vrai GTM n'a encore confirmé que le format est accepté. Les
tests automatiques ne valident que la cohérence interne (identifiants, références entre
balises et déclencheurs), pas l'acceptation par Google.

Cette étape est manuelle : elle demande un compte Google et un conteneur GTM de test. Elle
n'est exécutée ni par l'outillage du dépôt ni par les tests.

## Fichier d'exemple

`docs/ops/gtm-sample-container.json` est un conteneur généré pour un site de démonstration
(pile Next.js, donc avec le déclencheur History Change), avec :

- la balise « GA4 Configuration » (`googtag`) et trois événements GA4 (`gaawe`) : achat,
  contact, clic sur un numéro de téléphone ;
- la balise de conversion Google Ads (`awct`) et le Conversion Linker (`gclidw`) ;
- un déclencheur de clic (`linkClick`) et le déclencheur History Change ;
- la clé de premier niveau `importMetadata`, ajoutée par le générateur.

Il ne contient aucun secret : l'ID de mesure GA4 (`G-TEST123456`) et les identifiants
Google Ads sont des valeurs factices. Tu peux aussi générer un fichier depuis l'application
(page « Plan de mesure », bouton « Générer mon pack de démarrage »).

## Préparation

1. Crée dans GTM un conteneur **de test** (Web), sans lien avec un site en production.
2. Ouvre-le, puis va dans Administration > Importer un conteneur.
3. Choisis `gtm-sample-container.json`.
4. Espace de travail : **Nouvel espace de travail**. Option d'import : **Fusionner**, puis
   **Renommer les conflits**. (Ce sont les mêmes consignes que celles affichées par
   l'application et écrites dans `importMetadata`.)

Note chaque refus ou message d'erreur exact de GTM, avec une capture d'écran.

## Points à vérifier

### 1. Balises `gaawe` (événements GA4)

Le générateur référence l'ID de mesure par `measurementId` avec un `tagReference` vers la
balise « GA4 Configuration » (`googtag`). Or GTM exporte normalement ces balises avec
`measurementIdOverride` (la balise `googtag` portant l'ID). C'est le point le plus
incertain.

- Après l'import, ouvre « GA4 - purchase » : le champ « ID de mesure » ou la référence à la
  balise de configuration est-il bien renseigné ?
- Passe en mode Aperçu sur un site de test : la requête `/g/collect` de chaque événement
  contient-elle le bon `tid=G-…` ?
- Si l'ID n'est pas transmis : exporte un conteneur GTM contenant les mêmes balises créées
  à la main, compare les paramètres, et note l'écart à corriger dans le générateur.

### 2. Types `awct` et `gclidw`

- La balise « Google Ads - Conversion » (`awct`) est-elle importée avec son ID et son
  libellé de conversion ? Le type est-il reconnu (« Suivi des conversions Google Ads »).
- Le « Conversion Linker » (`gclidw`) est-il importé sans erreur ?
- Ces deux balises restent à ajuster avec de vrais identifiants Google Ads avant tout usage.

### 3. Clé de premier niveau `importMetadata`

- GTM tolère-t-il cette clé absente d'un export normal, ou refuse-t-il le fichier ?
- Si le fichier est refusé à cause de cette clé : note le message, la clé est à retirer du
  JSON téléchargé (elle ne sert qu'à afficher les consignes d'import dans l'application).

### 4. Déclencheurs de clic et History Change

- Le déclencheur « Clic - click_to_call » (`linkClick`, filtre `startsWith` `tel:`) est-il
  importé avec son filtre ?
- Le déclencheur « History Change (SPA) » est-il importé et rattaché à la balise « GA4
  Configuration » ?
- En Aperçu, un clic sur un lien `tel:` déclenche-t-il bien la balise de l'événement ?

## Aperçu

Après l'import, ouvre le mode Aperçu (Tag Assistant) sur un site de test, vérifie que les
balises se déclenchent, puis **ne publie pas** le conteneur de test sur un site réel.

## Résultat à consigner

Pour chacun des quatre points : accepté / refusé / accepté avec écart, avec le message de
GTM et la date. Tant qu'un point est « refusé », le conteneur ne doit pas être proposé ; le
correctif se fait dans `gtm_generator.py`, avec un test, puis on rejoue la procédure.
Tu peux consigner le résultat à la fin de ce fichier.
