"""Load and persist CSV indicator data."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = [
    "date",
    "indicator",
    "value",
    "unit",
    "source",
    "source_url",
    "updated_at",
    "frequency",
    "confidence",
]


@dataclass
class DataRow:
    date: date
    indicator: str
    value: float | str
    unit: str
    source: str
    source_url: str
    updated_at: datetime
    frequency: str
    confidence: str
    status: str = "pending"
    raw_line: int = 0

    @property
    def numeric_value(self) -> float | None:
        if isinstance(self.value, (int, float)):
            return float(self.value)
        try:
            return float(self.value)
        except (TypeError, ValueError):
            return None


def _parse_date(value: str) -> date:
    return date.fromisoformat(value.strip()[:10])


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    if "T" in text or " " in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    return datetime.combine(_parse_date(text), datetime.min.time())


def load_csv(path: Path) -> list[DataRow]:
    """Load indicator rows from a CSV file."""
    rows: list[DataRow] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"No header row in {path}")
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Missing columns in {path}: {sorted(missing)}")

        for line_no, record in enumerate(reader, start=2):
            indicator = record["indicator"].strip()
            raw_value = record["value"].strip()
            if indicator == "term_structure":
                value: float | str = raw_value.lower()
            else:
                try:
                    value = float(raw_value)
                except ValueError:
                    value = raw_value

            rows.append(
                DataRow(
                    date=_parse_date(record["date"]),
                    indicator=indicator,
                    value=value,
                    unit=record["unit"].strip(),
                    source=record["source"].strip(),
                    source_url=record["source_url"].strip(),
                    updated_at=_parse_datetime(record["updated_at"]),
                    frequency=record["frequency"].strip(),
                    confidence=record["confidence"].strip().upper(),
                    raw_line=line_no,
                )
            )
    return rows


def load_supply_events(path: Path) -> list[dict[str, Any]]:
    """Load manual supply disruption events."""
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            events.append(
                {
                    "date": _parse_date(record["date"]),
                    "event": record["event"].strip(),
                    "score": float(record["score"]),
                    "confidence": record["confidence"].strip().upper(),
                    "source": record["source"].strip(),
                    "note": record.get("note", "").strip(),
                }
            )
    return events


def write_csv(path: Path, rows: list[DataRow]) -> None:
    """Write data rows to CSV with status column."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = REQUIRED_COLUMNS + ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "date": row.date.isoformat(),
                    "indicator": row.indicator,
                    "value": row.value,
                    "unit": row.unit,
                    "source": row.source,
                    "source_url": row.source_url,
                    "updated_at": row.updated_at.isoformat(),
                    "frequency": row.frequency,
                    "confidence": row.confidence,
                    "status": row.status,
                }
            )


def group_by_indicator(rows: list[DataRow]) -> dict[str, list[DataRow]]:
    """Group rows by indicator, sorted by date ascending."""
    grouped: dict[str, list[DataRow]] = {}
    for row in rows:
        grouped.setdefault(row.indicator, []).append(row)
    for indicator in grouped:
        grouped[indicator].sort(key=lambda r: r.date)
    return grouped
