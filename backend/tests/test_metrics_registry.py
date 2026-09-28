import copy
import pickle
from datetime import date, timedelta

import pytest

from app.services.metrics.dimensions import CLEANERS
from app.services.metrics.registry import METRICS, METRICS_BY_KEY, metric_def, metrics_for_source
from app.services.metrics.types import SOURCE_SPECS, DayRange, Observation, SourceError


def test_keys_are_unique_and_qualified() -> None:
    assert len(METRICS_BY_KEY) == len(METRICS)
    for metric in METRICS:
        assert metric.key == f"{metric.source}.{metric.name}"
        assert metric.label


def test_dimensions_are_allowed_by_the_source_and_capped() -> None:
    for metric in METRICS:
        spec = SOURCE_SPECS[metric.source]
        assert set(metric.dimensions) <= set(spec.dimensions), metric.key
        assert (metric.top_n > 0) == bool(metric.dimensions), metric.key


def test_ratio_and_weighted_metrics_point_to_sibling_metrics() -> None:
    for metric in METRICS:
        if metric.aggregation == "ratio":
            assert metric.ratio_of is not None
            assert all(metric_def(metric.source, name) for name in metric.ratio_of)
        else:
            assert metric.ratio_of is None
        if metric.aggregation == "weighted_mean":
            assert metric.weight_by is not None
            assert metric_def(metric.source, metric.weight_by) is not None
        else:
            assert metric.weight_by is None


def test_thresholds_follow_the_direction_of_improvement() -> None:
    for metric in METRICS:
        good, poor = metric.thresholds.good, metric.thresholds.poor
        if good is None or poor is None:
            continue
        if metric.direction == "lower_is_better":
            assert good < poor, metric.key
        else:
            assert good > poor, metric.key


def test_lookup_helpers() -> None:
    sessions = metric_def("ga4", "sessions")
    assert sessions is not None and sessions.key == "ga4.sessions"
    assert metric_def("ga4", "inconnue") is None
    assert {m.name for m in metrics_for_source("gsc")} >= {"clicks", "impressions", "ctr", "position"}
    # Les utilisateurs ne s'additionnent pas d'un jour à l'autre : pas de métrique « users ».
    assert not any("user" in m.name for m in METRICS)


def test_source_specs_carry_the_floors_and_backfill() -> None:
    assert SOURCE_SPECS["ga4"].min_interval == timedelta(hours=8)
    assert SOURCE_SPECS["gsc"].min_interval == timedelta(hours=8)
    assert SOURCE_SPECS["cwv"].min_interval == timedelta(hours=8)
    assert SOURCE_SPECS["probe"].min_interval == timedelta(hours=1)
    assert SOURCE_SPECS["ga4"].backfill_days == 90
    assert SOURCE_SPECS["gsc"].backfill_days == 90
    assert SOURCE_SPECS["cwv"].backfill_window(date(2026, 9, 26)) is None


def test_day_range_helpers() -> None:
    window = DayRange(date(2026, 9, 1), date(2026, 9, 3))
    assert window.length == 3
    assert window.days() == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    assert window.chunks(2) == [
        DayRange(date(2026, 9, 1), date(2026, 9, 2)),
        DayRange(date(2026, 9, 3), date(2026, 9, 3)),
    ]
    assert window.contains(date(2026, 9, 2)) and not window.contains(date(2026, 9, 4))
    with pytest.raises(ValueError):
        DayRange(date(2026, 9, 3), date(2026, 9, 1))


def test_regular_and_backfill_windows_respect_freshness() -> None:
    today = date(2026, 9, 26)
    assert SOURCE_SPECS["ga4"].regular_window(today) == DayRange(date(2026, 9, 23), date(2026, 9, 25))
    assert SOURCE_SPECS["gsc"].regular_window(today) == DayRange(date(2026, 9, 21), date(2026, 9, 23))
    assert SOURCE_SPECS["probe"].regular_window(today) == DayRange(today, today)
    backfill = SOURCE_SPECS["ga4"].backfill_window(today)
    assert backfill is not None and backfill.length == 90 and backfill.end == date(2026, 9, 25)


def test_not_applicable_is_never_recoverable() -> None:
    error = SourceError("ga4_not_connected", recoverable=True, not_applicable=True)
    assert error.reason == "ga4_not_connected"
    assert error.not_applicable is True and error.recoverable is False
    # Sans `not_applicable`, l'indicateur `recoverable` est conservé tel quel.
    retryable = SourceError("quota", recoverable=True)
    assert retryable.recoverable is True and retryable.not_applicable is False
    final = SourceError("forbidden", recoverable=False)
    assert final.recoverable is False and final.not_applicable is False


@pytest.mark.parametrize(
    "error",
    [
        SourceError("quota", recoverable=True),
        SourceError("forbidden", recoverable=False),
        SourceError("ga4_not_connected", recoverable=True, not_applicable=True),
    ],
)
def test_source_error_survives_copy_and_pickle(error: SourceError) -> None:
    # Aller-retour d'un objet créé ici même (aucune donnée externe désérialisée).
    roundtrip = pickle.loads(pickle.dumps(error))  # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
    for clone in (copy.copy(error), copy.deepcopy(error), roundtrip):
        assert isinstance(clone, SourceError)
        assert (clone.reason, clone.recoverable, clone.not_applicable) == (
            error.reason,
            error.recoverable,
            error.not_applicable,
        )
        assert str(clone) == error.reason


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_observation_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError):
        Observation("sessions", date(2026, 9, 25), value)


def test_observation_accepts_finite_values() -> None:
    observation = Observation("sessions", date(2026, 9, 25), 0.0)
    assert observation.value == 0.0 and observation.dims == {}


def test_every_dimension_has_a_cleaner() -> None:
    for spec in SOURCE_SPECS.values():
        assert set(spec.dimensions) <= set(CLEANERS), spec.name
    for metric in METRICS:
        assert set(metric.dimensions) <= set(CLEANERS), metric.key


def test_source_spec_names_match_their_keys() -> None:
    for key, spec in SOURCE_SPECS.items():
        assert spec.name == key
