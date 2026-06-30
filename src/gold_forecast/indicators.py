"""Compute module scores from validated indicator data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yaml

from gold_forecast.data_loader import DataRow, group_by_indicator, load_supply_events


@dataclass
class SignalDetail:
    name: str
    score: float
    description: str


@dataclass
class ModuleScore:
    module: str
    score: float
    signals: list[SignalDetail] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)


def _latest_numeric(series: list[DataRow]) -> tuple[date | None, float | None]:
    nums = [(r.date, r.numeric_value) for r in series if r.numeric_value is not None]
    if not nums:
        return None, None
    d, v = nums[-1]
    return d, v


def _latest_preferred_numeric(
    series: list[DataRow], blocked_source_terms: tuple[str, ...]
) -> tuple[date | None, float | None, DataRow | None]:
    nums = [r for r in series if r.numeric_value is not None]
    if not nums:
        return None, None, None

    preferred = [
        r
        for r in nums
        if not any(term in r.source for term in blocked_source_terms)
    ]
    row = preferred[-1] if preferred else nums[-1]
    return row.date, row.numeric_value, row


def _value_n_days_ago(series: list[DataRow], n: int) -> float | None:
    nums = [(r.date, r.numeric_value) for r in series if r.numeric_value is not None]
    if len(nums) <= n:
        return nums[0][1] if nums else None
    return nums[-1 - n][1]


def _ma(series: list[DataRow], window: int) -> float | None:
    nums = [r.numeric_value for r in series if r.numeric_value is not None]
    if len(nums) < window:
        return None
    return sum(nums[-window:]) / window


def _pct_change(series: list[DataRow], days: int) -> float | None:
    nums = [r.numeric_value for r in series if r.numeric_value is not None]
    if len(nums) <= days:
        return None
    old, new = nums[-1 - days], nums[-1]
    if old == 0:
        return None
    return (new - old) / old


def _abs_change(series: list[DataRow], periods: int) -> float | None:
    nums = [r.numeric_value for r in series if r.numeric_value is not None]
    if len(nums) <= periods:
        return None
    old, new = nums[-1 - periods], nums[-1]
    return new - old


def _avg_signals(signals: list[SignalDetail]) -> float:
    if not signals:
        return 0.0
    return sum(s.score for s in signals) / len(signals)


def _value_on_or_before(observations: list[tuple[date, float]], target: date) -> float | None:
    last: float | None = None
    for d, v in observations:
        if d > target:
            break
        last = v
    return last


def _global_inventory_series(
    grouped: dict[str, list[DataRow]],
    inv_keys: list[str],
) -> list[tuple[date, float]]:
    """Sum exchange inventories by date; forward-fill each venue to align stale prints."""
    per_exchange: dict[str, list[tuple[date, float]]] = {}
    all_dates: set[date] = set()
    for key in inv_keys:
        series = grouped.get(key, [])
        obs = sorted(
            (r.date, r.numeric_value) for r in series if r.numeric_value is not None
        )
        if obs:
            per_exchange[key] = obs
            all_dates.update(d for d, _ in obs)

    if not per_exchange:
        return []

    totals: list[tuple[date, float]] = []
    for d in sorted(all_dates):
        total = 0.0
        contributors = 0
        for obs in per_exchange.values():
            v = _value_on_or_before(obs, d)
            if v is not None:
                total += v
                contributors += 1
        if contributors:
            totals.append((d, total))
    return totals


def _percentile_rank(series: list[DataRow], lookback: int = 756) -> float | None:
    """Approximate percentile rank over lookback observations (~3 years daily)."""
    nums = [r.numeric_value for r in series if r.numeric_value is not None]
    if not nums:
        return None
    window = nums[-lookback:] if len(nums) >= lookback else nums
    current = window[-1]
    below = sum(1 for v in window if v < current)
    return below / len(window)


def score_trend(grouped: dict[str, list[DataRow]]) -> ModuleScore:
    series = grouped.get("lme_gold_price", [])
    signals: list[SignalDetail] = []
    gaps: list[str] = []

    if not series:
        return ModuleScore("trend", 0.0, data_gaps=["lme_gold_price missing"])

    _, price = _latest_numeric(series)
    if price is None:
        return ModuleScore("trend", 0.0, data_gaps=["lme_gold_price not numeric"])

    for window, label in [(20, "20d"), (60, "60d"), (120, "120d")]:
        ma = _ma(series, window)
        if ma is None:
            gaps.append(f"MA{window} insufficient history")
            continue
        score = 1.0 if price > ma else -1.0
        signals.append(
            SignalDetail(
                f"price_vs_ma{window}",
                score,
                f"Price {price:.1f} {'>' if score > 0 else '<='} MA{window} ({ma:.1f})",
            )
        )

    for days, label in [(20, "20d"), (60, "60d")]:
        ret = _pct_change(series, days)
        if ret is None:
            gaps.append(f"{label} return insufficient history")
            continue
        score = 1.0 if ret > 0 else -1.0
        signals.append(
            SignalDetail(
                f"return_{label}",
                score,
                f"{label} return {ret:+.2%}",
            )
        )

    return ModuleScore("trend", _avg_signals(signals), signals, gaps)


def score_inventory(grouped: dict[str, list[DataRow]]) -> ModuleScore:
    signals: list[SignalDetail] = []
    gaps: list[str] = []

    inv_keys = ["lme_inventory", "shfe_inventory", "comex_inventory"]
    gaps: list[str] = []
    for key in inv_keys:
        if not grouped.get(key):
            gaps.append(f"{key} missing")

    global_series = _global_inventory_series(grouped, inv_keys)
    if global_series:
        global_rows = [
            DataRow(
                d,
                "global_inventory",
                v,
                "ton",
                "",
                "",
                __import__("datetime").datetime.min,
                "daily",
                "B",
            )
            for d, v in global_series
        ]

        for days, label in [(20, "20d"), (60, "60d")]:
            chg = _pct_change(global_rows, days)
            if chg is None:
                gaps.append(f"global inventory {label} change unavailable")
                continue
            score = -1.0 if chg > 0 else 1.0  # falling inventory = bullish
            signals.append(
                SignalDetail(
                    f"global_inv_chg_{label}",
                    score,
                    f"Global inventory {label} change {chg:+.2%}",
                )
            )

        pct = _percentile_rank(global_rows)
        if pct is not None:
            if pct <= 0.25:
                signals.append(
                    SignalDetail(
                        "inv_low_percentile",
                        1.0,
                        f"Global inventory at {pct:.0%} 3y percentile (low)",
                    )
                )
            elif pct >= 0.75:
                signals.append(
                    SignalDetail(
                        "inv_high_percentile",
                        -1.0,
                        f"Global inventory at {pct:.0%} 3y percentile (high)",
                    )
                )

    premium_series = grouped.get("spot_premium", [])
    if premium_series:
        _, prem = _latest_numeric(premium_series)
        if prem is not None:
            score = 1.0 if prem > 0 else -1.0
            signals.append(
                SignalDetail(
                    "spot_premium",
                    score,
                    f"Spot premium {prem:+.1f} ({'contango/premium' if prem > 0 else 'discount'})",
                )
            )

    term_series = grouped.get("term_structure", [])
    if term_series:
        label = str(term_series[-1].value).lower()
        if label == "backwardation":
            signals.append(
                SignalDetail("term_structure", 1.0, "Term structure: backwardation")
            )
        elif label == "contango":
            signals.append(
                SignalDetail("term_structure", -1.0, "Term structure: contango")
            )

    if not signals:
        return ModuleScore("inventory", 0.0, data_gaps=gaps or ["no inventory data"])

    return ModuleScore("inventory", _avg_signals(signals), signals, gaps)


def score_physical_demand(grouped: dict[str, list[DataRow]]) -> ModuleScore:
    signals: list[SignalDetail] = []
    gaps: list[str] = []

    pmi_series = grouped.get("china_pmi", [])
    if pmi_series:
        _, pmi = _latest_numeric(pmi_series)
        prev = _value_n_days_ago(pmi_series, 1)
        if pmi is not None:
            signals.append(
                SignalDetail(
                    "china_pmi_level",
                    1.0 if pmi > 50 else -1.0,
                    f"China PMI {pmi:.1f}",
                )
            )
        if pmi is not None and prev is not None:
            signals.append(
                SignalDetail(
                    "china_pmi_mom",
                    1.0 if pmi > prev else -1.0,
                    f"China PMI mom {pmi - prev:+.1f}",
                )
            )
    else:
        gaps.append("china_pmi missing")

    no_series = grouped.get("china_new_orders_pmi", [])
    if no_series:
        _, no_pmi = _latest_numeric(no_series)
        if no_pmi is not None:
            signals.append(
                SignalDetail(
                    "new_orders_pmi",
                    1.0 if no_pmi > 50 else -1.0,
                    f"New orders PMI {no_pmi:.1f}",
                )
            )
    else:
        gaps.append("china_new_orders_pmi missing")

    sf_series = grouped.get("social_financing", [])
    m1_series = grouped.get("m1", [])
    sf_improved = False
    if sf_series:
        _, sf = _latest_numeric(sf_series)
        prev_sf = _value_n_days_ago(sf_series, 1)
        if sf is not None and prev_sf is not None:
            sf_improved = sf > prev_sf
    if m1_series:
        _, m1 = _latest_numeric(m1_series)
        prev_m1 = _value_n_days_ago(m1_series, 1)
        if m1 is not None and prev_m1 is not None and m1 > prev_m1:
            sf_improved = True
    if sf_series or m1_series:
        signals.append(
            SignalDetail(
                "credit_impulse",
                1.0 if sf_improved else -1.0,
                "Social financing / M1 improving" if sf_improved else "Credit/M1 not improving",
            )
        )
    else:
        gaps.append("social_financing / m1 missing")

    cb_series = grouped.get("central_bank_gold_net_buy", [])
    if cb_series:
        _, cb_buy = _latest_numeric(cb_series)
        if cb_buy is not None:
            signals.append(
                SignalDetail(
                    "central_bank_buying",
                    1.0 if cb_buy > 0 else -1.0,
                    f"Central bank net gold buying {cb_buy:+.1f} ton",
                )
            )
    else:
        gaps.append("central_bank_gold_net_buy missing")

    jewelry_series = grouped.get("gold_jewelry_demand_yoy", [])
    if jewelry_series:
        _, jewelry = _latest_numeric(jewelry_series)
        if jewelry is not None:
            signals.append(
                SignalDetail(
                    "jewelry_demand",
                    1.0 if jewelry > 0 else -1.0,
                    f"Gold jewelry demand YoY {jewelry:+.1f}%",
                )
            )
    else:
        gaps.append("gold_jewelry_demand_yoy missing")

    return ModuleScore(
        "physical_demand",
        _avg_signals(signals) if signals else 0.0,
        signals,
        gaps,
    )


def score_macro_liquidity(grouped: dict[str, list[DataRow]]) -> ModuleScore:
    signals: list[SignalDetail] = []
    gaps: list[str] = []

    for key, label in [("dxy", "DXY"), ("us_10y_real_rate", "US 10Y real rate")]:
        series = grouped.get(key, [])
        if not series:
            gaps.append(f"{key} missing")
            continue
        for days in (20, 60):
            chg = _pct_change(series, days)
            if chg is None:
                gaps.append(f"{key} {days}d change unavailable")
                continue
            # Falling DXY / real rates = bullish for gold
            score = 1.0 if chg < 0 else -1.0
            signals.append(
                SignalDetail(
                    f"{key}_{days}d",
                    score,
                    f"{label} {days}d change {chg:+.2%}",
                )
            )

    cpi_series = grouped.get("us_cpi_yoy", [])
    if cpi_series:
        _, cpi = _latest_numeric(cpi_series)
        prev_cpi = _value_n_days_ago(cpi_series, 1)
        if cpi is not None:
            if cpi >= 3.0:
                level_score = 1.0
            elif cpi <= 1.5:
                level_score = -1.0
            else:
                level_score = 0.0
            signals.append(
                SignalDetail(
                    "us_cpi_yoy_level",
                    level_score,
                    f"US CPI YoY {cpi:.2f}%",
                )
            )
        if cpi is not None and prev_cpi is not None:
            delta = cpi - prev_cpi
            if abs(delta) < 0.05:
                momentum_score = 0.0
            else:
                momentum_score = 1.0 if delta > 0 else -1.0
            signals.append(
                SignalDetail(
                    "us_cpi_yoy_mom",
                    momentum_score,
                    f"US CPI YoY mom {delta:+.2f}pp",
                )
            )
    else:
        gaps.append("us_cpi_yoy missing")

    return ModuleScore(
        "macro_liquidity",
        _avg_signals(signals) if signals else 0.0,
        signals,
        gaps,
    )


def score_financial_flow(
    grouped: dict[str, list[DataRow]],
    events_path: str | None = None,
) -> ModuleScore:
    signals: list[SignalDetail] = []
    gaps: list[str] = []

    etf_series = grouped.get("gold_etf_holdings_chg", [])
    if etf_series:
        delta = _abs_change(etf_series, 1)
        if delta is not None:
            score = 1.0 if delta > 0 else -1.0
            signals.append(
                SignalDetail(
                    "etf_holdings_chg",
                    score,
                    f"Gold ETF holdings change {delta:+.1f} ton",
                )
            )
    else:
        gaps.append("gold_etf_holdings_chg missing")

    spec_series = grouped.get("spec_net_long_gold", [])
    if spec_series:
        delta = _abs_change(spec_series, 1)
        if delta is not None:
            score = 1.0 if delta > 0 else -1.0
            signals.append(
                SignalDetail(
                    "spec_net_long_chg",
                    score,
                    f"Spec net long change {delta:+.0f} contracts",
                )
            )
    else:
        gaps.append("spec_net_long_gold missing")

    if events_path:
        from pathlib import Path

        for event in load_supply_events(Path(events_path)):
            conf_mult = {"A": 1.0, "B": 0.8, "C": 0.6}.get(event["confidence"], 0.5)
            adj_score = max(-1.0, min(1.0, event["score"] * conf_mult))
            signals.append(
                SignalDetail(
                    event["event"],
                    adj_score,
                    f"{event['note']} (source: {event['source']})",
                )
            )

    return ModuleScore(
        "financial_flow",
        _avg_signals(signals) if signals else 0.0,
        signals,
        gaps,
    )


def compute_all_module_scores(
    confirmed_rows: list[DataRow],
    config_dir: str | None = None,
) -> dict[str, ModuleScore]:
    """Compute scores for all six modules."""
    grouped = group_by_indicator(confirmed_rows)
    events_path = None
    if config_dir:
        from pathlib import Path

        cfg_path = Path(config_dir)
        with (cfg_path / "indicators.yaml").open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        raw_events = cfg.get("modules", {}).get("financial_flow", {}).get("events_file")
        if raw_events:
            events_path = str(cfg_path.parent / raw_events)

    return {
        "trend": score_trend(grouped),
        "inventory": score_inventory(grouped),
        "physical_demand": score_physical_demand(grouped),
        "macro_liquidity": score_macro_liquidity(grouped),
        "financial_flow": score_financial_flow(grouped, events_path),
    }
