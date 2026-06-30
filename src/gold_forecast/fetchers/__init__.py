"""Shared types for data fetchers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class FetchedRecord:
    date: date
    indicator: str
    value: float | str
    unit: str
    source: str
    source_url: str
    frequency: str
    confidence: str
    updated_at: datetime = field(default_factory=datetime.now)
    note: str = ""


@dataclass
class FetchResult:
    records: list[FetchedRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def extend(self, other: FetchResult) -> None:
        self.records.extend(other.records)
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)
