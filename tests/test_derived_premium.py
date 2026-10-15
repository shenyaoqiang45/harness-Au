"""Spot premium must survive mixed datetime resolutions from pandas."""

from datetime import date, datetime

import pandas as pd

from gold_forecast.fetchers import FetchedRecord
from gold_forecast.fetchers.derived import _merge_shfe_comex, shfe_lme_premium


def test_merge_accepts_second_and_microsecond_keys():
    shfe = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-10-13", "2026-10-14"]).astype("datetime64[s]"),
            "shfe_close": [900.0, 910.0],
        }
    )
    comex = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-10-13", "2026-10-14"]).astype("datetime64[us]"),
            "Close": [4100.0, 4110.0],
        }
    )

    merged = _merge_shfe_comex(shfe, comex)

    assert list(merged["date"].dt.date) == [date(2026, 10, 13), date(2026, 10, 14)]
    assert merged["Close"].tolist() == [4100.0, 4110.0]


def test_shfe_lme_premium_uses_fetched_gold(monkeypatch):
    shfe = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2026-10-14"]).astype("datetime64[s]"),
            "收盘价": [900.0],
        }
    )
    monkeypatch.setattr(
        "gold_forecast.fetchers.derived.ak.futures_main_sina",
        lambda **_kwargs: shfe,
    )
    monkeypatch.setattr("gold_forecast.fetchers.derived._latest_fx", lambda: 7.2)
    gold = FetchedRecord(
        date=date(2026, 10, 14),
        indicator="lme_gold_price",
        value=4100.0,
        unit="USD/oz",
        source="Yahoo Finance",
        source_url="",
        frequency="daily",
        confidence="B",
        updated_at=datetime(2026, 10, 15, 9, 51),
    )

    result = shfe_lme_premium(existing=[gold])

    assert result.errors == []
    assert len(result.records) == 1
    assert result.records[0].date == date(2026, 10, 14)
    assert result.records[0].indicator == "spot_premium"
    assert result.records[0].value == round(900.0 * 31.1034768 / 7.2 - 4100.0, 2)
