"""Local CSV-backed gold inventory fetcher.

Reads ``data/raw/gold_inventory.csv`` which contains daily LME, SHFE and
COMEX warehouse stocks.  This replaces the broken Eastmoney LME mirror and
the CME XLS endpoint (403 Forbidden) with a manually maintained CSV that
can be updated periodically.

Expected CSV columns (BOM-tolerant, Chinese headers):
    日期, LME库存(公吨), SHFE库存(吨), COMEX库存(公吨)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from gold_forecast.fetchers import FetchedRecord, FetchResult

# Mapping: CSV column -> (indicator_name, unit)
_COL_MAP = {
    "LME库存(公吨)": ("lme_inventory", "ton"),
    "SHFE库存(吨)": ("shfe_inventory", "ton"),
    "COMEX库存(公吨)": ("comex_inventory", "ton"),
}

_SOURCE_MAP = {
    "lme_inventory": ("手动维护-LME", "https://www.lme.com/Market-data/Reports-and-data/Warehouse-and-stock-reports"),
    "shfe_inventory": ("手动维护-SHFE", "https://www.shfe.com.cn/reports/businessdata/prmsummary/"),
    "comex_inventory": ("手动维护-COMEX", "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls"),
}


def fetch_inventory_csv(
    csv_path: Path,
    lookback_days: int,
    indicators_cfg: dict | None = None,
) -> FetchResult:
    """Load gold inventory data from a local CSV file.

    Parameters
    ----------
    csv_path:
        Absolute path to the inventory CSV (``data/raw/gold_inventory.csv``).
    lookback_days:
        Only records newer than ``now - lookback_days`` are returned.
    indicators_cfg:
        Optional per-indicator config overrides (confidence, note, …).
        Falls back to sensible defaults when absent.
    """
    result = FetchResult()
    cfg = indicators_cfg or {}

    if not csv_path.exists():
        result.errors.append(
            f"inventory_csv: file not found: {csv_path}. "
            "Please place gold_inventory.csv in data/raw/."
        )
        return result

    try:
        # encoding_errors="replace" tolerates BOM and mixed encodings
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"inventory_csv: failed to read {csv_path}: {exc}")
        return result

    if "日期" not in df.columns:
        result.errors.append(
            f"inventory_csv: '日期' column not found. Columns: {list(df.columns)}"
        )
        return result

    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df = df.dropna(subset=["日期"])
    cutoff = (datetime.now() - timedelta(days=lookback_days)).date()

    for col, (indicator, default_unit) in _COL_MAP.items():
        if col not in df.columns:
            result.warnings.append(
                f"inventory_csv: column '{col}' not found, skipping {indicator}"
            )
            continue

        ind_cfg = cfg.get(indicator, {})
        source, source_url = _SOURCE_MAP[indicator]

        series = df[["日期", col]].copy()
        series[col] = pd.to_numeric(series[col], errors="coerce")
        series = series.dropna(subset=[col])

        for _, row in series.iterrows():
            row_date = row["日期"].date()
            if row_date < cutoff:
                continue
            result.records.append(
                FetchedRecord(
                    date=row_date,
                    indicator=indicator,
                    value=round(float(row[col]), 4),
                    unit=ind_cfg.get("unit", default_unit),
                    source=ind_cfg.get("source", source),
                    source_url=ind_cfg.get("source_url", source_url),
                    frequency=ind_cfg.get("frequency", "daily"),
                    confidence=ind_cfg.get("confidence", "B"),
                    note=ind_cfg.get("note", f"Loaded from {csv_path.name}"),
                )
            )

    result.warnings.append(
        f"inventory_csv: loaded {len(result.records)} records from {csv_path.name}"
    )
    return result
