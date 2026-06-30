"""Tests for missing source tracking."""

from pathlib import Path

from gold_forecast.missing_sources import compute_missing_sources, parse_fetch_errors


def _write_sources(config_dir: Path, text: str) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "sources.yaml").write_text(text, encoding="utf-8")


def test_parse_fetch_errors_maps_indicator():
    errors = [
        "eastmoney:lme_inventory: column missing",
        "cme:comex_inventory: 403 Forbidden",
    ]
    parsed = parse_fetch_errors(errors)
    assert parsed["lme_inventory"] == "column missing"
    assert parsed["comex_inventory"] == "403 Forbidden"


def test_compute_missing_sources_marks_unwired_and_fetch_failures(tmp_path):
    _write_sources(
        tmp_path,
        """
lookback_days: 30
sources:
  yahoo:
    enabled: true
    indicators:
      dxy:
        source: Yahoo Finance
        source_url: https://finance.yahoo.com/
  eastmoney:
    enabled: true
    indicators:
      lme_inventory:
        source: 东方财富-LME
        source_url: https://www.lme.com/
unwired:
  gold_etf_holdings_chg:
    expected_source: WGC
    source_url: https://www.gold.org/
    note: no fetcher yet
""",
    )

    missing = compute_missing_sources(
        tmp_path,
        present={"dxy"},
        fetch_errors=["eastmoney:lme_inventory: column missing"],
    )

    by_name = {item.indicator: item for item in missing}
    assert by_name["lme_inventory"].reason == "fetch_failed"
    assert "column missing" in by_name["lme_inventory"].detail
    assert by_name["gold_etf_holdings_chg"].reason == "no_automated_fetcher"
    assert by_name["gold_etf_holdings_chg"].expected_source == "WGC"
