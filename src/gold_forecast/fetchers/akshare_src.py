"""Akshare-backed fetchers (mostly Eastmoney/Sina)."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

import akshare as ak
import pandas as pd

from gold_forecast.fetchers import FetchedRecord, FetchResult


_CN_MONTH = re.compile(r"(\d{4})年(\d{1,2})月份")


def parse_cn_month(text: str) -> date:
    """Parse a Chinese month string such as '2024年3月份' to a date.

    Fix: use the actual last day of the month (via ``calendar.monthrange``)
    instead of the hard-coded 28th, which is incorrect for months with 30 or
    31 days and ambiguous for February in leap years.
    """
    match = _CN_MONTH.search(str(text))
    if not match:
        return pd.to_datetime(text).date()
    year, month = int(match.group(1)), int(match.group(2))
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def _records_from_frame(
    frame: pd.DataFrame,
    indicator: str,
    date_col: str,
    value_col: str,
    cfg: dict,
    cutoff: date,
    date_parser=None,
) -> list[FetchedRecord]:
    rows: list[FetchedRecord] = []
    for _, row in frame.iterrows():
        raw_date = row[date_col]
        row_date = date_parser(raw_date) if date_parser else pd.to_datetime(raw_date).date()
        if row_date < cutoff:
            continue
        value = row[value_col]
        if pd.isna(value):
            continue
        num = float(value)
        rows.append(
            FetchedRecord(
                date=row_date,
                indicator=indicator,
                value=round(num, 4),
                unit=cfg["unit"],
                source=cfg["source"],
                source_url=cfg["source_url"],
                frequency=cfg["frequency"],
                confidence=cfg["confidence"],
                note=cfg.get("note", ""),
            )
        )
    return rows


def fetch_akshare(indicators_cfg: dict, lookback_days: int) -> FetchResult:
    result = FetchResult()
    cutoff = (datetime.now() - timedelta(days=lookback_days)).date()

    for indicator, cfg in indicators_cfg.items():
        func_name = cfg["func"]
        try:
            func = getattr(ak, func_name)
            kwargs = cfg.get("kwargs", {})
            frame = func(**kwargs)

            date_col = cfg["date_col"]
            value_col = cfg["value_col"]
            parser = parse_cn_month if cfg.get("transform") == "parse_cn_month" else None

            result.records.extend(
                _records_from_frame(
                    frame, indicator, date_col, value_col, cfg, cutoff, parser
                )
            )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"akshare:{indicator}: {exc}")

    return result
