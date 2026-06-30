"""Orchestrate live data collection into standard CSV."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import yaml

from gold_forecast.data_loader import REQUIRED_COLUMNS, DataRow
from gold_forecast.fetchers import FetchedRecord, FetchResult
from gold_forecast.fetchers.akshare_src import fetch_akshare
from gold_forecast.fetchers.comex import fetch_comex
from gold_forecast.fetchers.derived import fetch_derived
from gold_forecast.fetchers.eastmoney import fetch_eastmoney
from gold_forecast.fetchers.fred import fetch_fred
from gold_forecast.fetchers.yahoo import fetch_yahoo
from gold_forecast.missing_sources import MissingSource


def load_sources_config(config_dir: Path) -> dict:
    with (config_dir / "sources.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def collect_all(config_dir: Path, project_root: Path) -> FetchResult:
    cfg = load_sources_config(config_dir)
    lookback = int(cfg.get("lookback_days", 400))
    merged = FetchResult()

    sources = cfg.get("sources", {})
    if sources.get("yahoo", {}).get("enabled", True):
        merged.extend(fetch_yahoo(sources["yahoo"]["indicators"], lookback))
    if sources.get("fred", {}).get("enabled", True):
        merged.extend(fetch_fred(sources["fred"]["indicators"], lookback))
    if sources.get("eastmoney", {}).get("enabled", True):
        merged.extend(fetch_eastmoney(sources["eastmoney"]["indicators"], lookback))
    if sources.get("akshare", {}).get("enabled", True):
        merged.extend(fetch_akshare(sources["akshare"]["indicators"], lookback))
    if sources.get("cme", {}).get("enabled", True):
        merged.extend(fetch_comex(sources["cme"]["indicators"], lookback))

    if sources.get("derived", {}).get("enabled", True):
        merged.extend(
            fetch_derived(sources["derived"]["indicators"], merged.records, lookback)
        )

    return merged


def _record_key(rec: FetchedRecord) -> tuple:
    if rec.frequency == "monthly":
        return (rec.indicator, f"{rec.date:%Y-%m}")
    return (rec.indicator, rec.date.isoformat())


def merge_records(
    existing: list[FetchedRecord],
    incoming: list[FetchedRecord],
) -> list[FetchedRecord]:
    """Merge by indicator+date; incoming overwrites existing."""
    by_key: dict[tuple, FetchedRecord] = {_record_key(r): r for r in existing}
    for rec in incoming:
        by_key[_record_key(rec)] = rec
    return sorted(by_key.values(), key=lambda r: (r.indicator, r.date))


def write_fetched_csv(path: Path, records: list[FetchedRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = REQUIRED_COLUMNS + ["note"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow(
                {
                    "date": rec.date.isoformat(),
                    "indicator": rec.indicator,
                    "value": rec.value,
                    "unit": rec.unit,
                    "source": rec.source,
                    "source_url": rec.source_url,
                    "updated_at": rec.updated_at.isoformat(),
                    "frequency": rec.frequency,
                    "confidence": rec.confidence,
                    "note": rec.note,
                }
            )


def write_fetch_log(
    path: Path, result: FetchResult, missing: list[MissingSource] | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now().isoformat(),
        "record_count": len(result.records),
        "warnings": result.warnings,
        "errors": result.errors,
        "indicators": sorted({r.indicator for r in result.records}),
        "missing_sources": [asdict(item) for item in (missing or [])],
        "missing_count": len(missing or []),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_fetch(
    config_dir: Path,
    project_root: Path,
    output_path: Path | None = None,
    merge_history: bool = True,
) -> FetchResult:
    output_path = output_path or project_root / "data" / "raw" / "live.csv"
    history_path = project_root / "data" / "raw" / "history.csv"

    existing: list[FetchedRecord] = []
    if merge_history and output_path.exists():
        from gold_forecast.data_loader import load_csv

        for row in load_csv(output_path):
            existing.append(
                FetchedRecord(
                    date=row.date,
                    indicator=row.indicator,
                    value=row.value,
                    unit=row.unit,
                    source=row.source,
                    source_url=row.source_url,
                    frequency=row.frequency,
                    confidence=row.confidence,
                    updated_at=row.updated_at,
                )
            )

    from gold_forecast.missing_sources import (
        compute_missing_sources,
        unwired_indicator_names,
        write_missing_sources_log,
    )

    unwired = unwired_indicator_names(config_dir)
    existing = [r for r in existing if r.indicator not in unwired]

    fetched = collect_all(config_dir, project_root)
    merged = merge_records(existing, fetched.records)
    merged = [r for r in merged if r.indicator not in unwired]
    present = {r.indicator for r in merged}
    missing = compute_missing_sources(config_dir, present, fetched.errors)
    write_fetched_csv(output_path, merged)
    if merge_history:
        write_fetched_csv(history_path, merged)
    audit_dir = project_root / "data" / "audit"
    write_fetch_log(audit_dir / "fetch_log.json", fetched, missing)
    write_missing_sources_log(audit_dir / "missing_sources.json", missing)
    return fetched
