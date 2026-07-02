"""Tests for Warsh policy factor scoring."""

from datetime import date
from pathlib import Path

from gold_forecast.indicators import score_warsh_policy
from gold_forecast.warsh_factor import compute_warsh_signals, load_warsh_config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_warsh_config_loads():
    cfg = load_warsh_config(CONFIG_DIR)
    speech_date = cfg.get("meta", {}).get("speech_date")
    assert str(speech_date) == "2026-07-01"
    assert len(cfg.get("dimensions", {})) >= 5


def test_warsh_signals_active_on_speech_date():
    signals = compute_warsh_signals(CONFIG_DIR, as_of=date(2026, 7, 2))
    names = [s.name for s in signals]
    assert "warsh_inflation_hawkishness" in names
    assert "warsh_composite" in names
    assert len(signals) == 8


def test_warsh_composite_is_weighted_average():
    signals = compute_warsh_signals(CONFIG_DIR, as_of=date(2026, 7, 2))
    composite = next(s for s in signals if s.name == "warsh_composite")
    assert -1.0 <= composite.score <= 1.0
    assert composite.score < 0


def test_warsh_inactive_after_valid_until():
    signals = compute_warsh_signals(CONFIG_DIR, as_of=date(2026, 8, 15))
    assert signals == []


def test_score_warsh_policy_module():
    result = score_warsh_policy(CONFIG_DIR)
    assert result.module == "warsh_policy"
    assert result.score < 0
    assert result.signals
    assert all(not s.name.endswith("composite") for s in result.signals)
