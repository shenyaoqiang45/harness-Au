"""Tests for indicator scoring helpers."""

from datetime import date, datetime

from gold_forecast.data_loader import DataRow
from gold_forecast.indicators import _global_inventory_series


def _inv_row(indicator: str, d: date, value: float) -> DataRow:
    return DataRow(
        date=d,
        indicator=indicator,
        value=value,
        unit="ton",
        source="test",
        source_url="https://example.com",
        updated_at=datetime.combine(d, datetime.min.time()),
        frequency="daily",
        confidence="A",
        status="confirmed",
    )


def test_global_inventory_forward_fills_stale_lme_on_newer_shfe_date():
    grouped = {
        "lme_inventory": [
            _inv_row("lme_inventory", date(2026, 6, 1), 400_000.0),
            _inv_row("lme_inventory", date(2026, 6, 26), 336_475.0),
        ],
        "shfe_inventory": [
            _inv_row("shfe_inventory", date(2026, 6, 1), 99_543.0),
            _inv_row("shfe_inventory", date(2026, 6, 29), 73_289.0),
        ],
    }

    series = _global_inventory_series(grouped, ["lme_inventory", "shfe_inventory"])
    by_date = dict(series)

    assert by_date[date(2026, 6, 1)] == 499_543.0
    assert by_date[date(2026, 6, 26)] == 336_475.0 + 99_543.0
    assert by_date[date(2026, 6, 29)] == 336_475.0 + 73_289.0
    assert by_date[date(2026, 6, 29)] > 400_000.0
