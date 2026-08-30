"""Generateur de conteneur GTM au format natif « Import Container »
(``exportFormatVersion: 2``). Zero API en ecriture : l'utilisateur importe
lui-meme le fichier via Admin > Importer un conteneur.
"""

from __future__ import annotations

import base64
import hashlib
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
