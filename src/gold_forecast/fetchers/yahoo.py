"""Yahoo Finance market data fetcher."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

from gold_forecast.fetchers import FetchedRecord, FetchResult

_CHART_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

LB_TO_TON = 2204.6226218488
OUTLIER_DAILY_PCT = 0.08


def _smooth_daily_outliers(
    records: list[FetchedRecord],
    threshold: float = OUTLIER_DAILY_PCT,
    max_passes: int = 10,
) -> list[FetchedRecord]:
    """Replace single-day spikes (e.g. COMEX roll bad ticks) via neighbor averaging.

    The most-recent data point is intentionally excluded from smoothing: a large
    move on the latest date may be a genuine market event and must not be silently
    overwritten.  Only interior points that have both a preceding *and* a following
    neighbour are eligible for replacement.
    """
    if len(records) < 3:
        # Need at least 3 points to have an interior candidate.
        return records

    ordered = sorted(records, key=lambda r: r.date)
    values = [float(r.value) for r in ordered]
    last_idx = len(values) - 1

    for _ in range(max_passes):
        changed = False
        # Fix: iterate only up to last_idx - 1 so the final (most-recent)
        # data point is never smoothed away.
        for i in range(1, last_idx):
            prev = values[i - 1]
            if not prev:
                continue
            if abs((values[i] - prev) / prev) <= threshold:
                continue
            # Interior spike: replace with average of neighbours.
            values[i] = round((prev + values[i + 1]) / 2, 4)
            changed = True
        if not changed:
            break

    smoothed: list[FetchedRecord] = []
    for rec, new_val in zip(ordered, values):
        old_val = float(rec.value)
        if old_val == new_val:
            smoothed.append(rec)
            continue
        note = rec.note or ""
        tag = "Yahoo outlier smoothed"
        if tag not in note:
            note = f"{note}; {tag}" if note else tag
        smoothed.append(
            FetchedRecord(
                date=rec.date,
                indicator=rec.indicator,
                value=new_val,
                unit=rec.unit,
                source=rec.source,
                source_url=rec.source_url,
                frequency=rec.frequency,
                confidence=rec.confidence,
                updated_at=rec.updated_at,
                note=note,
            )
        )
    return smoothed


def _history_chart_api(ticker: str, lookback_days: int) -> pd.DataFrame:
    """v8 chart API fallback when yfinance is rate-limited."""
    period = "2y" if lookback_days > 365 else "1y"
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(ticker, safe='')}?range={period}&interval=1d"
    )
    req = Request(url, headers={"User-Agent": _CHART_UA, "Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    results = (payload.get("chart") or {}).get("result") or []
    if not results:
        return pd.DataFrame()
    timestamps = results[0].get("timestamp") or []
    closes = ((results[0].get("indicators") or {}).get("quote") or [{}])[0].get(
        "close"
    ) or []
    idx = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(
        "America/New_York"
    )
    rows = [
        {
            "Date": ts.to_pydatetime().replace(tzinfo=None).replace(
                hour=0, minute=0, second=0, microsecond=0
            ),
            "Close": float(close),
        }
        for ts, close in zip(idx, closes)
        if close is not None
    ]
    return pd.DataFrame(rows)


def _normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.reset_index()
    date_col = "Date" if "Date" in frame.columns else frame.columns[0]
    frame["Date"] = pd.to_datetime(frame[date_col]).dt.tz_localize(None)
    return frame


def _history(ticker: str, lookback_days: int) -> pd.DataFrame:
    frame = pd.DataFrame()
    yf_error: Exception | None = None
    try:
        for period in ("2y", "1y", "6mo", "3mo", "1mo"):
            if lookback_days > 365 and period in ("3mo", "1mo"):
                continue
            frame = yf.Ticker(ticker).history(period=period, auto_adjust=False)
            if not frame.empty:
                break

        if frame.empty:
            period = "2y" if lookback_days > 365 else "1y"
            downloaded = yf.download(
                ticker,
                period=period,
                progress=False,
                auto_adjust=False,
            )
            if not downloaded.empty:
                frame = downloaded
    except Exception as exc:  # noqa: BLE001
        yf_error = exc
        frame = pd.DataFrame()

    if not frame.empty:
        return _normalize_history(frame)

    chart = _history_chart_api(ticker, lookback_days)
    if not chart.empty:
        return chart
    if yf_error is not None:
        raise yf_error
    return chart


def fetch_yahoo(
    indicators_cfg: dict,
    lookback_days: int,
) -> FetchResult:
    result = FetchResult()
    for indicator, cfg in indicators_cfg.items():
        ticker = cfg["ticker"]
        try:
            frame = _history(ticker, lookback_days)
            if frame.empty:
                result.errors.append(f"yahoo:{indicator}: no data for {ticker}")
                continue

            cutoff = datetime.now() - timedelta(days=lookback_days)
            indicator_records: list[FetchedRecord] = []
            for _, row in frame.iterrows():
                row_date = row["Date"].date()
                if row_date < cutoff.date():
                    continue
                value = float(row["Close"])
                if cfg.get("transform") == "comex_lb_to_usd_ton":
                    value = value * LB_TO_TON

                indicator_records.append(
                    FetchedRecord(
                        date=row_date,
                        indicator=indicator,
                        value=round(value, 4),
                        unit=cfg["unit"],
                        source=cfg["source"],
                        source_url=cfg["source_url"],
                        frequency=cfg["frequency"],
                        confidence=cfg["confidence"],
                        note=cfg.get("note", ""),
                    )
                )
            result.records.extend(_smooth_daily_outliers(indicator_records))
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"yahoo:{indicator}: {exc}")
    return result
