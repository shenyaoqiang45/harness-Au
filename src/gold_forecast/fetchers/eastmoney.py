"""Eastmoney / LME inventory fetcher."""

from __future__ import annotations

from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import requests

from gold_forecast.fetchers import FetchedRecord, FetchResult

EM_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _em_get(report: str, page_size: int = 2000) -> pd.DataFrame:
    params = {
        "reportName": report,
        "columns": "ALL",
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "client": "WEB",
    }
    response = requests.get(EM_URL, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success") or not payload.get("result", {}).get("data"):
        raise ValueError(payload.get("message", f"eastmoney empty: {report}"))
    return pd.DataFrame(payload["result"]["data"])


def _lme_gold_stock() -> pd.DataFrame:
    frame = ak.macro_euro_lme_stock()
    if "金-库存" not in frame.columns:
        available = ", ".join(frame.columns.tolist())
        raise ValueError(
            f"LME gold inventory column '金-库存' not available. Available columns: {available}"
        )
    out = frame[["日期", "金-库存"]].copy()
    out.columns = ["date", "value"]
    out["date"] = pd.to_datetime(out["date"])
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out.dropna()


def fetch_eastmoney(indicators_cfg: dict, lookback_days: int) -> FetchResult:
    result = FetchResult()
    cutoff = (datetime.now() - timedelta(days=lookback_days)).date()

    for indicator, cfg in indicators_cfg.items():
        try:
            if cfg.get("transform") == "lme_gold_stock":
                frame = _lme_gold_stock()
            else:
                frame = _em_get(cfg["report"])
                date_col = cfg["date_col"]
                value_col = cfg["value_col"]
                frame = frame[[date_col, value_col]].rename(
                    columns={date_col: "date", value_col: "value"}
                )
                frame["date"] = pd.to_datetime(frame["date"])
                frame["value"] = pd.to_numeric(frame["value"], errors="coerce")

            frame = frame.dropna(subset=["value"])
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
                        source_url=cfg["source_url"],
                        frequency=cfg["frequency"],
                        confidence=cfg["confidence"],
                        note=cfg.get("note", ""),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"eastmoney:{indicator}: {exc}")

    return result
