"""Tests for CLI helpers."""

from datetime import datetime
from pathlib import Path

from gold_forecast.cli import _resolve_report_output_path


def test_report_output_is_archived_by_date_and_timestamp():
    requested = Path("reports/monthly.md")
    ts = datetime(2026, 7, 1, 10, 12, 13)

    out = _resolve_report_output_path(requested, ts)

    assert out.parts[-3] == "reports"
    assert out.parts[-2] == "2026-07-01"
    assert out.name == "monthly_20260701_101213.md"


def test_non_reports_output_path_is_unchanged():
    requested = Path("data/out.md")
    ts = datetime(2026, 7, 1, 10, 12, 13)

    out = _resolve_report_output_path(requested, ts)

    assert out == requested
