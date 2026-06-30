"""Tests for data validation."""

from datetime import date, datetime
from pathlib import Path

import pytest

from gold_forecast.data_loader import DataRow
from gold_forecast.validator import validate_rows

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _row(
    indicator: str = "lme_gold_price",
    value: float = 2350.0,
    unit: str = "USD/oz",
    source: str = "comex",
    confidence: str = "A",
) -> DataRow:
    return DataRow(
        date=date(2026, 6, 29),
        indicator=indicator,
        value=value,
        unit=unit,
        source=source,
        source_url="https://example.com",
        updated_at=datetime(2026, 6, 29),
        frequency="daily",
        confidence=confidence,
    )


def test_reject_missing_source():
    row = _row(source="")
    result = validate_rows([row], CONFIG_DIR)
    assert len(result.rejected) == 1
    assert "source" in result.rejected[0].reason.lower()


def test_reject_negative_inventory():
    row = _row(indicator="lme_inventory", value=-100, unit="ton")
    result = validate_rows([row], CONFIG_DIR)
    assert len(result.rejected) == 1


def test_reject_unit_mismatch():
    row = _row(unit="CNY")
    result = validate_rows([row], CONFIG_DIR)
    assert len(result.rejected) == 1
    assert "Unit mismatch" in result.rejected[0].reason


def test_pending_pmi_out_of_range():
    row = _row(indicator="china_pmi", value=70, unit="index", source="nbs")
    row.frequency = "monthly"
    result = validate_rows([row], CONFIG_DIR)
    assert len(result.pending) == 1


def test_confirmed_valid_row():
    row = _row()
    result = validate_rows([row], CONFIG_DIR)
    assert len(result.confirmed) == 1
    assert result.confirmed[0].status == "confirmed"
