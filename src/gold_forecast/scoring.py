"""Total score, direction, confidence, and data health."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from gold_forecast.data_loader import DataRow
from gold_forecast.indicators import ModuleScore, SignalDetail
from gold_forecast.validator import ValidationResult


@dataclass
class ForecastResult:
    total_score: float
    direction: str
    week_outlook: str
    month_outlook: str
    confidence: float
    data_health: float
    module_scores: dict[str, ModuleScore]
    supporting_factors: list[str] = field(default_factory=list)
    suppressing_factors: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    data_cutoff: date | None = None
    generated_at: datetime = field(default_factory=datetime.now)
    cross_validation: "CrossValidationResult | None" = None
    horizon: str | None = None


@dataclass
class CrossValidationGroup:
    name: str
    label: str
    score: float
    direction: str
    modules: list[str]


@dataclass
class CrossValidationResult:
    groups: list[CrossValidationGroup]
    agreement: str
    note: str


def load_weights(config_dir: Path) -> dict[str, Any]:
    with (config_dir / "weights.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _direction_label(score: float, thresholds: dict[str, float]) -> str:
    if score >= thresholds["strong_bullish"]:
        return "看多"
    if score >= thresholds["bullish"]:
        return "偏多"
    if score <= thresholds["strong_bearish"]:
        return "看空"
    if score <= thresholds["bearish"]:
        return "偏空"
    return "中性"


def _outlook_from_direction(direction: str, horizon: str) -> str:
    if horizon == "month":
        # Monthly data is less noisy; keep strong directional labels.
        return direction
    mapping = {
        "看多": "偏多",
        "偏多": "偏多",
        "中性": "中性",
        "偏空": "偏空",
        "看空": "偏空",
    }
    return mapping.get(direction, "中性")


def compute_data_health(
    confirmed: list[DataRow],
    validation: ValidationResult,
    config_dir: Path,
) -> float:
    """Compute data_quality component (0-1)."""
    with (config_dir / "validation_rules.yaml").open(encoding="utf-8") as handle:
        rules = yaml.safe_load(handle)
    conf_map = rules.get("source_confidence_map", {"A": 1.0, "B": 0.8, "C": 0.6, "D": 0.4})

    if not confirmed:
        return 0.0

    with (config_dir / "indicators.yaml").open(encoding="utf-8") as handle:
        indicators_cfg = yaml.safe_load(handle)
    expected = set()
    for mod in indicators_cfg.get("modules", {}).values():
        expected.update(mod.get("indicators", []))
    with (config_dir / "sources.yaml").open(encoding="utf-8") as handle:
        sources_cfg = yaml.safe_load(handle)
    unwired = set(sources_cfg.get("unwired", {}).keys())
    unwired |= set(sources_cfg.get("optional", []))
    expected -= unwired

    latest_by_indicator: dict[str, DataRow] = {}
    for row in confirmed:
        if row.indicator not in expected:
            continue
        current = latest_by_indicator.get(row.indicator)
        if current is None or row.date > current.date:
            latest_by_indicator[row.indicator] = row

    source_scores = [conf_map.get(r.confidence, 0.5) for r in latest_by_indicator.values()]
    source_score = sum(source_scores) / len(source_scores) if source_scores else 0.5

    today = date.today()
    freshness_scores = []
    for row in latest_by_indicator.values():
        age_days = (today - row.date).days
        if row.frequency == "daily":
            freshness_scores.append(1.0 if age_days <= 5 else max(0.3, 1.0 - age_days / 30))
        else:
            freshness_scores.append(1.0 if age_days <= 60 else max(0.3, 1.0 - age_days / 90))
    freshness_score = sum(freshness_scores) / len(freshness_scores) if freshness_scores else 0.5

    total_issues = len(validation.rejected) + len(validation.pending)
    total_rows = len(confirmed) + total_issues
    cross_check_score = 1.0 if total_issues == 0 else max(0.4, 1.0 - total_issues / max(total_rows, 1))

    present = {r.indicator for r in confirmed}
    completeness_score = len(present & expected) / len(expected) if expected else 0.5

    w = load_weights(config_dir)["confidence"]["data_quality_weights"]
    return (
        w["source"] * source_score
        + w["freshness"] * freshness_score
        + w["cross_check"] * cross_check_score
        + w["completeness"] * completeness_score
    )


def compute_factor_consistency(
    module_scores: dict[str, ModuleScore],
    active_threshold: float,
) -> float:
    positive = sum(1 for m in module_scores.values() if m.score > active_threshold)
    negative = sum(1 for m in module_scores.values() if m.score < -active_threshold)
    active = positive + negative
    if active == 0:
        return 0.5
    return abs(positive - negative) / active


def _direction_sign(score: float, thresholds: dict[str, float]) -> int:
    if score >= thresholds["bullish"]:
        return 1
    if score <= thresholds["bearish"]:
        return -1
    return 0


def compute_cross_validation(
    module_scores: dict[str, ModuleScore],
    module_weights: dict[str, float],
    thresholds: dict[str, float],
    cross_cfg: dict[str, Any] | None,
) -> CrossValidationResult | None:
    if not cross_cfg:
        return None

    groups = []
    for name, cfg in cross_cfg.get("groups", {}).items():
        modules = cfg.get("modules", [])
        weighted = 0.0
        weight_sum = 0.0
        present = []
        for module in modules:
            score = module_scores.get(module)
            weight = module_weights.get(module, 0.0)
            if score is None or weight == 0:
                continue
            weighted += weight * score.score
            weight_sum += abs(weight)
            present.append(module)
        group_score = weighted / weight_sum if weight_sum else 0.0
        groups.append(
            CrossValidationGroup(
                name=name,
                label=cfg.get("label", name),
                score=group_score,
                direction=_direction_label(group_score, thresholds),
                modules=present,
            )
        )

    signs = [_direction_sign(group.score, thresholds) for group in groups]
    active_signs = [sign for sign in signs if sign != 0]
    if len(groups) < 2:
        agreement = "无法验证"
        note = "A/B 分组不足"
    elif not active_signs:
        agreement = "均为中性"
        note = "两组都没有给出明确方向"
    elif len(set(active_signs)) == 1 and len(active_signs) == len(groups):
        agreement = "同向确认"
        note = "A/B 两组给出一致方向"
    elif len(set(active_signs)) == 1:
        agreement = "弱确认"
        note = "一组给出方向，另一组偏中性"
    else:
        agreement = "相互背离"
        note = "A/B 两组方向冲突，方向置信度应下调"

    return CrossValidationResult(groups, agreement, note)


def _top_signals(module_scores: dict[str, ModuleScore], n: int = 3) -> tuple[list[str], list[str]]:
    bullish: list[tuple[float, str]] = []
    bearish: list[tuple[float, str]] = []
    for mod in module_scores.values():
        for sig in mod.signals:
            if sig.score > 0:
                bullish.append((sig.score, f"[{mod.module}] {sig.description}"))
            elif sig.score < 0:
                bearish.append((abs(sig.score), f"[{mod.module}] {sig.description}"))
    bullish.sort(reverse=True)
    bearish.sort(reverse=True)
    return [t[1] for t in bullish[:n]], [t[1] for t in bearish[:n]]


def _default_risks(module_scores: dict[str, ModuleScore], data_health: float) -> list[str]:
    risks = []
    if data_health < 0.7:
        risks.append("数据健康度偏低，部分指标缺失或待复核")
    split = sum(1 for m in module_scores.values() if abs(m.score) > 0.2)
    if split >= 4:
        both_sides = any(m.score > 0.2 for m in module_scores.values()) and any(
            m.score < -0.2 for m in module_scores.values()
        )
        if both_sides:
            risks.append("多空模块严重分裂，方向判断不确定性较高")
    for mod in module_scores.values():
        if mod.data_gaps:
            risks.append(f"{mod.module} 存在数据缺口: {', '.join(mod.data_gaps[:2])}")
    if not risks:
        risks.append("宏观数据发布窗口可能引发短期波动")
        risks.append("地缘政治与避险资金流动未完全量化入模")
    return risks[:3]


def _invalidation_conditions(
    module_scores: dict[str, ModuleScore], direction: str
) -> list[str]:
    conditions = []
    inv = module_scores.get("inventory")
    macro = module_scores.get("macro_liquidity")
    physical = module_scores.get("physical_demand")

    if direction in ("偏多", "看多"):
        conditions.append("全球黄金显性库存连续两周大幅累库（>5%）")
        conditions.append("美元指数突破近期高点且实际利率持续上行")
        conditions.append("黄金 ETF 连续大幅净流出且投机净多回落")
    elif direction in ("偏空", "看空"):
        conditions.append("全球库存降至三年低位且现货维持升水")
        conditions.append("央行净购金与 ETF 流入同步走强")
        conditions.append("美元与实际利率同步下行")
    else:
        conditions.append("任一核心模块分数突破 ±0.5 将触发方向调整")
        conditions.append("库存或宏观流动性出现单边趋势性变化")
        conditions.append("实物需求或金融流动出现方向性拐点")

    if inv and inv.score > 0.3:
        conditions.append("现货贴水扩大且期限结构转为 contango")
    if macro and macro.score < -0.3:
        conditions.append("DXY 与实际利率同步走强超过 4 周")
    if physical and physical.score < -0.3:
        conditions.append("中国 PMI 跌破 50 且首饰消费同比走弱")

    return conditions[:3]


def _module_weights_for_horizon(
    weights_cfg: dict[str, Any], horizon: str | None
) -> dict[str, float]:
    """Return module weights, optionally overridden for a specific horizon."""
    default_weights = weights_cfg["modules"]
    if not horizon:
        return default_weights
    horizon_cfg = weights_cfg.get("horizon_weights", {}).get(horizon, {})
    return horizon_cfg.get("modules", default_weights)


def compute_forecast(
    module_scores: dict[str, ModuleScore],
    validation: ValidationResult,
    confirmed: list[DataRow],
    config_dir: Path,
    horizon: str | None = None,
) -> ForecastResult:
    weights_cfg = load_weights(config_dir)
    module_weights = _module_weights_for_horizon(weights_cfg, horizon)
    thresholds = weights_cfg["direction_thresholds"]
    active_threshold = weights_cfg.get("module_active_threshold", 0.20)

    total = sum(
        module_weights.get(name, 0) * ms.score
        for name, ms in module_scores.items()
    )

    direction = _direction_label(total, thresholds)
    week_outlook = _outlook_from_direction(direction, "week")
    month_outlook = _outlook_from_direction(direction, "month")

    data_health = compute_data_health(confirmed, validation, config_dir)
    factor_consistency = compute_factor_consistency(module_scores, active_threshold)
    confidence = min(1.0, abs(total) * data_health * max(factor_consistency, 0.3))
    cross_validation = compute_cross_validation(
        module_scores,
        module_weights,
        thresholds,
        weights_cfg.get("cross_validation"),
    )

    supporting, suppressing = _top_signals(module_scores)
    risks = _default_risks(module_scores, data_health)
    invalidation = _invalidation_conditions(module_scores, direction)

    cutoff = max((r.date for r in confirmed), default=None)

    return ForecastResult(
        total_score=total,
        direction=direction,
        week_outlook=week_outlook,
        month_outlook=month_outlook,
        confidence=confidence,
        data_health=data_health,
        module_scores=module_scores,
        supporting_factors=supporting,
        suppressing_factors=suppressing,
        risks=risks,
        invalidation_conditions=invalidation,
        data_cutoff=cutoff,
        cross_validation=cross_validation,
        horizon=horizon,
    )
