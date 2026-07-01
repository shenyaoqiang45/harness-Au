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


def test_pending_cpi_out_of_range():
    row = _row(indicator="us_cpi_yoy", value=20, unit="pct", source="FRED")
    row.frequency = "monthly"
    result = validate_rows([row], CONFIG_DIR)
    assert len(result.pending) == 1


def test_confirmed_valid_row():
    row = _row()
    result = validate_rows([row], CONFIG_DIR)
    assert len(result.confirmed) == 1
    assert result.confirmed[0].status == "confirmed"


def test_pending_abs_change_anomaly_rule(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "indicators.yaml").write_text(
        (
            "units:\n"
            "  us_cpi_yoy: pct\n"
            "frequencies:\n"
            "  us_cpi_yoy: monthly\n"
        ),
        encoding="utf-8",
    )
    (config_dir / "validation_rules.yaml").write_text(
        (
            "required_columns:\n"
            "  - date\n"
            "  - indicator\n"
            "  - value\n"
            "  - unit\n"
            "  - source\n"
            "  - source_url\n"
            "  - updated_at\n"
            "  - frequency\n"
            "  - confidence\n"
            "source_confidence_map:\n"
            "  A: 1.0\n"
            "anomaly_rules:\n"
            "  - indicator: us_cpi_yoy\n"
            "    rule: abs_change\n"
            "    threshold: 0.5\n"
            "    message: CPI abs jump too large\n"
        ),
        encoding="utf-8",
    )

    rows = [
        DataRow(
            date=date(2026, 4, 1),
            indicator="us_cpi_yoy",
            value=2.0,
            unit="pct",
            source="FRED",
            source_url="https://example.com",
            updated_at=datetime(2026, 6, 29),
            frequency="monthly",
            confidence="A",
        ),
        DataRow(
            date=date(2026, 5, 1),
            indicator="us_cpi_yoy",
            value=3.0,
            unit="pct",
            source="FRED",
            source_url="https://example.com",
            updated_at=datetime(2026, 6, 29),
            frequency="monthly",
            confidence="A",
        ),
    ]

    result = validate_rows(rows, config_dir)
    assert len(result.pending) == 1
    assert result.pending[0].reason == "CPI abs jump too large"
