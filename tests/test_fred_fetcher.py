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
        "CPIAUCSL",
        "us_cpi_yoy",
        {
            "transform": "yoy_pct",
            "unit": "pct",
            "frequency": "monthly",
            "source": "FRED",
            "source_url": "https://fred.stlouisfed.org/series/CPIAUCSL",
            "confidence": "A",
        },
        lookback_days=10_000,
    )

    assert len(result.records) == 1
    assert result.records[0].indicator == "us_cpi_yoy"
    assert result.records[0].value == pytest.approx(12.0)