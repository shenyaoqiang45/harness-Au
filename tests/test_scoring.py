"""Tests for scoring and direction labels."""

from datetime import date, datetime, timedelta
from pathlib import Path

from gold_forecast.data_loader import DataRow
from gold_forecast.indicators import ModuleScore, SignalDetail, compute_all_module_scores, score_macro_liquidity
from gold_forecast.scoring import (
    _direction_label,
    compute_cross_validation,
    compute_data_health,
    compute_forecast,
)
from gold_forecast.validator import ValidationResult

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_direction_thresholds():
    thresholds = {
        "strong_bullish": 0.50,
        "bullish": 0.20,
        "bearish": -0.20,
        "strong_bearish": -0.50,
    }
    assert _direction_label(0.55, thresholds) == "看多"
    assert _direction_label(0.35, thresholds) == "偏多"
    assert _direction_label(0.0, thresholds) == "中性"
    assert _direction_label(-0.35, thresholds) == "偏空"
    assert _direction_label(-0.55, thresholds) == "看空"


def test_total_score_weighted():
    module_scores = {
        "physical_demand": ModuleScore("physical_demand", 1.0),
        "inventory": ModuleScore("inventory", 1.0),
        "macro_liquidity": ModuleScore("macro_liquidity", -1.0),
        "financial_flow": ModuleScore("financial_flow", 0.0),
        "trend": ModuleScore("trend", 1.0),
    }
    row = DataRow(
        date=date(2026, 6, 29),
        indicator="lme_gold_price",
        value=2350.0,
        unit="USD/oz",
        source="comex",
        source_url="https://example.com",
        updated_at=datetime(2026, 6, 29),
        frequency="daily",
        confidence="A",
        status="confirmed",
    )
    forecast = compute_forecast(
        module_scores,
        ValidationResult(confirmed=[row]),
        [row],
        CONFIG_DIR,
        horizon="month",
    )
    # Monthly weights: macro 0.40, warsh 0.05, trend 0.25, fin 0.15, inv 0.10, phys 0.05
    # 0.05*1 + 0.10*1 + 0.40*(-1) + 0.15*0 + 0.25*1 = 0.00
    assert abs(forecast.total_score - 0.00) < 0.001
    assert forecast.horizon == "month"
    assert forecast.month_outlook == forecast.direction


def test_total_score_weighted_aggregate():
    module_scores = {
        "physical_demand": ModuleScore("physical_demand", 1.0),
        "inventory": ModuleScore("inventory", 1.0),
        "macro_liquidity": ModuleScore("macro_liquidity", -1.0),
        "financial_flow": ModuleScore("financial_flow", 0.0),
        "trend": ModuleScore("trend", 1.0),
    }
    row = DataRow(
        date=date(2026, 6, 29),
        indicator="lme_gold_price",
        value=2350.0,
        unit="USD/oz",
        source="comex",
        source_url="https://example.com",
        updated_at=datetime(2026, 6, 29),
        frequency="daily",
        confidence="A",
        status="confirmed",
    )
    forecast = compute_forecast(
        module_scores,
        ValidationResult(confirmed=[row]),
        [row],
        CONFIG_DIR,
    )
    # 0.15*1 + 0.10*1 + 0.35*(-1) + 0.20*0 + 0.15*1 = 0.05
    assert abs(forecast.total_score - 0.05) < 0.001
    assert forecast.direction == "中性"
    assert forecast.cross_validation is not None


def test_cross_validation_detects_group_divergence():
    module_scores = {
        "physical_demand": ModuleScore("physical_demand", 1.0),
        "inventory": ModuleScore("inventory", 1.0),
        "macro_liquidity": ModuleScore("macro_liquidity", -1.0),
        "trend": ModuleScore("trend", -1.0),
    }
    module_weights = {
        "physical_demand": 0.15,
        "inventory": 0.20,
        "macro_liquidity": 0.30,
        "trend": 0.10,
    }
    thresholds = {
        "strong_bullish": 0.50,
        "bullish": 0.20,
        "bearish": -0.20,
        "strong_bearish": -0.50,
    }
    cross_cfg = {
        "groups": {
            "A": {"label": "A", "modules": ["physical_demand", "inventory"]},
            "B": {"label": "B", "modules": ["macro_liquidity", "trend"]},
        }
    }

    result = compute_cross_validation(
        module_scores, module_weights, thresholds, cross_cfg
    )

    assert result is not None
    assert result.agreement == "相互背离"
    assert [group.direction for group in result.groups] == ["看多", "看空"]


