"""Conteneur GTM : conformite au format Import Container v2."""

import json

import pytest

from app.models.enums import StackKind
from app.services.gtm_generator import build_gtm_container, import_metadata


def _container(**kw):
    return build_gtm_container(domain="boutique-verte.fr", **kw)


def test_top_level_shape() -> None:
    c = _container(stack=StackKind.NEXTJS)
    assert c["exportFormatVersion"] == 2
    assert "exportTime" in c
    cv = c["containerVersion"]
    assert set(cv) >= {
        "path",
        "accountId",
        "containerId",
        "containerVersionId",
        "container",
        "tag",
        "trigger",
        "variable",
        "builtInVariable",
    }
    assert isinstance(cv["tag"], list)
    assert isinstance(cv["trigger"], list)
    assert isinstance(cv["variable"], list)


def test_container_metadata() -> None:
    cv = _container()["containerVersion"]["container"]
    assert cv["usageContext"] == ["WEB"]
    assert cv["publicId"].startswith("GTM-")
    assert cv["name"] == "boutique-verte.fr"


def test_json_serialisable() -> None:
    dumped = json.dumps(_container(stack=StackKind.WORDPRESS))
    assert json.loads(dumped)["exportFormatVersion"] == 2


def test_ga4_configuration_tag_present() -> None:
    tags = {t["name"]: t for t in _container()["containerVersion"]["tag"]}
    assert tags["GA4 Configuration"]["type"] == "googtag"
    params = {p["key"]: p for p in tags["GA4 Configuration"]["parameter"]}
    assert params["tagId"]["value"] == "G-XXXXXXXXXX"


def test_ecommerce_event_tags_wired_to_triggers() -> None:
    cv = _container()["containerVersion"]
    triggers = {t["triggerId"]: t for t in cv["trigger"]}
    tags = {t["name"]: t for t in cv["tag"]}

    purchase = tags["GA4 - purchase"]
    assert purchase["type"] == "gaawe"
    (trigger_id,) = purchase["firingTriggerId"]
    assert triggers[trigger_id]["type"] == "customEvent"
    ce_filter = triggers[trigger_id]["customEventFilter"][0]["parameter"]
    assert {"type": "template", "key": "arg1", "value": "purchase"} in ce_filter

    lead = tags["GA4 - generate_lead"]
    (lead_trigger,) = lead["firingTriggerId"]
    assert triggers[lead_trigger]["name"] == "CE - generate_lead"


def test_datalayer_variables_present() -> None:
    names = {v["name"] for v in _container()["containerVersion"]["variable"]}
    assert {"dlv - value", "dlv - currency", "dlv - items"} <= names


def test_history_change_only_for_spa() -> None:
    spa = _container(stack=StackKind.NUXT)["containerVersion"]
    assert any(t["type"] == "historyChange" for t in spa["trigger"])
    config = next(t for t in spa["tag"] if t["name"] == "GA4 Configuration")
    history_ids = [t["triggerId"] for t in spa["trigger"] if t["type"] == "historyChange"]
    assert set(history_ids) <= set(config["firingTriggerId"])

    wp = _container(stack=StackKind.WORDPRESS)["containerVersion"]
    assert not any(t["type"] == "historyChange" for t in wp["trigger"])


def test_outbound_click_trigger_present() -> None:
    triggers = _container()["containerVersion"]["trigger"]
    outbound = next(t for t in triggers if t["type"] == "linkClick")
    needle = outbound["filter"][0]["parameter"][1]["value"]
    assert needle == "boutique-verte.fr"


def test_referential_integrity_of_firing_triggers() -> None:
    cv = _container(stack=StackKind.NEXTJS)["containerVersion"]
    trigger_ids = {t["triggerId"] for t in cv["trigger"]} | {"2147479553"}
    for tag in cv["tag"]:
        for trigger_id in tag.get("firingTriggerId", []):
            assert trigger_id in trigger_ids, f"{tag['name']} -> {trigger_id} orphelin"


@pytest.mark.parametrize("mode", ["merge", "overwrite"])
def test_import_mode_metadata(mode: str) -> None:
    c = _container(import_mode=mode)
    assert c["importMetadata"]["mode"] == mode
    assert c["importMetadata"] == import_metadata(mode)
    assert isinstance(c["importMetadata"]["steps"], list)
    assert c["importMetadata"]["recommended"] is (mode == "merge")


def test_invalid_import_mode_rejected() -> None:
    with pytest.raises(ValueError, match="import_mode"):
        _container(import_mode="patch")


def test_ga4_property_note_in_description() -> None:
    c = _container(ga4_property="properties/447213908")
    assert "properties/447213908" in c["containerVersion"]["description"]


def test_stable_ids_per_domain() -> None:
    a = build_gtm_container(domain="a.example")["containerVersion"]["container"]
    b = build_gtm_container(domain="b.example")["containerVersion"]["container"]
    a2 = build_gtm_container(domain="a.example")["containerVersion"]["container"]
    assert a["publicId"] != b["publicId"]
    assert a["publicId"] == a2["publicId"]
