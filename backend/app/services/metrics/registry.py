"""Registre de métriques en code : unité, sens d'amélioration, dimensions permises,
agrégation et seuils de chaque métrique stockée. Le code décide : aucun seuil ni statut
ne vient d'un modèle de langage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Unit = Literal["count", "currency", "ratio", "position", "ms", "score", "days", "unitless"]
Direction = Literal["higher_is_better", "lower_is_better", "neutral"]
Aggregation = Literal["sum", "mean", "last", "ratio", "weighted_mean"]

# Plafond de valeurs de dimension conservées par jour (pages, requêtes, événements).
TOP_N = 25


@dataclass(frozen=True, slots=True)
class Thresholds:
    # Seuil « bon » (inclus) et seuil « mauvais » (au-delà, dans le sens défavorable).
    good: float | None = None
    poor: float | None = None
    # Baisse relative (en %) par rapport à la période précédente jugée anormale.
    drop_alert_pct: float | None = None


@dataclass(frozen=True, slots=True)
class MetricDef:
    key: str
    source: str
    name: str
    label: str
    unit: Unit
    direction: Direction
    aggregation: Aggregation
    dimensions: tuple[str, ...] = ()
    top_n: int = 0
    # Ratio : (numérateur, dénominateur), noms courts de la même source.
    ratio_of: tuple[str, str] | None = None
    # Moyenne pondérée : nom court de la métrique servant de poids.
    weight_by: str | None = None
    thresholds: Thresholds = field(default_factory=Thresholds)


def _metric(
    source: str,
    name: str,
    label: str,
    unit: Unit,
    direction: Direction,
    aggregation: Aggregation,
    *,
    dimensions: tuple[str, ...] = (),
    top_n: int = 0,
    ratio_of: tuple[str, str] | None = None,
    weight_by: str | None = None,
    thresholds: Thresholds | None = None,
) -> MetricDef:
    return MetricDef(
        key=f"{source}.{name}",
        source=source,
        name=name,
        label=label,
        unit=unit,
        direction=direction,
        aggregation=aggregation,
        dimensions=dimensions,
        top_n=top_n,
        ratio_of=ratio_of,
        weight_by=weight_by,
        thresholds=thresholds or Thresholds(),
    )


METRICS: tuple[MetricDef, ...] = (
    _metric("ga4", "sessions", "Sessions", "count", "higher_is_better", "sum",
            thresholds=Thresholds(drop_alert_pct=40.0)),
    _metric("ga4", "screen_page_views", "Pages vues", "count", "higher_is_better", "sum"),
    _metric("ga4", "engaged_sessions", "Sessions avec engagement", "count",
            "higher_is_better", "sum"),
    _metric("ga4", "key_events", "Événements clés (conversions)", "count",
            "higher_is_better", "sum", thresholds=Thresholds(drop_alert_pct=50.0)),
    _metric("ga4", "total_revenue", "Revenu total", "currency", "higher_is_better", "sum"),
    _metric("ga4", "event_count", "Nombre d'événements", "count", "neutral", "sum",
            dimensions=("event_name",), top_n=TOP_N),
    _metric("gsc", "clicks", "Clics depuis la recherche Google", "count",
            "higher_is_better", "sum", dimensions=("page", "query"), top_n=TOP_N,
            thresholds=Thresholds(drop_alert_pct=40.0)),
    _metric("gsc", "impressions", "Impressions dans la recherche Google", "count",
            "higher_is_better", "sum", dimensions=("page", "query"), top_n=TOP_N),
    _metric("gsc", "ctr", "Taux de clic", "ratio", "higher_is_better", "ratio",
            ratio_of=("clicks", "impressions")),
    _metric("gsc", "position", "Position moyenne", "position", "lower_is_better",
            "weighted_mean", weight_by="impressions"),
    _metric("cwv", "lcp_p75_ms", "LCP des visiteurs réels (75e centile)", "ms",
            "lower_is_better", "last", thresholds=Thresholds(good=2500.0, poor=4000.0)),
    _metric("cwv", "inp_p75_ms", "INP des visiteurs réels (75e centile)", "ms",
            "lower_is_better", "last", thresholds=Thresholds(good=200.0, poor=500.0)),
    _metric("cwv", "cls_p75", "CLS des visiteurs réels (75e centile)", "unitless",
            "lower_is_better", "last", thresholds=Thresholds(good=0.1, poor=0.25)),
    _metric("cwv", "performance_score", "Score de performance (laboratoire)", "score",
            "higher_is_better", "last", thresholds=Thresholds(good=90.0, poor=50.0)),
    _metric("probe", "tls_days_remaining", "Jours avant expiration du certificat HTTPS",
            "days", "higher_is_better", "last", thresholds=Thresholds(good=30.0, poor=7.0)),
    _metric("probe", "page_up", "Page d'accueil joignable (dernier contrôle du jour)",
            "ratio", "higher_is_better", "mean", thresholds=Thresholds(good=1.0, poor=0.9)),
)

METRICS_BY_KEY: dict[str, MetricDef] = {metric.key: metric for metric in METRICS}
_BY_SOURCE_AND_NAME: dict[tuple[str, str], MetricDef] = {
    (metric.source, metric.name): metric for metric in METRICS
}


def metric_def(source: str, name: str) -> MetricDef | None:
    return _BY_SOURCE_AND_NAME.get((source, name))


def metrics_for_source(source: str) -> tuple[MetricDef, ...]:
    return tuple(metric for metric in METRICS if metric.source == source)
