"""Tests for FRED fetcher transforms."""

import pandas as pd
import pytest

from gold_forecast.fetchers import fred


def test_fetch_fred_series_applies_yoy_pct_transform(monkeypatch):
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=13, freq="MS"),
            "value": [100 + i for i in range(13)],
        }
    )
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(fred, "_fred_csv", lambda series_id: frame)

    result = fred.fetch_fred_series(
        "CPIAUCNS",
        "us_cpi_yoy",
        {
            "transform": "yoy_pct",
            "unit": "pct",
            "frequency": "monthly",
            "source": "FRED",
            "source_url": "https://fred.stlouisfed.org/series/CPIAUCNS",
            "confidence": "A",
        },
        lookback_days=10_000,
    )

    assert len(result.records) == 1
    assert result.records[0].indicator == "us_cpi_yoy"
    assert result.records[0].value == pytest.approx(12.0)


def test_yoy_pct_uses_calendar_months_when_a_month_is_missing(monkeypatch):
    dates = pd.date_range("2025-01-01", "2026-10-01", freq="MS")
    rows = []
    for d in dates:
        if d == pd.Timestamp("2025-10-01"):
            continue
        months = (d.year - 2025) * 12 + d.month - 1
        rows.append({"date": d, "value": 100.0 + months})
    frame = pd.DataFrame(rows)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(fred, "_fred_csv", lambda series_id: frame)

    result = fred.fetch_fred_series(
        "CPIAUCNS",
        "us_cpi_yoy",
        {
            "transform": "yoy_pct",
            "unit": "pct",
            "frequency": "monthly",
            "source": "FRED",
            "source_url": "https://fred.stlouisfed.org/series/CPIAUCNS",
            "confidence": "A",
        },
        lookback_days=10_000,
    )

    by_date = {r.date.isoformat(): r.value for r in result.records}
    assert by_date["2026-07-01"] == pytest.approx(118.0 / 106.0 * 100 - 100)
    assert "2026-10-01" not in by_date


def test_fetch_fred_honors_indicator_lookback_days(monkeypatch):
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2025-01-01", "2026-01-01"]),
            "value": [100.0, 103.0, 106.0],
        }
    )
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(fred, "_fred_csv", lambda series_id: frame)

    cfg = {
        "us_10y_real_rate": {
            "series_id": "DFII10",
            "unit": "pct",
            "frequency": "daily",
            "source": "FRED",
            "source_url": "https://fred.stlouisfed.org/series/DFII10",
            "confidence": "A",
            "lookback_days": 10_000,
        }
    }
    result = fred.fetch_fred(cfg, lookback_days=1)
    assert len(result.records) == 3
    assert result.records[-1].value == pytest.approx(106.0)
