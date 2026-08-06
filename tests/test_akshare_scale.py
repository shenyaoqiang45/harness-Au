"""Tests for akshare value_scale conversion."""

from gold_forecast.fetchers.akshare_src import _records_from_frame
import pandas as pd


def test_value_scale_converts_kg_to_ton():
    frame = pd.DataFrame({"日期": ["2026-08-05"], "库存": [113616.0]})
    cfg = {
        "unit": "ton",
        "source": "test",
        "source_url": "",
        "frequency": "daily",
        "confidence": "A",
        "value_scale": 0.001,
        "note": "kg to ton",
    }
    rows = _records_from_frame(
        frame,
        "shfe_inventory",
        "日期",
        "库存",
        cfg,
        cutoff=pd.Timestamp("2026-01-01").date(),
    )
    assert len(rows) == 1
    assert rows[0].value == 113.616
    assert rows[0].unit == "ton"
