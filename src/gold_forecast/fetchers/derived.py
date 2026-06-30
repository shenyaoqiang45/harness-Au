"""Derived indicators from fetched market data."""

from __future__ import annotations

from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import yfinance as yf

from gold_forecast.fetchers import FetchedRecord, FetchResult

LOOKBACK = 120
TROY_OZ_PER_GRAM = 31.1034768


def _latest_fx() -> float:
    frame = yf.Ticker("USDCNY=X").history(period="10d")
    if frame.empty:
        return 7.2
    return float(frame["Close"].iloc[-1])


def shfe_lme_premium(lookback_days: int = LOOKBACK) -> FetchResult:
    result = FetchResult()
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")
        shfe = ak.futures_main_sina(symbol="AU0", start_date=start, end_date=end)
        comex = yf.Ticker("GC=F").history(
            start=(datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        )
        if shfe.empty or comex.empty:
            result.errors.append("derived:spot_premium: missing SHFE or COMEX history")
            return result

        shfe = shfe.rename(columns={"日期": "date", "收盘价": "shfe_close"})
        shfe["date"] = pd.to_datetime(shfe["date"])
        comex = comex.reset_index()
        comex["Date"] = pd.to_datetime(comex["Date"]).dt.tz_localize(None)
        fx = _latest_fx()

        merged = pd.merge_asof(
            shfe.sort_values("date"),
            comex[["Date", "Close"]].sort_values("Date"),
            left_on="date",
            right_on="Date",
            direction="backward",
        )
        merged["comex_usd_oz"] = merged["Close"]
        merged["shfe_usd_oz"] = merged["shfe_close"] * TROY_OZ_PER_GRAM / fx
        merged["premium"] = merged["shfe_usd_oz"] - merged["comex_usd_oz"]

        for _, row in merged.dropna(subset=["premium"]).iterrows():
            result.records.append(
                FetchedRecord(
                    date=row["date"].date(),
                    indicator="spot_premium",
                    value=round(float(row["premium"]), 2),
                    unit="USD/oz",
                    source="derived",
                    source_url="",
                    frequency="daily",
                    confidence="C",
                    note="SHFE AU0 vs COMEX GC=F after USDCNY conversion (CNY/g to USD/oz)",
                )
            )
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"derived:spot_premium: {exc}")
    return result


def premium_to_curve(existing: list[FetchedRecord], lookback_days: int = LOOKBACK) -> FetchResult:
    result = FetchResult()
    premiums = sorted(
        [r for r in existing if r.indicator == "spot_premium"],
        key=lambda r: r.date,
    )
    if not premiums:
        result.warnings.append("derived:term_structure: no spot_premium available")
        return result

    for rec in premiums[-lookback_days:]:
        label = "backwardation" if float(rec.value) > 0 else "contango"
        result.records.append(
            FetchedRecord(
                date=rec.date,
                indicator="term_structure",
                value=label,
                unit="label",
                source="derived",
                source_url="",
                frequency="daily",
                confidence="C",
                note="Inferred from SHFE-COMEX gold premium sign",
            )
        )
    return result


def fetch_derived(
    indicators_cfg: dict,
    existing: list[FetchedRecord],
    lookback_days: int,
) -> FetchResult:
    result = FetchResult()
    for indicator, cfg in indicators_cfg.items():
        func = cfg.get("func")
        if func == "shfe_lme_premium":
            part = shfe_lme_premium(lookback_days)
        elif func == "premium_to_curve":
            part = premium_to_curve(existing + result.records, lookback_days)
        elif func == "composite_global_pmi":
            part = composite_global_pmi(existing + result.records)
        else:
            result.errors.append(f"derived:{indicator}: unknown func {func}")
            continue
        result.extend(part)
    return result
