"""Tests for the unattended quality gate."""

from datetime import date, datetime
from pathlib import Path

from gold_forecast.collector import write_fetched_csv
from gold_forecast.fetchers import FetchedRecord, FetchResult
from gold_forecast.unattended import (
    dedupe_incoming,
    evaluate_gate,
    protect_trusted_rows,
    run_unattended,
    update_fail_streak,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def _rec(
    indicator: str,
    day: str,
    value: float,
    *,
    unit: str,
    frequency: str = "daily",
) -> FetchedRecord:
    return FetchedRecord(
        date=date.fromisoformat(day),
        indicator=indicator,
        value=value,
        unit=unit,
        source="test",
        source_url="https://example.test",
        frequency=frequency,
        confidence="A",
        updated_at=datetime(2026, 10, 1, 8, 0, 0),
    )


def _price(day: str, value: float) -> FetchedRecord:
    return _rec("lme_gold_price", day, value, unit="USD/oz")


def _dxy(day: str, value: float) -> FetchedRecord:
    return _rec("dxy", day, value, unit="index")


def _rate(day: str, value: float) -> FetchedRecord:
    return _rec("us_10y_real_rate", day, value, unit="pct")


def _base(day: str = "2026-10-14") -> list[FetchedRecord]:
    return [_price(day, 4100.0), _dxy(day, 102.0), _rate(day, 1.8)]


def test_duplicate_incoming_rows_collapse_to_one():
    rows, dropped = dedupe_incoming([_dxy("2026-10-14", 100.0), _dxy("2026-10-14", 101.0)])
    assert dropped == 1
    assert len(rows) == 1
    assert rows[0].value == 101.0


def test_anomaly_does_not_overwrite_trusted_price():
    existing = _base("2026-10-13")
    incoming = _base("2026-10-13")
    incoming[0] = _price("2026-10-13", 2500.0)
    protected, notes = protect_trusted_rows(existing, incoming, CONFIG)
    gold = next(rec for rec in protected if rec.indicator == "lme_gold_price")
    assert gold.value == 4100.0
    assert any(note.startswith("anomaly_kept_previous") for note in notes)


def test_rejected_new_row_is_not_ingested():
    existing = _base()
    bad = _price("2026-10-15", 100.0)
    bad.unit = ""
    protected, notes = protect_trusted_rows(existing, [bad], CONFIG)
    assert all(rec.date.isoformat() != "2026-10-15" for rec in protected)
    assert any(note.startswith("rejected_dropped") for note in notes)


def test_weekday_fetch_failure_keeps_history_and_fails():
    existing = _base("2026-10-14")
    fetched = FetchResult(errors=["yahoo:lme_gold_price: Too Many Requests"])
    decision = evaluate_gate(existing, existing, fetched, CONFIG, date(2026, 10, 15), [], 0)
    assert decision.status == "failed"
    assert decision.publish is False
    assert decision.notify is True
    assert decision.exit_code == 1
    assert "lme_gold_price" in decision.categories["fetch_failed"]


def test_weekend_without_new_bar_is_market_closed():
    existing = _base("2026-10-16")
    fetched = FetchResult()
    decision = evaluate_gate(existing, existing, fetched, CONFIG, date(2026, 10, 17), [], 0)
    assert decision.status == "unchanged"
    assert decision.publish is False
    assert decision.exit_code == 0
    assert decision.categories["market_closed"]


def test_monthly_inside_lag_is_not_a_failure():
    existing = _base("2026-10-14")
    existing.append(
        _rec("us_cpi_yoy", "2026-09-15", 2.5, unit="pct", frequency="monthly")
    )
    fetched = FetchResult(records=list(existing))
    decision = evaluate_gate(
        existing, existing, fetched, CONFIG, date(2026, 10, 15), [], 0
    )
    assert decision.status == "unchanged"
    assert any(item.startswith("us_cpi_yoy:") for item in decision.categories["not_published"])


def test_new_confirmed_bar_publishes():
    existing = _base("2026-10-14")
    incoming = [
        _price("2026-10-15", 4110.0),
        _dxy("2026-10-15", 102.1),
        _rate("2026-10-15", 1.81),
    ]
    protected, _notes = protect_trusted_rows(existing, incoming, CONFIG)
    fetched = FetchResult(records=incoming)
    decision = evaluate_gate(
        existing, protected, fetched, CONFIG, date(2026, 10, 15), [], 0
    )
    assert decision.status == "success"
    assert decision.publish is True
    assert decision.exit_code == 0


def test_repeated_run_does_not_rewrite_history_or_add_a_second_report(tmp_path, monkeypatch):
    history = tmp_path / "data" / "raw" / "history.csv"
    existing = _base("2026-10-14")
    write_fetched_csv(history, existing)
    original = history.read_bytes()
    calls = {"n": 0}

    def _fetch(_config, _root):
        calls["n"] += 1
        if calls["n"] == 1:
            return FetchResult(
                records=[
                    _price("2026-10-15", 4110.0),
                    _dxy("2026-10-15", 102.1),
                    _rate("2026-10-15", 1.81),
                ]
            )
        return FetchResult(records=[])

    monkeypatch.setattr("gold_forecast.unattended.collect_all", _fetch)
    first = run_unattended(CONFIG, tmp_path, as_of=date(2026, 10, 15))
    reports = list((tmp_path / "reports").rglob("*.md"))
    assert first == 0
    assert len(reports) == 1
    after_first = history.read_bytes()
    assert after_first != original

    second = run_unattended(CONFIG, tmp_path, as_of=date(2026, 10, 15))
    reports = list((tmp_path / "reports").rglob("*.md"))
    assert second == 0
    assert len(reports) == 1
    assert history.read_bytes() == after_first
    status = (tmp_path / "data" / "audit" / "run_status.json").read_text(encoding="utf-8")
    assert '"status": "unchanged"' in status


def test_fetch_failure_does_not_overwrite_history_file(tmp_path, monkeypatch):
    history = tmp_path / "data" / "raw" / "history.csv"
    write_fetched_csv(history, _base("2026-10-14"))
    original = history.read_bytes()
    monkeypatch.setattr(
        "gold_forecast.unattended.collect_all",
        lambda *_args, **_kwargs: FetchResult(
            errors=["yahoo:lme_gold_price: Too Many Requests"]
        ),
    )
    code = run_unattended(CONFIG, tmp_path, as_of=date(2026, 10, 15))
    assert code == 1
    assert history.read_bytes() == original
    assert not list((tmp_path / "reports").rglob("*.md"))


def test_report_failure_restores_history(tmp_path, monkeypatch):
    history = tmp_path / "data" / "raw" / "history.csv"
    write_fetched_csv(history, _base("2026-10-14"))
    original = history.read_bytes()

    def _fetch(_config, _root):
        return FetchResult(
            records=[
                _price("2026-10-15", 4110.0),
                _dxy("2026-10-15", 102.1),
                _rate("2026-10-15", 1.81),
            ]
        )

    monkeypatch.setattr("gold_forecast.unattended.collect_all", _fetch)
    monkeypatch.setattr(
        "gold_forecast.cli.run_pipeline",
        lambda *_args, **_kwargs: 1,
    )
    code = run_unattended(CONFIG, tmp_path, as_of=date(2026, 10, 15))
    assert code == 1
    assert history.read_bytes() == original
    status = (tmp_path / "data" / "audit" / "run_status.json").read_text(encoding="utf-8")
    assert '"status": "failed"' in status
    assert '"publish": false' in status


def test_fail_streak_resets_after_success():
    assert update_fail_streak(0, "failed") == 1
    assert update_fail_streak(2, "failed") == 3
    assert update_fail_streak(3, "success") == 0
    assert update_fail_streak(3, "unchanged") == 0
