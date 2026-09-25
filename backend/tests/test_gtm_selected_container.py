import json

import pytest

from app.models.enums import StackKind
from app.services.gtm_generator import (
    _ADS_UNVALIDATED_WARNING,
    _DOUBLE_PAGE_VIEW_WARNING,
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
    # Une balise GA4 Configuration part toujours avec l'avertissement de double page_view.
    assert warnings == [_DOUBLE_PAGE_VIEW_WARNING]
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
    assert warnings == [_DOUBLE_PAGE_VIEW_WARNING, _ADS_UNVALIDATED_WARNING]


def test_ads_tag_without_ids_warns_and_is_skipped() -> None:
    container, warnings = _build(["ads_conversion_tag", "event_view_item"])
    assert "Google Ads - Conversion" not in _names(container, "tag")
    ads_warnings = [w for w in warnings if "Réglages Ads" in w]
    assert len(ads_warnings) == 1
    assert _ADS_UNVALIDATED_WARNING not in warnings  # aucune balise Ads émise


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


def test_conversion_linker_alone_warns_that_ads_tags_are_unvalidated() -> None:
    _, warnings = _build(["ads_conversion_linker"])
    assert warnings == [_ADS_UNVALIDATED_WARNING]


def _event_parameter_values(tag: dict) -> list[str]:
    values = []
    for parameter in tag["parameter"]:
        if parameter["key"] != "eventParameters":
            continue
        for entry in parameter["list"]:
            values += [item["value"] for item in entry["map"]]
    return values


def test_contact_click_events_never_send_the_click_url() -> None:
    container, _ = _build(["event_click_to_call", "event_click_email", "event_click_whatsapp"])
    tags = {t["name"]: t for t in container["containerVersion"]["tag"]}
    for name, method in (
        ("GA4 - click_to_call", "tel"),
        ("GA4 - click_email", "email"),
        ("GA4 - click_whatsapp", "whatsapp"),
    ):
        values = _event_parameter_values(tags[name])
        assert "{{Click URL}}" not in values
        assert method in values
    assert "{{Click URL}}" not in json.dumps([t["parameter"] for t in tags.values()])


def test_ads_tag_on_purchase_sends_value_and_currency() -> None:
    container, _ = _build(
        ["event_purchase", "ads_conversion_tag"],
        ads_conversion_id="AW-123456789",
        ads_conversion_label="AbCdEfGhIjK",
    )
    ads = next(t for t in container["containerVersion"]["tag"] if t["type"] == "awct")
    params = {p["key"]: p["value"] for p in ads["parameter"]}
    assert params["conversionValue"] == "{{dlv - value}}"
    assert params["currencyCode"] == "{{dlv - currency}}"


def test_ads_tag_on_a_non_ecommerce_event_has_no_value() -> None:
    container, _ = _build(
        ["event_generate_lead", "ads_conversion_tag"],
        ads_conversion_id="AW-123456789",
        ads_conversion_label="AbCdEfGhIjK",
    )
    ads = next(t for t in container["containerVersion"]["tag"] if t["type"] == "awct")
    assert {p["key"] for p in ads["parameter"]} == {"conversionId", "conversionLabel"}


def test_duplicate_item_ids_are_generated_once() -> None:
    container, _ = _build(["event_purchase", "event_purchase", "ga4_tag", "ga4_tag"])
    version = container["containerVersion"]
    assert _names(container, "tag").count("GA4 - purchase") == 1
    assert len(version["trigger"]) == len({t["triggerId"] for t in version["trigger"]})
    assert [t["name"] for t in version["trigger"]].count("CE - purchase") == 1


def test_output_is_deterministic_with_a_fixed_export_time() -> None:
    ids = ["ga4_tag", "event_purchase", "event_click_to_call", "ads_conversion_tag"]
    kwargs = {
        "ads_conversion_id": "AW-123456789",
        "ads_conversion_label": "AbCdEfGhIjK",
        "export_time": "2026-09-25 00:00:00",
    }
    assert _build(ids, **kwargs) == _build(list(ids), **kwargs)


def test_unknown_or_non_container_items_warn_once_each() -> None:
    container, warnings = _build(["ga4_tag", "consent_mode", "fautedefrappe"])
    assert "GA4 Configuration" in _names(container, "tag")
    assert len(warnings) == 3  # dont l'avertissement de double page_view
    assert any("consent_mode" in w for w in warnings)
    assert any("fautedefrappe" in w for w in warnings)


def test_ga4_configuration_always_warns_about_duplicated_page_views() -> None:
    _, implicit = _build(["event_login"])
    assert any("page_view" in w for w in implicit)
    _, explicit = _build(["ga4_tag", "event_login"])
    # Désormais aussi quand la balise est demandée explicitement (I4 de la revue finale).
    assert any("page_view" in w for w in explicit)


def test_invalid_import_mode_raises() -> None:
    with pytest.raises(ValueError, match="import_mode inconnu"):
        _build(["ga4_tag"], import_mode="nimporte")


def test_double_page_view_warning_when_the_config_is_added_implicitly() -> None:
    # Événements seuls : la balise GA4 Configuration est ajoutée d'office.
    container, warnings = _build(["event_generate_lead"])
    assert "GA4 Configuration" in _names(container, "tag")
    assert warnings == [_DOUBLE_PAGE_VIEW_WARNING]


def test_no_double_page_view_warning_without_a_config_tag() -> None:
    container, warnings = _build(["ads_conversion_linker"])
    assert "GA4 Configuration" not in _names(container, "tag")
    assert _DOUBLE_PAGE_VIEW_WARNING not in warnings
