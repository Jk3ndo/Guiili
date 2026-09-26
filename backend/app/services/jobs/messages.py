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
    "job_lease_lost": "La tâche a été reprise par une autre exécution.",
    # Côté exploitation (jamais « reconnecte » ni « ton site ») : le client n'y peut rien.
    "db_transient": "Base de données momentanément indisponible : nouvel essai automatique.",
    "api_key_rejected": "Notre accès au service de mesure est refusé : nous sommes prévenus.",
    "token_refresh_failed": (
        "Le renouvellement de l'accès Google a échoué momentanément : nouvel essai automatique."
    ),
    "truncated": "Réponse Google trop volumineuse pour être collectée en entier : nous sommes prévenus.",
    "bad_request": "Requête refusée par le service : nous sommes prévenus.",
    "internal_error": _UNKNOWN,
    "unknown_kind": _UNKNOWN,
    "bad_params": _UNKNOWN,
}


def error_message(code: str | None) -> str | None:
    if code is None:
        return None
    return ERROR_MESSAGES.get(code, _UNKNOWN)
