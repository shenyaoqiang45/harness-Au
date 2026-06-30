"""Data validation: format, units, ranges, anomalies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from gold_forecast.data_loader import DataRow, group_by_indicator


@dataclass
class ValidationIssue:
    row: DataRow
    severity: str  # rejected | pending
    reason: str


@dataclass
class ValidationResult:
    confirmed: list[DataRow] = field(default_factory=list)
    rejected: list[ValidationIssue] = field(default_factory=list)
    pending: list[ValidationIssue] = field(default_factory=list)

    @property
    def anomalies(self) -> list[ValidationIssue]:
        return self.rejected + self.pending


def load_validation_config(config_dir: Path) -> dict[str, Any]:
    rules_path = config_dir / "validation_rules.yaml"
    indicators_path = config_dir / "indicators.yaml"
    with rules_path.open(encoding="utf-8") as handle:
        rules = yaml.safe_load(handle)
    with indicators_path.open(encoding="utf-8") as handle:
        indicators = yaml.safe_load(handle)
    return {
        "rules": rules,
        "expected_units": indicators.get("units", {}),
        "expected_frequencies": indicators.get("frequencies", {}),
    }


def validate_rows(rows: list[DataRow], config_dir: Path) -> ValidationResult:
    """Validate raw rows and partition into confirmed / pending / rejected."""
    cfg = load_validation_config(config_dir)
    rules = cfg["rules"]
    expected_units = cfg["expected_units"]
    expected_frequencies = cfg["expected_frequencies"]
    non_negative = set(rules.get("non_negative", []))
    term_values = set(rules.get("term_structure_values", []))

    result = ValidationResult()

    for row in rows:
        if not row.source or row.source.lower() in ("", "unknown", "n/a"):
            result.rejected.append(
                ValidationIssue(row, "rejected", "Missing source — cannot ingest")
            )
            continue

        if not row.unit:
            result.rejected.append(
                ValidationIssue(row, "rejected", "Missing unit — cannot ingest")
            )
            continue

        expected_unit = expected_units.get(row.indicator)
        if expected_unit and row.unit != expected_unit:
            result.rejected.append(
                ValidationIssue(
                    row,
                    "rejected",
                    f"Unit mismatch: expected {expected_unit}, got {row.unit}",
                )
            )
            continue

        expected_freq = expected_frequencies.get(row.indicator)
        if expected_freq and row.frequency != expected_freq:
            result.pending.append(
                ValidationIssue(
                    row,
                    "pending",
                    f"Frequency mismatch: expected {expected_freq}, got {row.frequency}",
                )
            )
            continue

        if row.indicator in non_negative:
            num = row.numeric_value
            if num is not None and num < 0:
                result.rejected.append(
                    ValidationIssue(row, "rejected", "Negative value not allowed")
                )
                continue

        if row.indicator == "term_structure":
            if str(row.value).lower() not in term_values:
                result.rejected.append(
                    ValidationIssue(
                        row,
                        "rejected",
                        f"Invalid term_structure value: {row.value}",
                    )
                )
                continue

        range_issue = _check_range_anomaly(row, rules.get("anomaly_rules", []))
        if range_issue:
            result.pending.append(range_issue)
            continue

        result.confirmed.append(row)

    _check_time_series_anomalies(result, rules.get("anomaly_rules", []))
    return result


def _check_range_anomaly(row: DataRow, anomaly_rules: list[dict]) -> ValidationIssue | None:
    for rule in anomaly_rules:
        if rule.get("rule") != "range":
            continue
        if rule.get("indicator") != row.indicator:
            continue
        num = row.numeric_value
        if num is None:
            continue
        low, high = rule["min"], rule["max"]
        if num < low or num > high:
            return ValidationIssue(
                row,
                "pending",
                rule.get("message", f"Value {num} outside [{low}, {high}]"),
            )
    return None


def _check_time_series_anomalies(
    result: ValidationResult, anomaly_rules: list[dict]
) -> None:
    """Move confirmed rows with large daily changes to pending."""
    pct_rules = {
        r["indicator"]: r
        for r in anomaly_rules
        if r.get("rule") == "daily_pct_change"
    }
    if not pct_rules:
        return

    grouped = group_by_indicator(result.confirmed)
    still_confirmed: list[DataRow] = []

    for indicator, series in grouped.items():
        rule = pct_rules.get(indicator)
        if not rule or len(series) < 2:
            still_confirmed.extend(series)
            continue

        series_sorted = sorted(series, key=lambda r: r.date)
        flagged_dates: set[date] = set()
        for prev, curr in zip(series_sorted, series_sorted[1:]):
            # Skip long calendar gaps (weekends/holidays) to avoid overstating
            # the daily change when markets reopen.
            if (curr.date - prev.date).days > 2:
                continue
            prev_val = prev.numeric_value
            curr_val = curr.numeric_value
            if prev_val is None or curr_val is None or prev_val == 0:
                continue
            pct = abs((curr_val - prev_val) / prev_val)
            if pct > rule["threshold"]:
                flagged_dates.add(curr.date)

        for row in series_sorted:
            if row.date in flagged_dates:
                result.pending.append(
                    ValidationIssue(
                        row,
                        "pending",
                        rule.get("message", "Large daily change — pending review"),
                    )
                )
            else:
                still_confirmed.append(row)

    result.confirmed = still_confirmed
    for row in result.confirmed:
        row.status = "confirmed"
    for issue in result.pending:
        issue.row.status = "pending"
    for issue in result.rejected:
        issue.row.status = "rejected"
