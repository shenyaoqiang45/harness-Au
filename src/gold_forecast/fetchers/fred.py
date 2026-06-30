"""FRED API / CSV fetcher."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from io import StringIO
from urllib.parse import urlencode

import pandas as pd
import requests

from gold_forecast.fetchers import FetchedRecord, FetchResult


def _fred_csv(series_id: str) -> pd.DataFrame:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?{urlencode({'id': series_id})}"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    frame = pd.read_csv(StringIO(response.text))
    date_col = frame.columns[0]
    value_col = frame.columns[1]
    frame[date_col] = pd.to_datetime(frame[date_col])
    frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
    frame = frame.dropna(subset=[value_col])
    frame = frame.rename(columns={date_col: "date", value_col: "value"})
    return frame


def _fred_api(series_id: str, api_key: str, lookback_days: int) -> pd.DataFrame:
    start = (datetime.now() - timedelta(days=lookback_days)).date().isoformat()
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    rows = []
    for obs in payload.get("observations", []):
        if obs.get("value") in (".", None, ""):
            continue
        rows.append({"date": obs["date"], "value": float(obs["value"])})
    return pd.DataFrame(rows)


def fetch_fred_series(
    series_id: str,
    indicator: str,
    cfg: dict,
    lookback_days: int,
) -> FetchResult:
    result = FetchResult()
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    fetch_lookback = lookback_days + 400 if cfg.get("transform") == "yoy_pct" else lookback_days
    try:
        if api_key:
            frame = _fred_api(series_id, api_key, fetch_lookback)
            result.warnings.append(f"fred:{indicator}: loaded via API")
        else:
            frame = _fred_csv(series_id)
            result.warnings.append(
                f"fred:{indicator}: loaded via public CSV (set FRED_API_KEY for API)"
            )
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"fred:{indicator}: {exc}")
        return result

    if frame.empty:
        result.errors.append(f"fred:{indicator}: empty series {series_id}")
        return result

    frame = frame.sort_values("date")
    if cfg.get("transform") == "yoy_pct":
        frame["value"] = frame["value"].pct_change(12) * 100
        frame = frame.dropna(subset=["value"])

    cutoff = (datetime.now() - timedelta(days=lookback_days)).date()
    for _, row in frame.iterrows():
        row_date = pd.to_datetime(row["date"]).date()
        if row_date < cutoff:
            continue
        result.records.append(
            FetchedRecord(
                date=row_date,
                indicator=indicator,
                value=float(row["value"]),
                unit=cfg["unit"],
                source=cfg["source"],
                source_url=cfg.get("source_url") or f"https://fred.stlouisfed.org/series/{series_id}",
                frequency=cfg["frequency"],
                confidence=cfg["confidence"],
                note=cfg.get("note", ""),
            )
        )
    return result


def fetch_fred(indicators_cfg: dict, lookback_days: int) -> FetchResult:
    result = FetchResult()
    for indicator, cfg in indicators_cfg.items():
        part = fetch_fred_series(cfg["series_id"], indicator, cfg, lookback_days)
        result.extend(part)
    return result
