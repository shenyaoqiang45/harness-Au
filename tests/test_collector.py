"""Tests for collector merge logic."""

from datetime import date, datetime

from gold_forecast.collector import merge_records
from gold_forecast.fetchers import FetchedRecord


def _rec(indicator: str, day: str, value: float, frequency: str = "daily") -> FetchedRecord:
    return FetchedRecord(
        date=date.fromisoformat(day),
        indicator=indicator,
        value=value,
        unit="index",
        source="test",
        source_url="",
        frequency=frequency,
        confidence="A",
    )


def test_merge_overwrites_same_key():
    old = [_rec("dxy", "2026-06-01", 100.0)]
    new = [_rec("dxy", "2026-06-01", 101.0)]
    merged = merge_records(old, new)
    assert len(merged) == 1
    assert merged[0].value == 101.0


def test_merge_keeps_distinct_series():
    a = [_rec("dxy", "2026-06-01", 100.0)]
    b = [_rec("china_pmi", "2026-05-28", 50.0)]
    merged = merge_records(a, b)
    assert len(merged) == 2


def test_merge_overwrites_monthly_same_month():
    proxy = [_rec("grid_investment", "2026-05-28", -17.1, "monthly")]
    manual = [_rec("grid_investment", "2026-05-01", 8.2, "monthly")]
    merged = merge_records(proxy, manual)
    assert len(merged) == 1
    assert merged[0].date == date(2026, 5, 1)
    assert merged[0].value == 8.2
