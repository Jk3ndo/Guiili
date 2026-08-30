"""Bibliotheque de snippets : coherence par framework."""

import itertools

import pytest

from app.models.enums import StackKind
from app.services.snippet_library import SnippetEvent, get_snippets


def test_every_stack_event_combination_resolves() -> None:
    for stack, event in itertools.product(StackKind, SnippetEvent):
        entries = get_snippets(stack, event)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.code.strip()
        assert entry.target_path.strip()
        assert entry.instructions.strip()
        assert "dataLayer" in entry.code


def test_default_returns_all_three_events() -> None:
    entries = get_snippets(StackKind.NEXTJS)
    assert {e.event for e in entries} == set(SnippetEvent)


def test_nextjs_is_typescript() -> None:
    langs = {e.language for e in get_snippets(StackKind.NEXTJS)}
    assert langs <= {"ts", "tsx"}
    purchase = get_snippets(StackKind.NEXTJS, SnippetEvent.PURCHASE)[0]
    assert purchase.target_path == "lib/analytics.ts"
    assert "trackPurchase" in purchase.code


def test_woocommerce_purchase_uses_thankyou_hook() -> None:
    entry = get_snippets(StackKind.WOOCOMMERCE, SnippetEvent.PURCHASE)[0]
    assert entry.language == "php"
    assert "woocommerce_thankyou" in entry.code
    # le lead/custom retombent sur la famille WordPress
    lead = get_snippets(StackKind.WOOCOMMERCE, SnippetEvent.LEAD)[0]
    assert "wpcf7mailsent" in lead.code


def test_nuxt_returns_composable() -> None:
    entry = get_snippets(StackKind.NUXT, SnippetEvent.PURCHASE)[0]
    assert entry.language == "ts"
    assert entry.target_path.startswith("composables/")
    assert "useAnalytics" in entry.code
    assert "import.meta.client" in entry.code


@pytest.mark.parametrize(
    "stack", [StackKind.VUE, StackKind.ANGULAR, StackKind.GENERIC, StackKind.UNKNOWN]
)
def test_fallback_is_vanilla_js(stack: StackKind) -> None:
    entries = get_snippets(stack)
    assert all(e.language == "js" for e in entries)
    assert all(e.stack is stack for e in entries)


def test_none_stack_falls_back() -> None:
    entries = get_snippets(None, SnippetEvent.CUSTOM)
    assert entries[0].language == "js"
    assert entries[0].stack is StackKind.UNKNOWN


def test_event_names_match_gtm_datalayer() -> None:
    assert "purchase" in get_snippets(StackKind.NEXTJS, SnippetEvent.PURCHASE)[0].code
    assert "generate_lead" in get_snippets(StackKind.NEXTJS, SnippetEvent.LEAD)[0].code
