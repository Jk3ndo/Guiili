"""Catalogue des items du plan de mesure.

Contenu produit : les textes (`title`, `why`, `guide`) sont relus et validés par le
propriétaire du produit avant mise en ligne, pas seulement par les tests.
"""

from __future__ import annotations

from app.services.measurement.types import (
    ActionKind,
    Layer,
    MeasurementItem,
    SiteType,
)

LAYER_ORDER: tuple[Layer, ...] = ("foundations", "events", "conversions", "ads", "seo")

_ECOM: frozenset[SiteType] = frozenset({"ecommerce"})
_LEAD: frozenset[SiteType] = frozenset({"lead_gen"})
_SAAS: frozenset[SiteType] = frozenset({"saas"})
_CONTENT: frozenset[SiteType] = frozenset({"content"})
_LEAD_SAAS: frozenset[SiteType] = frozenset({"lead_gen", "saas"})

_EVENT_ACTIONS: tuple[ActionKind, ...] = ("guide", "snippet", "gtm_container", "advisor")
_AUTO_ACTIONS: tuple[ActionKind, ...] = ("guide", "advisor")


def _event_guide(place: str) -> tuple[str, ...]:
    return (
        f"Repère où l'action se produit sur ton site : {place}.",
        "Ouvre l'onglet « Snippet » de cette ligne et copie le code fourni à cet "
        "endroit (ou transmets-le à ton développeur).",
        "Vérifie dans GA4, rapport « Temps réel », que l'événement apparaît quand tu "
        "fais l'action toi-même.",
        "Reviens ici et clique sur « Vérifier maintenant » : la ligne passe à « Reçu par "
        "GA4 » dès que GA4 a traité les données (jusqu'à 24 h).",
    )


def _event(
    *,
    event: str,
    applies_to: frozenset[SiteType],
    weight: int,
    title: str,
    why: str,
    place: str,
    quick_win: bool = False,
) -> MeasurementItem:
    return MeasurementItem(
        id=f"event_{event}",
        layer="events",
        applies_to=applies_to,
        weight=weight,
        quick_win=quick_win,
        title=title,
        why=why,
        check="event",
        arg=event,
        max_level="received",
        guide=_event_guide(place),
        actions=_EVENT_ACTIONS,
        snippet_event=event,
    )


def _auto_event(
    *,
    item_id: str,
    event: str,
    applies_to: frozenset[SiteType],
    weight: int,
    title: str,
    why: str,
    guide: tuple[str, ...],
) -> MeasurementItem:
    """Événement mesuré automatiquement par GA4 (« mesures améliorées »)."""
    return MeasurementItem(
        id=item_id,
        layer="events",
        applies_to=applies_to,
        weight=weight,
        quick_win=True,
        title=title,
        why=why,
        check="event",
        arg=event,
        max_level="received",
        guide=guide,
        actions=_AUTO_ACTIONS,
        snippet_event=None,
    )


