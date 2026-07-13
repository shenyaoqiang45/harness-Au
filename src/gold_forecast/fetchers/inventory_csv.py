"""Local CSV-backed gold inventory fetcher.

Reads ``data/raw/gold_inventory.csv`` which contains daily exchange / vault
stocks.  This replaces the broken Eastmoney LME mirror and the CME XLS
endpoint (403 Forbidden) with a manually maintained CSV.

Supported CSV schemas (first matching column wins per indicator):

Legacy::
    日期, LME库存(公吨), SHFE库存(吨), COMEX库存(公吨), …

Current (2026-07+)::
    日期, COMEX黄金库存(吨), LBMA伦敦金库(吨), SHFE黄金仓单(吨), …
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from gold_forecast.fetchers import FetchedRecord, FetchResult

# indicator -> candidate CSV columns (first hit used)
_INDICATOR_COLUMNS: dict[str, tuple[str, ...]] = {
    "comex_inventory": ("COMEX黄金库存(吨)", "COMEX库存(公吨)"),
    "lme_inventory": ("LBMA伦敦金库(吨)", "LME库存(公吨)"),
    "shfe_inventory": ("SHFE黄金仓单(吨)", "SHFE库存(吨)"),
}

_DEFAULT_UNITS: dict[str, str] = {
    "comex_inventory": "ton",
    "lme_inventory": "ton",
    "shfe_inventory": "ton",
}

# column -> (source label, source_url) for traceability
_COLUMN_SOURCES: dict[str, tuple[str, str]] = {
    "COMEX黄金库存(吨)": (
        "手动维护-COMEX",
        "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls",
    ),
    "COMEX库存(公吨)": (
        "手动维护-COMEX",
        "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls",
    ),
    "LBMA伦敦金库(吨)": (
        "手动维护-LBMA",
        "https://www.lbma.org.uk/prices-and-data/london-vault-data",
    ),
    "LME库存(公吨)": (
        "手动维护-LME",
        "https://www.lme.com/Market-data/Reports-and-data/Warehouse-and-stock-reports",
    ),
    "SHFE黄金仓单(吨)": (
        "手动维护-SHFE",
        "https://www.shfe.com.cn/reports/businessdata/prmsummary/",
    ),
    "SHFE库存(吨)": (
        "手动维护-SHFE",
        "https://www.shfe.com.cn/reports/businessdata/prmsummary/",
    ),
}


def _resolve_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in columns:
            return name
    return None


def fetch_inventory_csv(
    csv_path: Path,
    lookback_days: int,
    indicators_cfg: dict | None = None,
) -> FetchResult:
    """Load gold inventory data from a local CSV file."""
    result = FetchResult()
    cfg = indicators_cfg or {}

    if not csv_path.exists():
        result.errors.append(
            f"inventory_csv: file not found: {csv_path}. "
            "Please place gold_inventory.csv in data/raw/."
        )
        return result

    try:
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
    col_names = list(df.columns)

    for indicator, candidates in _INDICATOR_COLUMNS.items():
        col = _resolve_column(col_names, candidates)
        if col is None:
            result.warnings.append(
                f"inventory_csv: no column for {indicator} "
                f"(tried {', '.join(candidates)}), skipping"
            )
            continue

        ind_cfg = cfg.get(indicator, {})
        source, source_url = _COLUMN_SOURCES.get(col, ("手动维护", ""))

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
                    unit=ind_cfg.get("unit", _DEFAULT_UNITS[indicator]),
                    source=ind_cfg.get("source", source),
                    source_url=ind_cfg.get("source_url", source_url),
                    frequency=ind_cfg.get("frequency", "daily"),
                    confidence=ind_cfg.get("confidence", "B"),
                    note=ind_cfg.get("note", f"Loaded from {csv_path.name} ({col})"),
                )
            )

    result.warnings.append(
        f"inventory_csv: loaded {len(result.records)} records from {csv_path.name}"
    )
    return result
