"""Tests for CME COMEX gold stocks parser."""

from datetime import date

from gold_forecast.fetchers.comex import parse_cme_gold_stocks_xls


def test_parse_cme_gold_stocks_xls_from_fixture():
    import io

    import pandas as pd

    rows = [
        [None] * 9,
        [None, None, None, None, None, None, None, "Activity Date: 6/25/2026", None],
        [None] * 9,
        ["TOTAL GOLD", 25000000, 1200, 800, 400, 0, 25002400, None, None],
    ]
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, header=False)
    buffer.seek(0)

    activity_date, metric_tons = parse_cme_gold_stocks_xls(buffer.read())
    assert activity_date == date(2026, 6, 25)
    assert metric_tons == round(25002400 * 0.0000311034768, 4)
