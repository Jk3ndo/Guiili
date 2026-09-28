import time

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


def test_clean_page_cuts_then_normalises() -> None:
    # Coupe sur une espace : pas d'espace final, et un second passage ne change rien.
    sample = "/" + "a" * 198 + " b"
    cleaned = clean_page(sample)
    assert cleaned == "/" + "a" * 198
    assert cleaned is not None and clean_page(cleaned) == cleaned


def test_clean_page_never_cuts_a_percent_escape_in_two() -> None:
    # Le signe % à l'indice 199 : échappement coupé (le 41 sort de la fenêtre) -> retiré.
    assert clean_page("/" + "a" * 198 + "%41") == "/" + "a" * 198
    # Le signe % à l'indice 198 : « %4 » resterait en fin de valeur -> retiré aussi.
    assert clean_page("/" + "a" * 197 + "%41zz") == "/" + "a" * 197
    # Un échappement complet qui tient dans la fenêtre est conservé (le reste est coupé).
    assert clean_page("/" + "a" * 196 + "%41zzz") == "/" + "a" * 196 + "%41"


def test_clean_query_cuts_then_normalises() -> None:
    sample = "a" * 99 + " " + "b" * 10
    cleaned = clean_query(sample)
    assert cleaned == "a" * 99
    assert clean_query(cleaned) == cleaned


@pytest.mark.parametrize("length", range(95, 106))
@pytest.mark.parametrize("filler", ["a", "é", "a b", " x"])
def test_clean_query_is_idempotent_around_the_cut(length: int, filler: str) -> None:
    sample = (filler * length)[: length + 5]
    once = clean_query(sample)
    if once is not None:
        assert len(once) <= 100 and once == once.strip()
        assert clean_query(once) == once


@pytest.mark.parametrize("length", range(190, 210))
@pytest.mark.parametrize("filler", ["a", "é", "a b", "/x", "%41", "%c3%a9"])
def test_clean_page_is_idempotent_around_the_cut(length: int, filler: str) -> None:
    sample = "/" + (filler * length)[:length]
    once = clean_page(sample)
    if once is not None:
        assert len(once) <= 200 and once == once.rstrip()
        assert clean_page(once) == once


def test_an_email_beyond_the_cut_is_still_dropped() -> None:
    assert clean_query("x" * 99 + " jean@gmail.com") is None
    assert clean_page("/" + "a" * 250 + "/jean@gmail.com") is None


def test_input_is_capped_before_regular_expressions() -> None:
    start = time.perf_counter()
    assert clean_query("a@a.co " * 5000) is None
    assert clean_query("a@" * 10000) == "a@" * 50
    assert clean_query("x" * 20000) == "x" * 100
    assert clean_page("/" + "a@a.co/" * 5000) is None
    assert clean_page("/" + "a@" * 10000) is not None
    assert clean_event("a" * 20000) is None
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize("cleaner", list(CLEANERS.values()))
@pytest.mark.parametrize("raw", [None, 42, b"/a", ["/a"], "\x00", "a\x00b", "\ud800", "a\udfffb"])
def test_cleaners_drop_non_text_control_and_unencodable_values(cleaner, raw) -> None:
    assert cleaner(raw) is None


def test_clean_page_rejects_control_characters_even_when_encoded() -> None:
    assert clean_page("/a%00b") is None
    assert clean_page("/a\nb") is None
    assert clean_page(" \n/a\n") == "/a"


def test_clean_query_treats_line_breaks_as_spaces() -> None:
    assert clean_query("chaise\nen\tchêne") == "chaise en chêne"


def test_clean_page_drops_session_ids_and_protocol_relative_paths() -> None:
    assert clean_page("/a;jsessionid=ABC123/b") == "/a/b"
    assert clean_page("/a;JSESSIONID=ABC123?x=1") == "/a"
    assert clean_page("https://boutique.fr/a;jsessionid=ABC123") == "/a"
    assert clean_page("//evil.com/x") is None
    assert clean_page("https://boutique.fr//x") is None
    assert clean_page("http://[broken/x") is None


def test_unicode_is_normalised_to_nfc() -> None:
    decomposed = "é"
    assert clean_page("/" + decomposed) == "/é"
    assert clean_query("Chaise " + decomposed) == "chaise é"


def test_clean_event_is_strict() -> None:
    assert clean_event("purchase\n") == "purchase"
    assert clean_event("a" * 65) is None
    assert clean_event("1abc") is None
    assert clean_event("évènement") is None