def test_forecast_downgrades_outlook_when_cross_validation_diverges():
    module_scores = {
        "physical_demand": ModuleScore("physical_demand", 1.0),
        "inventory": ModuleScore("inventory", 1.0),
        "financial_flow": ModuleScore("financial_flow", 1.0),
        "macro_liquidity": ModuleScore("macro_liquidity", -0.5),
        "trend": ModuleScore("trend", 0.0),
    }
    row = DataRow(
        date=date(2026, 6, 29),
        indicator="lme_gold_price",
        value=2350.0,
        unit="USD/oz",
        source="comex",
        source_url="https://example.com",
        updated_at=datetime(2026, 6, 29),
        frequency="daily",
        confidence="A",
        status="confirmed",
    )

    forecast = compute_forecast(
        module_scores,
        ValidationResult(confirmed=[row]),
        [row],
        CONFIG_DIR,
    )

    assert forecast.direction == "偏多"
    assert forecast.cross_validation is not None
    assert forecast.cross_validation.agreement == "相互背离"
    assert forecast.low_confidence is True
    assert forecast.week_outlook == "中性偏多（低置信）"
    assert forecast.month_outlook == "中性偏多（低置信）"
    assert "A/B 交叉验证方向背离" in forecast.confidence_note


def test_data_health_uses_latest_freshness_and_ignores_optional(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "validation_rules.yaml").write_text(
        "source_confidence_map:\n  A: 1.0\n  B: 0.8\n",
        encoding="utf-8",
    )
    (config_dir / "indicators.yaml").write_text(
        "modules:\n  inventory:\n    indicators:\n      - required_indicator\n      - optional_indicator\n",
        encoding="utf-8",
    )
    (config_dir / "sources.yaml").write_text(
        "optional:\n  - optional_indicator\n",
        encoding="utf-8",
    )
    (config_dir / "weights.yaml").write_text(
        "confidence:\n  data_quality_weights:\n    source: 0.0\n    freshness: 0.5\n    cross_check: 0.0\n    completeness: 0.5\n",
        encoding="utf-8",
    )

    today = date.today()
    rows = [
        DataRow(
            date=today - timedelta(days=120),
            indicator="required_indicator",
            value=1,
            unit="index",
            source="test",
            source_url="https://example.com",
            updated_at=datetime.combine(today, datetime.min.time()),
            frequency="daily",
            confidence="A",
            status="confirmed",
        ),
        DataRow(
            date=today,
            indicator="required_indicator",
            value=2,
            unit="index",
            source="test",
            source_url="https://example.com",
            updated_at=datetime.combine(today, datetime.min.time()),
            frequency="daily",
            confidence="A",
            status="confirmed",
        ),
    ]

    health = compute_data_health(rows, ValidationResult(confirmed=rows), config_dir)

    assert health == 1.0


def test_trend_score_from_price_series():
    rows = []
    price = 2200.0
    for i in range(130):
        d = date(2026, 2, 1)
        from datetime import timedelta

        day = d + timedelta(days=i)
        price += 1.5
        rows.append(
            DataRow(
                date=day,
                indicator="lme_gold_price",
                value=price,
                unit="USD/oz",
                source="comex",
                source_url="https://example.com",
                updated_at=datetime.combine(day, datetime.min.time()),
                frequency="daily",
                confidence="A",
                status="confirmed",
            )
        )
    scores = compute_all_module_scores(rows, str(CONFIG_DIR))
    assert scores["trend"].score > 0


def test_macro_liquidity_scores_us_cpi_yoy():
    rows = [
        DataRow(
            date=date(2026, 4, 1),
            indicator="us_cpi_yoy",
            value=2.8,
            unit="pct",
            source="FRED",
            source_url="https://example.com",
            updated_at=datetime(2026, 6, 29),
            frequency="monthly",
            confidence="A",
            status="confirmed",
        ),
        DataRow(
            date=date(2026, 5, 1),
            indicator="us_cpi_yoy",
            value=3.2,
            unit="pct",
            source="FRED",
            source_url="https://example.com",
            updated_at=datetime(2026, 6, 29),
            frequency="monthly",
            confidence="A",
            status="confirmed",
        ),
    ]

    score = score_macro_liquidity({"us_cpi_yoy": rows})

    assert score.score == 1.0
    assert [signal.name for signal in score.signals] == ["us_cpi_yoy_level", "us_cpi_yoy_mom"]


def test_physical_demand_credit_impulse():
    from gold_forecast.indicators import score_physical_demand

    def _row(d: date, indicator: str, value: float) -> DataRow:
        return DataRow(
            date=d,
            indicator=indicator,
            value=value,
            unit="CNY_bn",
            source="test",
            source_url="https://example.com",
            updated_at=datetime.combine(d, datetime.min.time()),
            frequency="monthly",
            confidence="A",
            status="confirmed",
        )

    rows = [
        _row(date(2026, 4, 1), "social_financing", 1000.0),
        _row(date(2026, 5, 1), "social_financing", 1200.0),
    ]
    result = score_physical_demand({"social_financing": rows})

    signal = next(s for s in result.signals if s.name == "credit_impulse")
    assert signal.score == 1.0
    assert "improving" in signal.description


def test_financial_flow_events_only():
    from gold_forecast.indicators import score_financial_flow

    result = score_financial_flow({})
    assert result.score == 0.0
    assert not result.signals
