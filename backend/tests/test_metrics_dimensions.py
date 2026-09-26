import pytest

from app.services.metrics.dimensions import CLEANERS, clean_event, clean_page, clean_query, dim_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://boutique.fr/produits/chaise?utm_source=x#avis", "/produits/chaise"),
        ("https://boutique.fr", "/"),
        ("/panier?id=42", "/panier"),
        ("contact", "/contact"),
        ("https://boutique.fr/compte/jean.dupont%40gmail.com", None),
        ("   ", None),
    ],
)
def test_clean_page_keeps_only_the_path(raw: str, expected: str | None) -> None:
    assert clean_page(raw) == expected


def test_clean_page_truncates_long_paths() -> None:
    cleaned = clean_page("/" + "a" * 500)
    assert cleaned is not None and len(cleaned) == 200


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Chaise EN Chêne ", "chaise en chêne"),
        ("jean.dupont@gmail.com", None),
        ("appeler 06 12 34 56 78", None),
        ("commande 123456789", None),
        ("", None),
    ],
)
def test_clean_query_drops_personal_data(raw: str, expected: str | None) -> None:
    assert clean_query(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("purchase", "purchase"), ("generate_lead", "generate_lead"), ("nom invalide !", None), ("", None)],
)
def test_clean_event_accepts_only_ga4_names(raw: str, expected: str | None) -> None:
    assert clean_event(raw) == expected


def test_cleaners_are_idempotent() -> None:
    for name, cleaner in CLEANERS.items():
        sample = {"page": "https://x.fr/a/b?q=1", "query": " Chaise ", "event_name": "purchase"}[name]
        once = cleaner(sample)
        assert once is not None and cleaner(once) == once


def test_dim_key_is_stable_and_empty_for_totals() -> None:
    assert dim_key({}) == ""
    first = dim_key({"page": "/a"})
    assert first == dim_key({"page": "/a"}) and len(first) == 32
    assert first != dim_key({"page": "/b"})
    assert dim_key({"page": "/a"}) != dim_key({"query": "/a"})
