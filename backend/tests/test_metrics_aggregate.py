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


def test_sum_mean_and_last() -> None:
    values = {D1: 2.0, D2: 4.0, D3: 9.0}
    assert aggregate(METRICS_BY_KEY["ga4.sessions"], values) == 15.0
    assert aggregate(METRICS_BY_KEY["probe.page_up"], {D1: 1.0, D2: 0.0}) == 0.5
    assert aggregate(METRICS_BY_KEY["cwv.lcp_p75_ms"], values) == 9.0
    assert aggregate(METRICS_BY_KEY["ga4.sessions"], {}) is None


def test_ratio_is_computed_from_the_sums() -> None:
    ctr = METRICS_BY_KEY["gsc.ctr"]
    assert siblings_needed(ctr) == ("clicks", "impressions")
    siblings = {"clicks": {D1: 10.0, D2: 30.0}, "impressions": {D1: 100.0, D2: 300.0, D3: 50.0}}
    # Seuls les jours présents des deux côtés comptent : 40 / 400.
    assert aggregate(ctr, {D1: 0.1, D2: 0.1}, siblings) == pytest.approx(0.1)
    assert aggregate(ctr, {}, {"clicks": {D1: 1.0}, "impressions": {D1: 0.0}}) is None


def test_weighted_mean_uses_the_weight_metric() -> None:
    position = METRICS_BY_KEY["gsc.position"]
    assert siblings_needed(position) == ("impressions",)
    values = {D1: 10.0, D2: 20.0}
    siblings = {"impressions": {D1: 100.0, D2: 300.0}}
    assert aggregate(position, values, siblings) == pytest.approx(17.5)
    assert aggregate(position, values, {"impressions": {}}) is None
