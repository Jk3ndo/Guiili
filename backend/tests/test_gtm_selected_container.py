import json

from app.models.enums import StackKind
from app.services.gtm_generator import (
    _RECIPES,
    build_selected_container,
    requires_site_code,
)
from app.services.measurement.catalog import ITEMS


def _build(item_ids, **kw):
    args = {
        "domain": "exemple.fr",
        "stack": StackKind.NEXTJS,
        "item_ids": item_ids,
        "ga4_measurement_id": "G-ABC123XYZ",
        "ads_conversion_id": None,
        "ads_conversion_label": None,
    }
    args.update(kw)
    return build_selected_container(**args)


def _names(container: dict, key: str) -> list[str]:
    return [entry["name"] for entry in container["containerVersion"][key]]


def test_only_selected_events_are_generated() -> None:
    container, warnings = _build(["ga4_tag", "event_purchase", "event_generate_lead"])
    tags = _names(container, "tag")
    assert "GA4 Configuration" in tags
    assert "GA4 - purchase" in tags and "GA4 - generate_lead" in tags
    assert "GA4 - view_item" not in tags
    assert warnings == []
    json.dumps(container)  # sérialisable


def test_ids_are_unique_and_triggers_are_referenced() -> None:
    container, _ = _build(
        ["event_view_item", "event_add_to_cart", "event_click_to_call", "event_sign_up"]
    )
    version = container["containerVersion"]
    for key, id_key in (("tag", "tagId"), ("trigger", "triggerId"), ("variable", "variableId")):
        ids = [entry[id_key] for entry in version[key]]
        assert len(ids) == len(set(ids)), key
    trigger_ids = {t["triggerId"] for t in version["trigger"]} | {"2147479553"}
    for tag in version["tag"]:
        assert set(tag["firingTriggerId"]) <= trigger_ids


def test_ecommerce_events_send_ecommerce_data() -> None:
    container, _ = _build(["event_purchase"])
    tag = next(t for t in container["containerVersion"]["tag"] if t["name"] == "GA4 - purchase")
    keys = {p["key"]: p.get("value") for p in tag["parameter"]}
    assert keys["sendEcommerceData"] == "true"


def test_link_click_events_use_link_click_triggers() -> None:
    container, _ = _build(["event_click_to_call", "event_click_whatsapp"])
    triggers = {t["name"]: t for t in container["containerVersion"]["trigger"]}
    tel = triggers["Clic - click_to_call"]
    assert tel["type"] == "linkClick"
    assert tel["filter"][0]["type"] == "startsWith"
    assert tel["filter"][0]["parameter"][1]["value"] == "tel:"
    wa = triggers["Clic - click_whatsapp"]
    assert wa["filter"][0]["type"] == "contains"


def test_ads_conversion_tag_uses_the_provided_ids_and_first_key_event() -> None:
    container, warnings = _build(
        ["ga4_tag", "event_generate_lead", "ads_conversion_tag"],
        ads_conversion_id="AW-123456789",
        ads_conversion_label="AbCdEfGhIjK",
    )
    tags = {t["name"]: t for t in container["containerVersion"]["tag"]}
    ads = tags["Google Ads - Conversion"]
    params = {p["key"]: p.get("value") for p in ads["parameter"]}
    assert ads["type"] == "awct"
    assert params["conversionId"] == "123456789"
    assert params["conversionLabel"] == "AbCdEfGhIjK"
    lead_trigger = next(
        t["triggerId"]
        for t in container["containerVersion"]["trigger"]
        if t["name"] == "CE - generate_lead"
    )
    assert ads["firingTriggerId"] == [lead_trigger]
    assert "Conversion Linker" in tags
    assert tags["Conversion Linker"]["type"] == "gclidw"
    assert warnings == []


def test_ads_tag_without_ids_warns_and_is_skipped() -> None:
    container, warnings = _build(["ads_conversion_tag", "event_view_item"])
    assert "Google Ads - Conversion" not in _names(container, "tag")
    assert len(warnings) == 1
    assert "Réglages Ads" in warnings[0]


def test_ads_tag_without_a_key_event_warns() -> None:
    container, warnings = _build(
        ["ads_conversion_tag"],
        ads_conversion_id="AW-123456789",
        ads_conversion_label="AbCdEfGhIjK",
    )
    assert "Google Ads - Conversion" not in _names(container, "tag")
    assert any("événement clé" in w for w in warnings)


def test_conversion_linker_alone() -> None:
    container, _ = _build(["ads_conversion_linker"])
    assert "Conversion Linker" in _names(container, "tag")


def test_missing_measurement_id_uses_a_placeholder_and_warns() -> None:
    container, warnings = _build(["ga4_tag"], ga4_measurement_id=None)
    config = next(
        t for t in container["containerVersion"]["tag"] if t["name"] == "GA4 Configuration"
    )
    assert config["parameter"][0]["value"] == "G-XXXXXXXXXX"
    assert any("ID de mesure" in w for w in warnings)


def test_events_without_ga4_tag_still_get_a_configuration_tag() -> None:
    container, _ = _build(["event_login"])
    assert "GA4 Configuration" in _names(container, "tag")


def test_every_container_item_of_the_catalog_has_a_recipe_or_a_special_case() -> None:
    special = {"ga4_tag", "ads_conversion_tag", "ads_conversion_linker"}
    for item in ITEMS:
        if "gtm_container" in item.actions and item.id not in special:
            assert item.id in _RECIPES, f"{item.id} n'a pas de recette GTM"


def test_requires_site_code_only_for_custom_events() -> None:
    assert requires_site_code("event_purchase") is True
    assert requires_site_code("event_generate_lead") is True
    assert requires_site_code("event_click_to_call") is False  # déclencheur de clic GTM
    assert requires_site_code("ga4_tag") is False
    assert requires_site_code("inconnu") is False


def test_import_metadata_and_mode() -> None:
    merge, _ = _build(["ga4_tag"])
    assert merge["importMetadata"]["mode"] == "merge"
    overwrite, _ = _build(["ga4_tag"], import_mode="overwrite")
    assert overwrite["importMetadata"]["mode"] == "overwrite"
