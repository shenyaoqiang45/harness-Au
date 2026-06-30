"""Tests for Yahoo price outlier smoothing."""

from datetime import date

from gold_forecast.fetchers import FetchedRecord
from gold_forecast.fetchers.yahoo import _smooth_daily_outliers


def _rec(day: str, value: float) -> FetchedRecord:
    return FetchedRecord(
        date=date.fromisoformat(day),
        indicator="lme_gold_price",
        value=value,
        unit="USD/oz",
        source="Yahoo Finance",
        source_url="",
        frequency="daily",
        confidence="B",
    )


def test_smooth_daily_outliers_fixes_spike():
    records = [
        _rec("2026-06-01", 2350.0),
        _rec("2026-06-02", 2550.0),
        _rec("2026-06-03", 2360.0),
        _rec("2026-06-04", 2365.0),
    ]
    smoothed = _smooth_daily_outliers(records)
    values = [float(r.value) for r in smoothed]
    assert values[1] == 2355.0
