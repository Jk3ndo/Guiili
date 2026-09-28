from datetime import date

import pytest

from app.services.metrics.aggregate import (
    aggregate,
    month_start,
    period_end,
    period_start,
    periods_between,
    siblings_needed,
    week_start,
)
from app.services.metrics.registry import METRICS_BY_KEY

D1, D2, D3 = date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)


def test_periods() -> None:
    assert week_start(date(2026, 9, 24)) == date(2026, 9, 21)  # un lundi
    assert month_start(date(2026, 9, 24)) == date(2026, 9, 1)
    assert period_start(date(2026, 9, 24), "week") == date(2026, 9, 21)
    assert period_end(date(2026, 9, 21), "week") == date(2026, 9, 27)
    assert period_end(date(2026, 2, 1), "month") == date(2026, 2, 28)
    assert period_end(date(2026, 12, 1), "month") == date(2026, 12, 31)
    assert periods_between(date(2026, 9, 25), date(2026, 10, 6), "week") == [
        date(2026, 9, 21),
        date(2026, 9, 28),
        date(2026, 10, 5),
    ]
    assert periods_between(date(2026, 9, 25), date(2026, 11, 2), "month") == [
        date(2026, 9, 1),
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]


def test_period_boundaries_across_a_year_change() -> None:
    assert week_start(date(2027, 1, 1)) == date(2026, 12, 28)  # un vendredi
    assert period_end(date(2026, 12, 28), "week") == date(2027, 1, 3)
    assert month_start(date(2027, 1, 1)) == date(2027, 1, 1)
    assert period_end(date(2027, 1, 1), "month") == date(2027, 1, 31)
    assert period_end(date(2028, 2, 1), "month") == date(2028, 2, 29)  # année bissextile
    assert periods_between(date(2026, 12, 30), date(2027, 1, 5), "week") == [
        date(2026, 12, 28),
        date(2027, 1, 4),
    ]
    assert periods_between(date(2026, 12, 15), date(2027, 2, 1), "month") == [
        date(2026, 12, 1),
        date(2027, 1, 1),
        date(2027, 2, 1),
    ]
    # Un début et une fin dans la même période donnent cette seule période.
    assert periods_between(date(2026, 9, 22), date(2026, 9, 23), "week") == [date(2026, 9, 21)]


def test_periods_between_is_empty_when_start_follows_end() -> None:
    assert periods_between(date(2026, 9, 25), date(2026, 9, 24), "week") == []
    assert periods_between(date(2026, 9, 25), date(2026, 9, 24), "month") == []


def test_sum_mean_and_last() -> None:
    values = {D1: 2.0, D2: 4.0, D3: 9.0}
    assert aggregate(METRICS_BY_KEY["ga4.sessions"], values) == 15.0
    assert aggregate(METRICS_BY_KEY["probe.page_up"], {D1: 1.0, D2: 0.0}) == 0.5
    assert aggregate(METRICS_BY_KEY["cwv.lcp_p75_ms"], values) == 9.0
    assert aggregate(METRICS_BY_KEY["ga4.sessions"], {}) is None


def test_last_takes_the_latest_day_not_the_largest_value_nor_insertion_order() -> None:
    lcp = METRICS_BY_KEY["cwv.lcp_p75_ms"]
    # Insérés dans le désordre ; le dernier jour (D3) porte la plus petite valeur.
    values = {D2: 5.0, D3: 1.0, D1: 9.0}
    assert aggregate(lcp, values) == 1.0


def test_ratio_is_computed_from_the_sums() -> None:
    ctr = METRICS_BY_KEY["gsc.ctr"]
    assert siblings_needed(ctr) == ("clicks", "impressions")
    # Jours de poids inégaux : 20 / 1000 = 0,02 ; une moyenne des ratios (0,1 et 0,011)
    # donnerait 0,055. Le jour D3 n'a pas de clics : il est ignoré.
    siblings = {"clicks": {D1: 10.0, D2: 10.0}, "impressions": {D1: 100.0, D2: 900.0, D3: 50.0}}
    result = aggregate(ctr, {D1: 0.1, D2: 10 / 900}, siblings)
    assert result == pytest.approx(0.02)
    assert result != pytest.approx(0.055)
    assert aggregate(ctr, {}, {"clicks": {D1: 1.0}, "impressions": {D1: 0.0}}) is None
    assert aggregate(ctr, {}, {"clicks": {D1: 1.0}, "impressions": {D2: 5.0}}) is None


def test_weighted_mean_uses_the_weight_metric() -> None:
    position = METRICS_BY_KEY["gsc.position"]
    assert siblings_needed(position) == ("impressions",)
    values = {D1: 10.0, D2: 20.0}
    siblings = {"impressions": {D1: 100.0, D2: 300.0, D3: 1000.0}}
    # (10*100 + 20*300) / 400 = 17,5 ; la moyenne simple donnerait 15 et le jour D3,
    # sans position, ne pèse pas.
    result = aggregate(position, values, siblings)
    assert result == pytest.approx(17.5)
    assert result != pytest.approx(15.0)
    assert aggregate(position, values, {"impressions": {}}) is None
