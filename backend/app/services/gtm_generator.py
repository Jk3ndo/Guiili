"""Generateur de conteneur GTM au format natif « Import Container »
(``exportFormatVersion: 2``). Zero API en ecriture : l'utilisateur importe
lui-meme le fichier via Admin > Importer un conteneur.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.models.enums import StackKind

ImportMode = Literal["merge", "overwrite"]

# Declencheur natif « All Pages » de GTM (id reserve, identique partout).
_ALL_PAGES_TRIGGER_ID = "2147479553"
_SPA_STACKS = frozenset({StackKind.NEXTJS, StackKind.NUXT, StackKind.ANGULAR, StackKind.VUE})
_FINGERPRINT = "1700000000000"

_IMPORT_METADATA: dict[ImportMode, dict] = {
    "merge": {
        "mode": "merge",
        "recommended": True,
        "gtm_option": "Fusionner",
        "conflict_option": "Renommer les conflits",
        "steps": [
            "GTM > Administration > Importer un conteneur.",
            "Selectionnez ce fichier JSON.",
            "Espace de travail : « Nouveau ».",
            "Option d'import : « Fusionner », puis « Renommer les conflits ».",
            "Verifiez en mode Apercu, remplacez G-XXXXXXXXXX, puis publiez.",
        ],
    },
    "overwrite": {
        "mode": "overwrite",
        "recommended": False,
        "gtm_option": "Ecraser",
        "conflict_option": None,
        "steps": [
            "GTM > Administration > Importer un conteneur.",
            "Selectionnez ce fichier JSON.",
            "Option d'import : « Ecraser » — REMPLACE toute la configuration existante.",
            "A n'utiliser que sur un conteneur neuf ou de test.",
        ],
    },
}


def _short_code(seed: str, length: int) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")[:length]


def _numeric_id(seed: str, length: int) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return str(int(digest, 16))[:length]


def _built_in_variables(base: dict) -> list[dict]:
    names = [
        ("pageUrl", "Page URL"),
        ("pageHostname", "Page Hostname"),
        ("pagePath", "Page Path"),
        ("referrer", "Referrer"),
        ("event", "Event"),
        ("historySource", "History Source"),
        ("newHistoryFragment", "New History Fragment"),
        ("oldHistoryFragment", "Old History Fragment"),
        ("clickElement", "Click Element"),
        ("clickUrl", "Click URL"),
        ("clickClasses", "Click Classes"),
        ("clickText", "Click Text"),
    ]
    return [{**base, "type": kind, "name": name} for kind, name in names]


def _dlv_variable(base: dict, variable_id: str, name: str, key: str) -> dict:
    return {
        **base,
        "variableId": variable_id,
        "name": name,
        "type": "v",
        "parameter": [
            {"type": "integer", "key": "dataLayerVersion", "value": "2"},
            {"type": "boolean", "key": "setDefaultValue", "value": "false"},
            {"type": "template", "key": "name", "value": key},
        ],
        "fingerprint": _FINGERPRINT,
    }


def _custom_event_trigger(base: dict, trigger_id: str, name: str, event_name: str) -> dict:
    return {
        **base,
        "triggerId": trigger_id,
        "name": name,
        "type": "customEvent",
        "customEventFilter": [
            {
                "type": "equals",
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{_event}}"},
                    {"type": "template", "key": "arg1", "value": event_name},
                ],
            }
        ],
        "fingerprint": _FINGERPRINT,
    }


def _ga4_event_tag(
    base: dict,
    tag_id: str,
    name: str,
    event_name: str,
    firing_trigger_id: str,
    *,
    ecommerce: bool = False,
    extra_params: list[dict] | None = None,
) -> dict:
    parameter: list[dict] = [
        {"type": "template", "key": "eventName", "value": event_name},
        {
            "type": "tagReference",
            "key": "measurementId",
            "value": "GA4 Configuration",
        },
    ]
    if ecommerce:
        parameter += [
            {"type": "boolean", "key": "sendEcommerceData", "value": "true"},
            {
                "type": "template",
                "key": "getEcommerceDataFrom",
                "value": "dataLayer",
            },
        ]
    if extra_params:
        parameter += extra_params
    return {
        **base,
        "tagId": tag_id,
        "name": name,
        "type": "gaawe",
        "parameter": parameter,
        "fingerprint": _FINGERPRINT,
        "firingTriggerId": [firing_trigger_id],
        "tagFiringOption": "oncePerEvent",
        "consentSettings": {"consentStatus": "notSet"},
    }


def build_gtm_container(
    *,
    domain: str,
    stack: StackKind = StackKind.UNKNOWN,
    ga4_measurement_id: str | None = None,
    ga4_property: str | None = None,
    import_mode: ImportMode = "merge",
    export_time: str | None = None,
) -> dict:
    if import_mode not in _IMPORT_METADATA:
        raise ValueError(f"import_mode inconnu : {import_mode!r}")

    account_id = _numeric_id(f"acct:{domain}", 10)
    container_id = _numeric_id(f"cont:{domain}", 9)
    public_id = f"GTM-{_short_code(domain, 7)}"
    base = {"accountId": account_id, "containerId": container_id}
    measurement_id = ga4_measurement_id or "G-XXXXXXXXXX"
    is_spa = stack in _SPA_STACKS

    triggers: list[dict] = [
        _custom_event_trigger(base, "10", "CE - purchase", "purchase"),
        _custom_event_trigger(base, "11", "CE - generate_lead", "generate_lead"),
        {
            **base,
            "triggerId": "12",
            "name": "Clic sortant",
            "type": "linkClick",
            "waitForTags": [{"type": "boolean", "key": "waitForTags", "value": "false"}],
            "checkValidation": [{"type": "boolean", "key": "checkValidation", "value": "false"}],
            "filter": [
                {
                    "type": "doesNotContain",
                    "parameter": [
                        {"type": "template", "key": "arg0", "value": "{{Click URL}}"},
                        {"type": "template", "key": "arg1", "value": domain},
                    ],
                }
            ],
            "fingerprint": _FINGERPRINT,
        },
    ]
    config_triggers = [_ALL_PAGES_TRIGGER_ID]
    if is_spa:
        triggers.append(
            {
                **base,
                "triggerId": "13",
                "name": "History Change (SPA)",
                "type": "historyChange",
                "fingerprint": _FINGERPRINT,
            }
        )
        config_triggers.append("13")

    tags: list[dict] = [
        {
            **base,
            "tagId": "1",
            "name": "GA4 Configuration",
            "type": "googtag",
            "parameter": [
                {"type": "template", "key": "tagId", "value": measurement_id},
                {
                    "type": "list",
                    "key": "configSettingsTable",
                    "list": [
                        {
                            "type": "map",
                            "map": [
                                {
                                    "type": "template",
                                    "key": "parameter",
                                    "value": "send_page_view",
                                },
                                {
                                    "type": "template",
                                    "key": "parameterValue",
                                    "value": "true",
                                },
                            ],
                        }
                    ],
                },
            ],
            "fingerprint": _FINGERPRINT,
            "firingTriggerId": config_triggers,
            "tagFiringOption": "oncePerEvent",
            "monitoringMetadata": {"type": "map"},
            "consentSettings": {"consentStatus": "notSet"},
        },
        _ga4_event_tag(base, "2", "GA4 - purchase", "purchase", "10", ecommerce=True),
        _ga4_event_tag(
            base,
            "3",
            "GA4 - generate_lead",
            "generate_lead",
            "11",
            extra_params=[
                {
                    "type": "list",
                    "key": "eventParameters",
                    "list": [
                        {
                            "type": "map",
                            "map": [
                                {"type": "template", "key": "name", "value": "form_id"},
                                {
                                    "type": "template",
                                    "key": "value",
                                    "value": "{{dlv - form_id}}",
                                },
                            ],
                        }
                    ],
                }
            ],
        ),
        _ga4_event_tag(
            base,
            "4",
            "GA4 - outbound_click",
            "click",
            "12",
            extra_params=[
                {
                    "type": "list",
                    "key": "eventParameters",
                    "list": [
                        {
                            "type": "map",
                            "map": [
                                {"type": "template", "key": "name", "value": "link_url"},
                                {
                                    "type": "template",
                                    "key": "value",
                                    "value": "{{Click URL}}",
                                },
                            ],
                        }
                    ],
                }
            ],
        ),
    ]

    variables = [
        _dlv_variable(base, "1", "dlv - value", "ecommerce.value"),
        _dlv_variable(base, "2", "dlv - currency", "ecommerce.currency"),
        _dlv_variable(base, "3", "dlv - items", "ecommerce.items"),
        _dlv_variable(base, "4", "dlv - form_id", "form_id"),
        {
            **base,
            "variableId": "5",
            "name": "Const - GA4 Measurement ID",
            "type": "c",
            "parameter": [{"type": "template", "key": "value", "value": measurement_id}],
            "fingerprint": _FINGERPRINT,
        },
    ]

    manager_url = (
        f"https://tagmanager.google.com/#/container/accounts/{account_id}"
        f"/containers/{container_id}/workspaces?apiLink=container"
    )
    property_note = f" Propriete GA4 liee : {ga4_property}." if ga4_property else ""
    description = (
        f"Genere par Control Center pour {domain}. "
        f"Import : {_IMPORT_METADATA[import_mode]['gtm_option']}. "
        f"Remplacez {measurement_id} par l'ID de flux de votre propriete GA4."
        f"{property_note}"
    )

    return {
        "exportFormatVersion": 2,
        "exportTime": export_time or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "containerVersion": {
            "path": f"accounts/{account_id}/containers/{container_id}/versions/0",
            **base,
            "containerVersionId": "0",
            "name": f"Control Center - {domain}",
            "description": description,
            "container": {
                "path": f"accounts/{account_id}/containers/{container_id}",
                **base,
                "name": domain,
                "publicId": public_id,
                "usageContext": ["WEB"],
                "fingerprint": _FINGERPRINT,
                "tagManagerUrl": manager_url,
                "features": {
                    "supportUserPermissions": True,
                    "supportEnvironments": True,
                    "supportWorkspaces": True,
                    "supportGtagConfigs": True,
                },
            },
            "tag": tags,
            "trigger": triggers,
            "variable": variables,
            "builtInVariable": _built_in_variables(base),
            "fingerprint": _FINGERPRINT,
            "tagManagerUrl": manager_url,
        },
        "importMetadata": _IMPORT_METADATA[import_mode],
    }


def import_metadata(mode: ImportMode) -> dict:
    if mode not in _IMPORT_METADATA:
        raise ValueError(f"import_mode inconnu : {mode!r}")
    return _IMPORT_METADATA[mode]


# --------------------------------------------------------------------------- #
#  Conteneur sur mesure (plan de mesure)                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Recipe:
    event: str
    kind: str  # "custom_event" | "link_click"
    ecommerce: bool = False
    params: tuple[tuple[str, str], ...] = ()  # (paramètre GA4, variable dataLayer)
    link_op: str | None = None  # opérateur de filtre GTM pour "link_click"
    link_value: str | None = None


_RECIPES: dict[str, _Recipe] = {
    "event_view_item": _Recipe("view_item", "custom_event", ecommerce=True),
    "event_add_to_cart": _Recipe("add_to_cart", "custom_event", ecommerce=True),
    "event_begin_checkout": _Recipe("begin_checkout", "custom_event", ecommerce=True),
    "event_purchase": _Recipe("purchase", "custom_event", ecommerce=True),
    "event_generate_lead": _Recipe(
        "generate_lead", "custom_event", params=(("form_id", "{{dlv - form_id}}"),)
    ),
    "event_sign_up": _Recipe("sign_up", "custom_event"),
    "event_login": _Recipe("login", "custom_event"),
    "event_begin_trial": _Recipe("begin_trial", "custom_event"),
    "event_subscribe": _Recipe("subscribe", "custom_event"),
    "event_tutorial_complete": _Recipe("tutorial_complete", "custom_event"),
    "event_newsletter_signup": _Recipe("newsletter_signup", "custom_event"),
    "event_share": _Recipe("share", "custom_event"),
    "event_click_to_call": _Recipe(
        "click_to_call",
        "link_click",
        params=(("link_url", "{{Click URL}}"),),
        link_op="startsWith",
        link_value="tel:",
    ),
    "event_click_email": _Recipe(
        "click_email",
        "link_click",
        params=(("link_url", "{{Click URL}}"),),
        link_op="startsWith",
        link_value="mailto:",
    ),
    "event_click_whatsapp": _Recipe(
        "click_whatsapp",
        "link_click",
        params=(("link_url", "{{Click URL}}"),),
        link_op="contains",
        link_value="wa.me",
    ),
}

# Événements sur lesquels déclencher la conversion Ads, par ordre de préférence.
_ADS_KEY_EVENTS = ("event_purchase", "event_generate_lead", "event_sign_up", "event_subscribe")


def _event_params(params: tuple[tuple[str, str], ...]) -> list[dict] | None:
    if not params:
        return None
    return [
        {
            "type": "list",
            "key": "eventParameters",
            "list": [
                {
                    "type": "map",
                    "map": [
                        {"type": "template", "key": "name", "value": name},
                        {"type": "template", "key": "value", "value": value},
                    ],
                }
                for name, value in params
            ],
        }
    ]


def _link_click_trigger(base: dict, trigger_id: str, recipe: _Recipe) -> dict:
    return {
        **base,
        "triggerId": trigger_id,
        "name": f"Clic - {recipe.event}",
        "type": "linkClick",
        "waitForTags": [{"type": "boolean", "key": "waitForTags", "value": "false"}],
        "checkValidation": [{"type": "boolean", "key": "checkValidation", "value": "false"}],
        "filter": [
            {
                "type": recipe.link_op,
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{Click URL}}"},
                    {"type": "template", "key": "arg1", "value": recipe.link_value},
                ],
            }
        ],
        "fingerprint": _FINGERPRINT,
    }


def requires_site_code(item_id: str) -> bool:
    """Vrai si l'événement n'existera que si le site pousse lui-même l'événement dans le
    dataLayer (le conteneur ne fait que l'écouter). Les clics sur liens téléphone, e-mail
    et WhatsApp sont détectés par GTM seul."""
    recipe = _RECIPES.get(item_id)
    return recipe is not None and recipe.kind == "custom_event"


def build_selected_container(
    *,
    domain: str,
    stack: StackKind = StackKind.UNKNOWN,
    item_ids: list[str],
    ga4_measurement_id: str | None,
    ads_conversion_id: str | None,
    ads_conversion_label: str | None,
    import_mode: ImportMode = "merge",
    export_time: str | None = None,
) -> tuple[dict, list[str]]:
    """Conteneur GTM limité aux items choisis. Renvoie `(conteneur, avertissements)`."""
    if import_mode not in _IMPORT_METADATA:
        raise ValueError(f"import_mode inconnu : {import_mode!r}")

    selected = set(item_ids)
    warnings: list[str] = []
    account_id = _numeric_id(f"acct:{domain}", 10)
    container_id = _numeric_id(f"cont:{domain}", 9)
    public_id = f"GTM-{_short_code(domain, 7)}"
    base = {"accountId": account_id, "containerId": container_id}

    measurement_id = ga4_measurement_id or "G-XXXXXXXXXX"
    if not ga4_measurement_id:
        warnings.append(
            "ID de mesure GA4 inconnu : remplace G-XXXXXXXXXX par l'ID de ton flux de données "
            "avant de publier (ou connecte GA4 pour qu'il soit renseigné automatiquement)."
        )

    recipes = [(item_id, _RECIPES[item_id]) for item_id in item_ids if item_id in _RECIPES]
    wants_config = "ga4_tag" in selected or bool(recipes)

    triggers: list[dict] = []
    tags: list[dict] = []
    next_trigger = 10
    next_tag = 2
    trigger_by_item: dict[str, str] = {}

    if wants_config:
        config_triggers = [_ALL_PAGES_TRIGGER_ID]
        if stack in _SPA_STACKS:
            triggers.append(
                {
                    **base,
                    "triggerId": str(next_trigger),
                    "name": "History Change (SPA)",
                    "type": "historyChange",
                    "fingerprint": _FINGERPRINT,
                }
            )
            config_triggers.append(str(next_trigger))
            next_trigger += 1
        tags.append(
            {
                **base,
                "tagId": "1",
                "name": "GA4 Configuration",
                "type": "googtag",
                "parameter": [
                    {"type": "template", "key": "tagId", "value": measurement_id},
                    {
                        "type": "list",
                        "key": "configSettingsTable",
                        "list": [
                            {
                                "type": "map",
                                "map": [
                                    {
                                        "type": "template",
                                        "key": "parameter",
                                        "value": "send_page_view",
                                    },
                                    {
                                        "type": "template",
                                        "key": "parameterValue",
                                        "value": "true",
                                    },
                                ],
                            }
                        ],
                    },
                ],
                "fingerprint": _FINGERPRINT,
                "firingTriggerId": config_triggers,
                "tagFiringOption": "oncePerEvent",
                "monitoringMetadata": {"type": "map"},
                "consentSettings": {"consentStatus": "notSet"},
            }
        )

    for item_id, recipe in recipes:
        trigger_id = str(next_trigger)
        next_trigger += 1
        if recipe.kind == "link_click":
            triggers.append(_link_click_trigger(base, trigger_id, recipe))
        else:
            triggers.append(
                _custom_event_trigger(base, trigger_id, f"CE - {recipe.event}", recipe.event)
            )
        trigger_by_item[item_id] = trigger_id
        tags.append(
            _ga4_event_tag(
                base,
                str(next_tag),
                f"GA4 - {recipe.event}",
                recipe.event,
                trigger_id,
                ecommerce=recipe.ecommerce,
                extra_params=_event_params(recipe.params),
            )
        )
        next_tag += 1

    ads_selected = "ads_conversion_tag" in selected
    if ads_selected:
        numeric_id = (ads_conversion_id or "").removeprefix("AW-")
        key_event = next((k for k in _ADS_KEY_EVENTS if k in trigger_by_item), None)
        if not numeric_id or not ads_conversion_label:
            warnings.append(
                "Balise Ads ignorée : renseigne l'ID de conversion (AW-…) et le libellé dans "
                "« Réglages Ads »."
            )
        elif key_event is None:
            warnings.append(
                "Balise Ads ignorée : sélectionne aussi ton événement clé (achat, demande de "
                "contact, inscription ou abonnement) pour que la conversion se déclenche."
            )
        else:
            parameter = [
                {"type": "template", "key": "conversionId", "value": numeric_id},
                {"type": "template", "key": "conversionLabel", "value": ads_conversion_label},
            ]
            if _RECIPES[key_event].ecommerce:
                parameter += [
                    {"type": "template", "key": "conversionValue", "value": "{{dlv - value}}"},
                    {"type": "template", "key": "currencyCode", "value": "{{dlv - currency}}"},
                ]
            tags.append(
                {
                    **base,
                    "tagId": str(next_tag),
                    "name": "Google Ads - Conversion",
                    "type": "awct",
                    "parameter": parameter,
                    "fingerprint": _FINGERPRINT,
                    "firingTriggerId": [trigger_by_item[key_event]],
                    "tagFiringOption": "oncePerEvent",
                    "consentSettings": {"consentStatus": "notSet"},
                }
            )
            next_tag += 1

    ads_tag_added = any(t["name"] == "Google Ads - Conversion" for t in tags)
    if "ads_conversion_linker" in selected or ads_tag_added:
        tags.append(
            {
                **base,
                "tagId": str(next_tag),
                "name": "Conversion Linker",
                "type": "gclidw",
                "parameter": [],
                "fingerprint": _FINGERPRINT,
                "firingTriggerId": [_ALL_PAGES_TRIGGER_ID],
                "tagFiringOption": "oncePerEvent",
                "consentSettings": {"consentStatus": "notSet"},
            }
        )
        next_tag += 1

    variables = [
        _dlv_variable(base, "1", "dlv - value", "ecommerce.value"),
        _dlv_variable(base, "2", "dlv - currency", "ecommerce.currency"),
        _dlv_variable(base, "3", "dlv - items", "ecommerce.items"),
        _dlv_variable(base, "4", "dlv - form_id", "form_id"),
        {
            **base,
            "variableId": "5",
            "name": "Const - GA4 Measurement ID",
            "type": "c",
            "parameter": [{"type": "template", "key": "value", "value": measurement_id}],
            "fingerprint": _FINGERPRINT,
        },
    ]

    manager_url = (
        f"https://tagmanager.google.com/#/container/accounts/{account_id}"
        f"/containers/{container_id}/workspaces?apiLink=container"
    )
    description = (
        f"Genere par Control Center pour {domain} (plan de mesure). "
        f"Import : {_IMPORT_METADATA[import_mode]['gtm_option']}. "
        "Verifiez en mode Apercu avant de publier."
    )

    container = {
        "exportFormatVersion": 2,
        "exportTime": export_time or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "containerVersion": {
            "path": f"accounts/{account_id}/containers/{container_id}/versions/0",
            **base,
            "containerVersionId": "0",
            "name": f"Control Center - plan de mesure - {domain}",
            "description": description,
            "container": {
                "path": f"accounts/{account_id}/containers/{container_id}",
                **base,
                "name": domain,
                "publicId": public_id,
                "usageContext": ["WEB"],
                "fingerprint": _FINGERPRINT,
                "tagManagerUrl": manager_url,
                "features": {
                    "supportUserPermissions": True,
                    "supportEnvironments": True,
                    "supportWorkspaces": True,
                    "supportGtagConfigs": True,
                },
            },
            "tag": tags,
            "trigger": triggers,
            "variable": variables,
            "builtInVariable": _built_in_variables(base),
            "fingerprint": _FINGERPRINT,
            "tagManagerUrl": manager_url,
        },
        "importMetadata": _IMPORT_METADATA[import_mode],
    }
    return container, warnings
