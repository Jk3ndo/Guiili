# backend/tests/test_measurement_snippets.py
import pytest

from app.models.enums import StackKind
from app.services.measurement.catalog import ITEMS
from app.services.measurement.event_snippets import snippet_for_event


@pytest.mark.parametrize("stack", [StackKind.NEXTJS, None])
def test_every_snippet_item_resolves_to_a_snippet(stack: StackKind | None) -> None:
    for item in ITEMS:
        if "snippet" in item.actions:
            snippet = snippet_for_event(item.snippet_event or "", stack)
            assert snippet is not None, item.id
            assert snippet.code.strip() and snippet.instructions.strip(), item.id


@pytest.mark.parametrize(
    "stack",
    [StackKind.NEXTJS, StackKind.WOOCOMMERCE, StackKind.NUXT, StackKind.GENERIC, None],
)
def test_purchase_snippet_carries_the_ga4_purchase_parameters(stack: StackKind | None) -> None:
    snippet = snippet_for_event("purchase", stack)
    assert snippet is not None
    for token in ("transaction_id", "value", "currency", "items"):
        assert token in snippet.code, (stack, token)


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


def test_click_email_and_click_to_call_never_push_the_raw_href() -> None:
    for event in ("click_email", "click_to_call"):
        snippet = snippet_for_event(event, None)
        assert snippet is not None
        assert "link.href" not in snippet.code, event
        assert "link_url" not in snippet.code, event


def test_click_whatsapp_strips_the_query_string() -> None:
    snippet = snippet_for_event("click_whatsapp", None)
    assert snippet is not None
    assert 'link.href.split("?")[0]' in snippet.code
    assert (
        "link_url: link.href," not in snippet.code and "link_url: link.href }" not in snippet.code
    )


@pytest.mark.parametrize(
    "event",
    [
        "sign_up",
        "login",
        "begin_trial",
        "subscribe",
        "tutorial_complete",
        "newsletter_signup",
        "share",
    ],
)
def test_simple_events_push_the_event_name(event: str) -> None:
    snippet = snippet_for_event(event, None)
    assert snippet is not None
    assert f'event: "{event}"' in snippet.code
    assert "__" not in snippet.code  # aucun marqueur de gabarit non remplacé


@pytest.mark.parametrize("stack", [StackKind.NEXTJS, None])
def test_consent_default_snippet_denies_by_default(stack: StackKind | None) -> None:
    snippet = snippet_for_event("consent_default", stack)
    assert snippet is not None
    assert "'consent', 'default'" in snippet.code
    for key in ("ad_storage", "ad_personalization", "ad_user_data", "analytics_storage"):
        assert f"{key}: 'denied'" in snippet.code, key
    assert "wait_for_update" in snippet.code


def test_consent_default_snippet_is_pasteable_html() -> None:
    snippet = snippet_for_event("consent_default", None)
    assert snippet is not None
    assert snippet.language == "html"
    assert "<script>" in snippet.code and "</script>" in snippet.code


def test_unknown_event_returns_none() -> None:
    assert snippet_for_event("does_not_exist", None) is None
