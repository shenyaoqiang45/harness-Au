"""Tests for walk-forward backtest and as-of scoring."""

from datetime import date, datetime, timedelta
from pathlib import Path

from gold_forecast.backtest import (
    HORIZON_BARS,
    WARMUP_BARS,
    load_publication_lags,
    replay_reports,
    row_available_on,
    rows_as_of,
    run_backtest,
    spearman_corr,
    walk_forward,
)
from gold_forecast.data_loader import DataRow, write_csv
from gold_forecast.indicators import compute_all_module_scores, score_financial_flow

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _row(
    day: date,
    indicator: str,
    value: float | str,
    frequency: str = "daily",
    unit: str = "USD/oz",
) -> DataRow:
    return DataRow(
        date=day,
        indicator=indicator,
        value=value,
        unit=unit,
        source="test",
        source_url="https://example.com",
        updated_at=datetime.combine(day, datetime.min.time()),
        frequency=frequency,
        confidence="A",
        status="confirmed",
    )


def test_spearman_perfect_and_inverse():
    xs = [1.0, 2.0, 3.0, 4.0]
    assert spearman_corr(xs, xs) == 1.0
    assert spearman_corr(xs, [-v for v in xs]) == -1.0
    assert spearman_corr([1.0, 2.0], [3.0, 4.0]) is None


def test_publication_lag_keeps_july_cpi_off_the_july_tape():
    lags = load_publication_lags(CONFIG_DIR)
    cpi = _row(date(2026, 7, 1), "us_cpi_yoy", 3.4, frequency="monthly", unit="pct")
    available = row_available_on(cpi, lags)
    assert available == date(2026, 8, 12)
    snapshot = rows_as_of([cpi], date(2026, 8, 1), lags)
    assert snapshot == []
    snapshot = rows_as_of([cpi], date(2026, 8, 12), lags)
    assert snapshot == [cpi]


def test_as_of_drops_future_price_from_trend():
    rows = []
    price = 2000.0
    start = date(2026, 1, 2)
    for i in range(130):
        day = start + timedelta(days=i)
        price += 2.0
        rows.append(_row(day, "lme_gold_price", price))
    as_of = start + timedelta(days=129)
    crash_day = as_of + timedelta(days=1)
    rows.append(_row(crash_day, "lme_gold_price", 100.0))

    leaked = compute_all_module_scores(rows, str(CONFIG_DIR))
    gated = compute_all_module_scores(rows, str(CONFIG_DIR), as_of=as_of)
    assert leaked["trend"].score < 0
    assert gated["trend"].score > 0


def test_financial_flow_ignores_events_after_as_of(tmp_path):
    events = tmp_path / "events.csv"
    events.write_text(
        "date,event,score,confidence,source,note\n"
        "2026-06-15,early,0.6,B,news,early\n"
        "2026-08-01,late,0.9,A,news,late\n",
        encoding="utf-8",
    )
    before = score_financial_flow({}, str(events), as_of=date(2026, 7, 1))
    after = score_financial_flow({}, str(events), as_of=date(2026, 8, 1))
    assert [s.name for s in before.signals] == ["early"]
    assert [s.name for s in after.signals] == ["early", "late"]


def test_walk_forward_rising_market_hits_when_bullish():
    rows: list[DataRow] = []
    start = date(2025, 6, 2)
    price = 2000.0
    n = WARMUP_BARS + HORIZON_BARS["week"] + 8
    for i in range(n):
        day = start + timedelta(days=i)
        price += 3.0
        rows.append(_row(day, "lme_gold_price", price))
        rows.append(_row(day, "dxy", 100.0 - i * 0.01, unit="index"))

    points, _, _ = walk_forward(
        rows,
        CONFIG_DIR,
        lags_cfg={},
        horizon="week",
        score_horizon="month",
    )
    assert len(points) >= 5
    assert all(p.fwd_return > 0 for p in points)
    bullish = [p for p in points if p.pred_sign == 1]
    assert bullish
    assert all(p.hit for p in bullish)


def test_run_backtest_writes_metrics(tmp_path):
    rows: list[DataRow] = []
    start = date(2025, 6, 2)
    price = 2000.0
    n = WARMUP_BARS + HORIZON_BARS["week"] + 6
    for i in range(n):
        day = start + timedelta(days=i)
        price += 2.5
        rows.append(_row(day, "lme_gold_price", price))
        rows.append(_row(day, "dxy", 99.0, unit="index"))
    csv_path = tmp_path / "history.csv"
    write_csv(csv_path, rows)
    result = run_backtest(
        csv_path,
        CONFIG_DIR,
        reports_dir=tmp_path / "reports",
        horizons=("week",),
        apply_publication_lag=False,
    )
    assert result.horizons[0].n >= 3
    assert result.horizons[0].always_long_hit == 1.0


def test_replay_reports_grades_cutoff_against_gold(tmp_path):
    gold = [
        (date(2026, 8, 1), 100.0),
        (date(2026, 8, 4), 101.0),
        (date(2026, 8, 5), 102.0),
        (date(2026, 8, 6), 103.0),
        (date(2026, 8, 7), 104.0),
        (date(2026, 8, 8), 110.0),
    ]
    gold_index = {d: i for i, (d, _) in enumerate(gold)}
    report_dir = tmp_path / "2026-08-01"
    report_dir.mkdir()
    (report_dir / "monthly_20260801_120000.md").write_text(
        "数据截止：2026-08-01\n总分：**+0.400**（偏多）\n置信度：**55%**\n",
        encoding="utf-8",
    )
    points = replay_reports(tmp_path, gold, gold_index, bars=5, bullish=0.2, bearish=-0.2)
    assert len(points) == 1
    assert points[0].hit is True
    assert points[0].fwd_return is not None
    assert points[0].fwd_return > 0