_FOUNDATIONS: tuple[MeasurementItem, ...] = (
    MeasurementItem(
        id="gtm_installed",
        layer="foundations",
        applies_to=None,
        weight=100,
        quick_win=True,
        title="Google Tag Manager installé",
        why=(
            "GTM est la boîte à outils qui te permet d'ajouter le suivi (GA4, publicité, "
            "événements) sans modifier le code du site à chaque fois."
        ),
        check="gtm_installed",
        arg=None,
        max_level="on_page",
        guide=(
            "Crée un compte et un conteneur de type « Web » sur tagmanager.google.com.",
            "Copie les deux extraits de code fournis : le premier dans le <head> de toutes "
            "les pages, le second juste après l'ouverture de <body>.",
            "Publie le conteneur dans GTM.",
            "Reviens ici et clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="gtm_in_head",
        layer="foundations",
        applies_to=None,
        weight=70,
        quick_win=True,
        title="Snippet GTM placé dans le <head>",
        why=(
            "Placé plus bas dans la page, le snippet se charge trop tard : les premières "
            "actions du visiteur ne sont pas mesurées."
        ),
        check="gtm_in_head",
        arg=None,
        max_level="on_page",
        guide=(
            "Repère l'extrait GTM (il contient « googletagmanager.com/gtm.js »).",
            "Déplace-le le plus haut possible dans le <head>, avant les autres scripts.",
            "Reviens ici et clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="ga4_tag",
        layer="foundations",
        applies_to=None,
        weight=100,
        quick_win=True,
        title="Balise Google Analytics 4 active",
        why=(
            "Sans elle, aucun visiteur n'est compté. C'est la base de toute mesure : trafic, "
            "sources, conversions."
        ),
        check="ga4_tag",
        arg=None,
        max_level="received",
        guide=(
            "Dans GA4, crée une propriété puis un flux de données « Web » et note l'ID de "
            "mesure (il commence par G-).",
            "Clique sur « Générer mon pack de démarrage » (en haut de cette page) : le "
            "fichier contient la balise GA4 et les événements essentiels de ton type de "
            "site. Importe-le dans GTM (Administration > Importer un conteneur > « Nouvel "
            "espace de travail » > « Fusionner » > « Renommer les conflits ») et publie.",
            "Dans « Connexions Google », connecte ton compte pour que la plateforme voie "
            "les données arriver.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "gtm_container", "advisor"),
        snippet_event=None,
    ),
    MeasurementItem(
        id="no_double_tracking",
        layer="foundations",
        applies_to=None,
        weight=60,
        quick_win=False,
        title="Pas de double comptage GA4",
        why=(
            "Si GA4 est ajouté dans le code du site ET dans GTM, chaque visite est comptée "
            "deux fois et tes chiffres sont faux."
        ),
        check="no_double",
        arg=None,
        max_level="on_page",
        guide=(
            "Retire du code du site la balise GA4 codée en dur (le script « gtag/js »).",
            "Garde uniquement la balise GA4 gérée dans GTM.",
            "Reviens ici et clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="consent_mode",
        layer="foundations",
        applies_to=None,
        weight=65,
        quick_win=False,
        title="Consentement aux cookies et Consent Mode v2",
        why=(
            "Pour les visiteurs européens, la loi impose de demander le consentement. "
            "Consent Mode permet de continuer à mesurer sans cookies quand le visiteur "
            "refuse, et Google Ads l'exige pour la publicité personnalisée."
        ),
        check="consent",
        arg=None,
        max_level="on_page",
        guide=(
            "Installe une bannière de consentement compatible Consent Mode v2 (Cookiebot, "
            "Axeptio, Didomi, etc.).",
            "Vérifie qu'elle envoie l'état « par défaut : refusé » avant le chargement de GTM.",
            "Si ta bannière ne le fait pas, ajoute le snippet « consent default » fourni, "
            "placé avant le snippet GTM.",
            "Clique sur « Vérifier maintenant » (avec « en conditions réelles » pour une "
            "preuve fiable).",
        ),
        actions=("guide", "snippet", "advisor"),
        snippet_event="consent_default",
    ),
    MeasurementItem(
        id="datalayer_standard",
        layer="foundations",
        applies_to=None,
        weight=40,
        quick_win=False,
        title="dataLayer au nom standard",
        why=(
            "Les outils de test et de nombreux modèles de tags supposent le nom « dataLayer ». "
            "Un autre nom casse ces intégrations sans prévenir."
        ),
        check="datalayer",
        arg=None,
        max_level="on_page",
        guide=(
            "Dans le snippet GTM, repère le dernier paramètre (par défaut « dataLayer »).",
            "Remets-le à « dataLayer » (et adapte le code du site qui poussait vers l'ancien nom).",
            "Reviens ici et clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
)

_EVENTS: tuple[MeasurementItem, ...] = (
    # --- Boutique -----------------------------------------------------------
    _event(
        event="view_item",
        applies_to=_ECOM,
        weight=60,
        title="Vue d'une fiche produit",
        why="Sans cet événement, tu ne sais pas quels produits attirent l'attention avant l'achat.",
        place="sur chaque fiche produit, au chargement de la page",
    ),
    _event(
        event="add_to_cart",
        applies_to=_ECOM,
        weight=70,
        title="Ajout au panier",
        why=(
            "Il mesure l'intention d'achat : l'écart avec les achats montre où tu perds des "
            "clients."
        ),
        place="au clic sur le bouton « ajouter au panier »",
    ),
    _event(
        event="begin_checkout",
        applies_to=_ECOM,
        weight=70,
        title="Début du paiement",
        why=(
            "Il isole les abandons au moment de payer, l'endroit où une amélioration rapporte "
            "le plus."
        ),
        place="à l'ouverture de la page de paiement",
    ),
    _event(
        event="purchase",
        applies_to=_ECOM,
        weight=95,
        title="Achat",
        why=(
            "C'est ta conversion principale : sans elle, impossible de savoir combien te "
            "rapporte chaque source de trafic ni de piloter des campagnes."
        ),
        place="sur la page de confirmation de commande, une seule fois par commande",
        quick_win=True,
    ),
    MeasurementItem(
        id="purchase_params",
        layer="events",
        applies_to=_ECOM,
        weight=90,
        quick_win=False,
        title="Achat avec montant",
        why=(
            "Un achat sans montant ne dit pas combien tu gagnes : les revenus restent à zéro "
            "dans GA4 et dans tes campagnes."
        ),
        check="purchase_params",
        arg=None,
        max_level="received",
        guide=(
            "Dans le code de la confirmation de commande, renseigne « value » (montant), "
            "« currency » (EUR) et « transaction_id » (numéro de commande).",
            "Utilise le snippet de la ligne « Achat » comme modèle.",
            "Fais une commande test, puis clique sur « Vérifier maintenant » le lendemain.",
        ),
        actions=("guide", "snippet", "advisor"),
        snippet_event="purchase",
    ),
    # --- Prise de contact ---------------------------------------------------
    _event(
        event="generate_lead",
        applies_to=_LEAD,
        weight=95,
        title="Demande de contact envoyée",
        why=(
            "C'est ta conversion principale : chaque demande envoyée est un client potentiel "
            "qu'il faut pouvoir rattacher à sa source."
        ),
        place="après l'envoi réussi du formulaire de contact ou de devis",
        quick_win=True,
    ),
    _event(
        event="click_to_call",
        applies_to=_LEAD,
        weight=75,
        title="Clic sur ton numéro de téléphone",
        why=(
            "Beaucoup de clients appellent au lieu d'écrire ; sans ce suivi, ces contacts "
            "sont invisibles."
        ),
        place="au clic sur un lien téléphone (tel:)",
    ),
    _event(
        event="click_email",
        applies_to=_LEAD,
        weight=55,
        title="Clic sur ton adresse e-mail",
        why="Il compte les visiteurs qui préfèrent t'écrire depuis leur messagerie.",
        place="au clic sur un lien e-mail (mailto:)",
    ),
    _event(
        event="click_whatsapp",
        applies_to=_LEAD,
        weight=55,
        title="Clic sur WhatsApp",
        why="Il compte les contacts qui passent par WhatsApp, souvent invisibles autrement.",
        place="au clic sur le bouton ou le lien WhatsApp",
    ),
    _auto_event(
        item_id="event_file_download",
        event="file_download",
        applies_to=_LEAD,
        weight=40,
        title="Téléchargement de document",
        why="Brochures et catalogues téléchargés signalent un visiteur sérieux.",
        guide=(
            "Dans GA4 : Administration > Flux de données > ton flux web > « Mesures améliorées ».",
            "Vérifie que l'option « Téléchargements de fichiers » est activée.",
            "Télécharge un PDF sur ton site, puis clique sur « Vérifier maintenant » le lendemain.",
        ),
    ),
    # --- SaaS ---------------------------------------------------------------
    _event(
        event="sign_up",
        applies_to=_SAAS,
        weight=95,
        title="Création de compte",
        why=(
            "C'est ta conversion principale : elle te dit quelles sources de trafic amènent de "
            "vrais utilisateurs."
        ),
        place="après la création réussie du compte",
        quick_win=True,
    ),
    _event(
        event="login",
        applies_to=_SAAS,
        weight=60,
        title="Connexion",
        why="Elle montre combien d'utilisateurs reviennent, un signal clé de rétention.",
        place="après une connexion réussie",
    ),
    _event(
        event="begin_trial",
        applies_to=_SAAS,
        weight=80,
        title="Démarrage d'un essai",
        why="Il mesure le passage de l'inscription à l'essai réel de ton produit.",
        place="au démarrage effectif de l'essai gratuit",
    ),
    _event(
        event="subscribe",
        applies_to=_SAAS,
        weight=90,
        title="Abonnement payant",
        why="C'est le moment où un utilisateur devient un client : sans lui, pas de rentabilité mesurable.",
        place="après la souscription à une offre payante",
    ),
    _event(
        event="tutorial_complete",
        applies_to=_SAAS,
        weight=50,
        title="Onboarding terminé",
        why="Les utilisateurs qui terminent l'onboarding restent plus longtemps : suis-le pour l'améliorer.",
        place="quand l'utilisateur termine les premières étapes guidées",
    ),
    # --- Contenu ------------------------------------------------------------
    _event(
        event="newsletter_signup",
        applies_to=_CONTENT,
        weight=80,
        title="Inscription à la newsletter",
        why="C'est la conversion principale d'un site de contenu : elle transforme un lecteur en audience.",
        place="après l'inscription réussie à la newsletter",
        quick_win=True,
    ),
    _auto_event(
        item_id="event_outbound_click",
        event="click",
        applies_to=_CONTENT,
        weight=40,
        title="Clics vers d'autres sites",
        why="Il montre vers quels sites tes lecteurs partent, utile pour tes partenariats et affiliations.",
        guide=(
            "Dans GA4 : Administration > Flux de données > ton flux web > « Mesures améliorées ».",
            "Vérifie que l'option « Clics sortants » est activée.",
            "Clique sur un lien externe de ton site, puis « Vérifier maintenant » le lendemain.",
        ),
    ),
    _auto_event(
        item_id="event_site_search",
        event="view_search_results",
        applies_to=_CONTENT,
        weight=35,
        title="Recherche interne",
        why="Ce que tes visiteurs cherchent te dit quel contenu il te manque.",
        guide=(
            "Dans GA4 : Administration > Flux de données > ton flux web > « Mesures améliorées ».",
            "Active « Recherche sur le site » et vérifie le paramètre d'URL de recherche (souvent « q » ou « s »).",
            "Fais une recherche sur ton site, puis « Vérifier maintenant » le lendemain.",
        ),
    ),
    _event(
        event="share",
        applies_to=_CONTENT,
        weight=30,
        title="Partage d'un contenu",
        why="Le partage mesure les contenus qui se diffusent d'eux-mêmes.",
        place="au clic sur un bouton de partage",
    ),
)

_CONVERSIONS: tuple[MeasurementItem, ...] = (
    MeasurementItem(
        id="key_events_marked",
        layer="conversions",
        applies_to=None,
        weight=90,
        quick_win=True,
        title="Événements clés (conversions) déclarés dans GA4",
        why=(
            "Tant qu'un événement n'est pas marqué comme « événement clé », GA4 ne le compte "
            "pas comme une conversion : les rapports et Google Ads ne s'en servent pas."
        ),
        check="key_events",
        arg=None,
        max_level="received",
        guide=(
            "Dans GA4 : Administration > Événements (ou « Événements clés »).",
            "Repère ton événement principal (achat, demande de contact, inscription).",
            "Active « Marquer comme événement clé ».",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="conversion_value",
        layer="conversions",
        applies_to=_LEAD_SAAS,
        weight=50,
        quick_win=False,
        title="Valeur attribuée à tes conversions",
        why=(
            "Donner une valeur (même estimée) à un contact ou une inscription permet de "
            "comparer les sources de trafic par rentabilité et d'optimiser les campagnes."
        ),
        check="key_events_value",
        arg=None,
        max_level="received",
        guide=(
            "Estime la valeur moyenne d'une conversion (par exemple 50 € par contact).",
            "Dans GA4 > Événements clés, ouvre ton événement principal et renseigne la valeur "
            "par défaut.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
)

_ADS: tuple[MeasurementItem, ...] = (
    MeasurementItem(
        id="ads_ga4_link",
        layer="ads",
        applies_to=None,
        weight=70,
        quick_win=True,
        title="GA4 lié à Google Ads",
        why=(
            "Le lien permet à Google Ads de voir les conversions GA4 et de créer des audiences "
            "de remarketing à partir de tes visiteurs."
        ),
        check="ads_link",
        arg=None,
        max_level="received",
        guide=(
            "Dans GA4 : Administration > Association de produits > Liens Google Ads.",
            "Clique sur « Associer », choisis ton compte Google Ads et active la "
            "personnalisation des annonces.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="ads_conversion_tag",
        layer="ads",
        applies_to=None,
        weight=75,
        quick_win=False,
        title="Balise de conversion Google Ads",
        why=(
            "Elle indique à Google Ads quelles annonces ont mené à une vente ou un contact ; "
            "sans elle, les campagnes ne peuvent pas s'améliorer."
        ),
        check="ads_conversion_tag",
        arg=None,
        max_level="on_page",
        guide=(
            "Dans Google Ads : Objectifs > Conversions > Nouvelle action de conversion, choisis "
            "« Site web ».",
            "Note l'ID de conversion (AW-…) et le libellé de conversion.",
            "Saisis-les dans « Réglages Ads » (sous « Pour aller plus loin »), génère un "
            "« Conteneur GTM personnalisé » et "
            "importe-le dans GTM.",
            "Clique sur « Vérifier maintenant » avec « en conditions réelles ».",
        ),
        actions=("guide", "gtm_container", "advisor"),
    ),
    MeasurementItem(
        id="ads_conversion_linker",
        layer="ads",
        applies_to=None,
        weight=55,
        quick_win=False,
        title="Conversion Linker",
        why=(
            "Il conserve l'origine de la visite publicitaire (clic sur une annonce) pour que la "
            "conversion lui soit bien attribuée, malgré les restrictions des navigateurs."
        ),
        check="manual",
        arg=None,
        max_level="on_page",
        guide=(
            "Dans GTM, crée une balise « Conversion Linker » déclenchée sur toutes les pages "
            "(elle est incluse dans un « Conteneur GTM personnalisé » si tu coches cette ligne).",
            "Publie le conteneur.",
            "Marque cette ligne comme faite.",
        ),
        actions=("guide", "gtm_container", "advisor"),
    ),
    MeasurementItem(
        id="ads_auto_tagging",
        layer="ads",
        applies_to=None,
        weight=60,
        quick_win=True,
        title="Balisage automatique (gclid)",
        why=(
            "Il ajoute un identifiant à chaque clic sur ton annonce ; sans lui, Google Ads ne "
            "peut pas relier les visites à tes conversions."
        ),
        check="manual",
        arg=None,
        max_level="on_page",
        guide=(
            "Dans Google Ads : Administration > Paramètres du compte > Suivi.",
            "Active « Balisage automatique du résultat des URL finales ».",
            "Marque cette ligne comme faite.",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="ads_remarketing",
        layer="ads",
        applies_to=None,
        weight=45,
        quick_win=False,
        title="Audiences de remarketing",
        why=(
            "Elles permettent de re-cibler les visiteurs qui n'ont pas converti, souvent le "
            "levier le moins cher pour ramener des clients."
        ),
        check="manual",
        arg=None,
        max_level="on_page",
        guide=(
            "Dans GA4 : Administration > Audiences > Nouvelle audience.",
            "Crée par exemple « Visiteurs ayant ajouté au panier sans acheter ».",
            "Vérifie que l'audience est partagée avec Google Ads (lien GA4 - Ads).",
            "Marque cette ligne comme faite.",
        ),
        actions=("guide", "advisor"),
    ),
)

_SEO: tuple[MeasurementItem, ...] = (
    MeasurementItem(
        id="gsc_property_linked",
        layer="seo",
        applies_to=None,
        weight=80,
        quick_win=True,
        title="Search Console connectée",
        why=(
            "Search Console te dit quelles pages Google indexe et sur quelles recherches tu "
            "apparais : sans elle, ton SEO est aveugle."
        ),
        check="gsc_linked",
        arg=None,
        max_level="received",
        guide=(
            "Vérifie ton site sur search.google.com/search-console (propriété de domaine).",
            "Dans « Connexions Google » de la plateforme, connecte ton compte puis choisis la "
            "propriété.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="gsc_sitemaps",
        layer="seo",
        applies_to=None,
        weight=60,
        quick_win=True,
        title="Sitemap envoyé à Google",
        why=(
            "Le sitemap liste les pages à indexer ; sans lui, Google peut mettre longtemps à "
            "découvrir tes nouvelles pages."
        ),
        check="gsc_sitemaps",
        arg=None,
        max_level="received",
        guide=(
            "Génère ou repère l'adresse de ton sitemap (souvent /sitemap.xml).",
            "Dans Search Console : Sitemaps > ajoute cette adresse.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="robots_txt",
        layer="seo",
        applies_to=None,
        weight=40,
        quick_win=True,
        title="robots.txt accessible",
        why=(
            "Ce fichier dit aux robots ce qu'ils peuvent explorer ; s'il est absent ou en "
            "erreur, l'exploration peut être perturbée."
        ),
        check="robots",
        arg=None,
        max_level="on_page",
        guide=(
            "Crée un fichier robots.txt à la racine du site (https://ton-site/robots.txt).",
            "Il doit répondre normalement (code 200) et pointer vers ton sitemap.",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
    MeasurementItem(
        id="tls_valid",
        layer="seo",
        applies_to=None,
        weight=85,
        quick_win=True,
        title="Certificat HTTPS valide",
        why=(
            "Sans certificat valide, les navigateurs affichent un avertissement qui fait fuir "
            "les visiteurs et pénalise ton référencement."
        ),
        check="tls",
        arg=None,
        max_level="on_page",
        guide=(
            "Renouvelle le certificat chez ton hébergeur.",
            "Active le renouvellement automatique (par exemple Let's Encrypt).",
            "Clique sur « Vérifier maintenant ».",
        ),
        actions=("guide", "advisor"),
    ),
)

ITEMS: tuple[MeasurementItem, ...] = (
    *_FOUNDATIONS,
    *_EVENTS,
    *_CONVERSIONS,
    *_ADS,
    *_SEO,
)
ITEMS_BY_ID: dict[str, MeasurementItem] = {item.id: item for item in ITEMS}


# Sélection recommandée pour le conteneur GTM « pack de démarrage », par type de site.
# `ga4_tag` est toujours ajouté en tête par `starter_pack`. Seuls des items qui peuvent
# entrer dans un conteneur GTM (action `gtm_container`) figurent ici.
STARTER_PACKS: dict[str, tuple[str, ...]] = {
    "ecommerce": (
        "event_view_item",
        "event_add_to_cart",
        "event_begin_checkout",
        "event_purchase",
    ),
    "lead_gen": (
        "event_generate_lead",
        "event_click_to_call",
        "event_click_email",
        "event_click_whatsapp",
    ),
    "saas": ("event_sign_up", "event_login", "event_begin_trial", "event_subscribe"),
    "content": ("event_newsletter_signup",),
    "other": (),
}


def starter_pack(types: tuple[str, ...] | list[str]) -> list[str]:
    """Items du pack de démarrage pour ces types de site, sans doublon."""
    item_ids = ["ga4_tag"]
    for site_type in types:
        for item_id in STARTER_PACKS.get(site_type, ()):
            if item_id not in item_ids:
                item_ids.append(item_id)
    return item_ids


def is_applicable(
    item: MeasurementItem, types: tuple[str, ...] | list[str], uses_google_ads: bool | None
) -> bool:
    """Vrai si l'item concerne le site : types effectifs et réglage « publicité ».

    La couche publicité n'est proposée que si l'utilisateur a indiqué faire de la
    publicité Google Ads (`uses_google_ads is True`) : un novice n'a pas à la voir."""
    if item.layer == "ads" and uses_google_ads is not True:
        return False
    if item.applies_to is None:
        return True
    return bool(set(types) & set(item.applies_to))
