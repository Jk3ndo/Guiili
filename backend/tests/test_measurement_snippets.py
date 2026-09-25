# backend/tests/test_measurement_snippets.py
import pytest

from app.models.enums import StackKind
from app.services.measurement.catalog import ITEMS
from app.services.measurement.event_snippets import snippet_for_event


def test_every_snippet_item_resolves_to_a_snippet() -> None:
    for item in ITEMS:
        if "snippet" in item.actions:
            snippet = snippet_for_event(item.snippet_event or "", StackKind.NEXTJS)
            assert snippet is not None, item.id
            assert snippet.code.strip() and snippet.instructions.strip(), item.id


def test_purchase_and_lead_reuse_the_stack_library() -> None:
    nextjs = snippet_for_event("purchase", StackKind.NEXTJS)
    wordpress = snippet_for_event("purchase", StackKind.WORDPRESS)
    assert nextjs is not None and wordpress is not None
    assert nextjs.code != wordpress.code
    lead = snippet_for_event("generate_lead", StackKind.NEXTJS)
    assert lead is not None and "generate_lead" in lead.code


@pytest.mark.parametrize(
    "event",
    ["view_item", "add_to_cart", "begin_checkout"],
)
def test_ecommerce_events_push_an_items_array(event: str) -> None:
    snippet = snippet_for_event(event, None)
    assert snippet is not None
    assert f'event: "{event}"' in snippet.code
    assert "items" in snippet.code and "ecommerce" in snippet.code


@pytest.mark.parametrize(
    ("event", "selector"),
    [
        ("click_to_call", 'a[href^="tel:"]'),
        ("click_email", 'a[href^="mailto:"]'),
        ("click_whatsapp", "wa.me"),
    ],
)
def test_link_events_listen_to_clicks(event: str, selector: str) -> None:
    snippet = snippet_for_event(event, None)
    assert snippet is not None
    assert selector in snippet.code
    assert f'event: "{event}"' in snippet.code


@pytest.mark.parametrize(
    "event",
    ["sign_up", "login", "begin_trial", "subscribe", "tutorial_complete", "newsletter_signup", "share"],
)
def test_simple_events_push_the_event_name(event: str) -> None:
    snippet = snippet_for_event(event, None)
    assert snippet is not None
    assert f'event: "{event}"' in snippet.code
    assert "__" not in snippet.code  # aucun marqueur de gabarit non remplacé


def test_consent_default_snippet_denies_by_default() -> None:
    snippet = snippet_for_event("consent_default", None)
    assert snippet is not None
    assert "'consent', 'default'" in snippet.code
    assert "analytics_storage: 'denied'" in snippet.code
    assert "ad_user_data: 'denied'" in snippet.code
    assert "wait_for_update" in snippet.code


def test_unknown_event_returns_none() -> None:
    assert snippet_for_event("does_not_exist", None) is None
