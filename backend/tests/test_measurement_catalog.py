from app.services.measurement.catalog import (
    ITEMS,
    ITEMS_BY_ID,
    LAYER_ORDER,
    STARTER_PACKS,
    is_applicable,
    starter_pack,
)
from app.services.measurement.types import CHECK_KINDS, SITE_TYPES


def test_ids_are_unique() -> None:
    assert len({item.id for item in ITEMS}) == len(ITEMS)
    assert set(ITEMS_BY_ID) == {item.id for item in ITEMS}


def test_every_item_is_complete() -> None:
    for item in ITEMS:
        assert item.title.strip(), item.id
        assert item.why.strip(), item.id
        assert item.guide, item.id
        assert all(step.strip() for step in item.guide), item.id
        assert item.check in CHECK_KINDS, item.id
        assert item.layer in LAYER_ORDER, item.id
        assert 1 <= item.weight <= 100, item.id
        assert "guide" in item.actions, item.id
        assert "advisor" in item.actions, item.id


def test_event_items_carry_their_event_name() -> None:
    for item in ITEMS:
        if item.check == "event":
            assert item.arg, item.id
            assert item.max_level == "received", item.id


def test_manual_items_are_capped_at_on_page() -> None:
    manual = [item for item in ITEMS if item.check == "manual"]
    assert {item.id for item in manual} == {
        "ads_conversion_linker",
        "ads_auto_tagging",
        "ads_remarketing",
    }
    assert all(item.max_level == "on_page" for item in manual)


def test_all_layers_and_site_types_are_covered() -> None:
    assert {item.layer for item in ITEMS} == set(LAYER_ORDER)
    covered: set[str] = set()
    for item in ITEMS:
        if item.applies_to is not None:
            covered |= set(item.applies_to)
    assert {"ecommerce", "lead_gen", "saas", "content"} <= covered
    assert set(SITE_TYPES) == {"ecommerce", "lead_gen", "saas", "content", "other"}


def test_snippet_and_gtm_actions_reference_a_snippet_event() -> None:
    for item in ITEMS:
        if "snippet" in item.actions:
            assert item.snippet_event, item.id


def test_is_applicable_by_type_and_ads_flag() -> None:
    purchase = ITEMS_BY_ID["event_purchase"]
    lead = ITEMS_BY_ID["event_generate_lead"]
    gtm = ITEMS_BY_ID["gtm_installed"]
    ads = ITEMS_BY_ID["ads_ga4_link"]

    assert is_applicable(purchase, ("ecommerce",), None)
    assert not is_applicable(purchase, ("lead_gen",), None)
    assert is_applicable(lead, ("lead_gen", "content"), None)
    assert is_applicable(gtm, ("other",), None)  # applies_to=None : tous les sites
    # La couche publicité reste masquée tant que l'utilisateur n'a pas dit en faire.
    assert not is_applicable(ads, ("ecommerce",), None)
    assert is_applicable(ads, ("ecommerce",), True)
    assert not is_applicable(ads, ("ecommerce",), False)


def test_starter_pack_is_a_minimal_selection_led_by_the_ga4_tag() -> None:
    ecommerce = starter_pack(("ecommerce",))
    assert ecommerce[0] == "ga4_tag"
    assert "event_purchase" in ecommerce and "event_generate_lead" not in ecommerce

    mixed = starter_pack(("lead_gen", "ecommerce"))
    assert mixed[0] == "ga4_tag"
    assert len(mixed) == len(set(mixed))  # aucun doublon
    assert "event_generate_lead" in mixed and "event_purchase" in mixed

    assert starter_pack(("other",)) == ["ga4_tag"]
    assert starter_pack(()) == ["ga4_tag"]


def test_every_starter_item_fits_a_container_and_its_site_type() -> None:
    assert set(STARTER_PACKS) == {"ecommerce", "lead_gen", "saas", "content", "other"}
    for site_type, item_ids in STARTER_PACKS.items():
        for item_id in item_ids:
            item = ITEMS_BY_ID[item_id]
            assert "gtm_container" in item.actions, item_id
            assert item.applies_to is None or site_type in item.applies_to, item_id
