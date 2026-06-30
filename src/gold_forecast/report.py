"""Generate Markdown forecast reports."""

from __future__ import annotations

from pathlib import Path

from gold_forecast.missing_sources import MissingSource
from gold_forecast.scoring import ForecastResult
from gold_forecast.validator import ValidationIssue, ValidationResult

MODULE_LABELS = {
    "physical_demand": "实物需求",
    "inventory": "库存现货",
    "macro_liquidity": "美元利率/通胀",
    "financial_flow": "金融流动",
    "trend": "价格趋势",
}


def _pct(value: float) -> str:
    return f"{value:.0%}"


def _score_bar(score: float) -> str:
    if score >= 0.5:
        return "🟢 强多"
    if score >= 0.2:
        return "🟡 偏多"
    if score <= -0.5:
        return "🔴 强空"
    if score <= -0.2:
        return "🟠 偏空"
    return "⚪ 中性"


def _monthly_core_summary(forecast: ForecastResult) -> list[str]:
    """Summarise core indicators most relevant for a 1-month horizon."""
    lines: list[str] = ["", "## 1个月核心指标摘要", ""]
    mod = forecast.module_scores.get("trend")
    if mod:
        price_sig = next(
            (s for s in mod.signals if s.name == "return_20d"), None
        )
        ma_sig = next(
            (s for s in mod.signals if s.name == "price_vs_ma20"), None
        )
        if price_sig:
            lines.append(f"- **金价 20 日回报**：{price_sig.description}")
        if ma_sig:
            lines.append(f"- **金价 vs MA20**：{ma_sig.description}")

    mod = forecast.module_scores.get("macro_liquidity")
    if mod:
        for s in mod.signals:
            if "20d" in s.name:
                lines.append(f"- **{s.description}**")
        cpi_level = next(
            (s for s in mod.signals if s.name == "us_cpi_yoy_level"), None
        )
        cpi_mom = next(
            (s for s in mod.signals if s.name == "us_cpi_yoy_mom"), None
        )
        if cpi_level:
            lines.append(f"- **CPI 同比**：{cpi_level.description}")
        if cpi_mom:
            lines.append(f"- **CPI 环比变化**：{cpi_mom.description}")

    mod = forecast.module_scores.get("physical_demand")
    if mod:
        for s in mod.signals:
            if s.name in ("china_pmi_level", "china_pmi_mom"):
                lines.append(f"- **{s.description}**")

    mod = forecast.module_scores.get("inventory")
    if mod:
        for s in mod.signals:
            if "20d" in s.name or s.name in ("spot_premium", "term_structure"):
                lines.append(f"- **{s.description}**")

    return lines


def render_report(
    forecast: ForecastResult,
    validation: ValidationResult,
    missing_sources: list[MissingSource] | None = None,
) -> str:
    lines: list[str] = [
        "# 伦敦金走势判断报告",
        "",
        f"生成日期：{forecast.generated_at.strftime('%Y-%m-%d %H:%M')}",
        f"数据截止：{forecast.data_cutoff.isoformat() if forecast.data_cutoff else 'N/A'}",
        "",
        "## 结论",
        "",
        f"1 周判断：**{forecast.week_outlook}**",
        f"1 月判断：**{forecast.month_outlook}**",
        f"总分：**{forecast.total_score:+.3f}**（{forecast.direction}）",
        f"置信度：**{_pct(forecast.confidence)}**",
        f"数据健康度：**{_pct(forecast.data_health)}**",
        "",
    ]

    if forecast.horizon == "month":
        lines.extend(_monthly_core_summary(forecast))

    lines.extend([
        "",
        "## 模块分数",
        "",
        "| 模块 | 分数 | 状态 |",
        "|---|---:|---|",
    ])

    for key, label in MODULE_LABELS.items():
        mod = forecast.module_scores.get(key)
        if mod:
            gaps = f"（缺口: {len(mod.data_gaps)}）" if mod.data_gaps else ""
            lines.append(
                f"| {label} | {mod.score:+.3f} | {_score_bar(mod.score)}{gaps} |"
            )

    if forecast.cross_validation:
        lines.extend(["", "## A/B 交叉验证", ""])
        lines.append(f"结论：**{forecast.cross_validation.agreement}**。{forecast.cross_validation.note}")
        lines.extend(["", "| 组别 | 模块 | 分数 | 方向 |", "|---|---|---:|---|"])
        for group in forecast.cross_validation.groups:
            modules = "、".join(MODULE_LABELS.get(m, m) for m in group.modules)
            lines.append(
                f"| {group.label} | {modules} | {group.score:+.3f} | {group.direction} |"
            )

    lines.extend(["", "## 主要支撑", ""])
    for i, factor in enumerate(forecast.supporting_factors, 1):
        lines.append(f"{i}. {factor}")
    if not forecast.supporting_factors:
        lines.append("1. （暂无显著支撑因子）")

    lines.extend(["", "## 主要压制", ""])
    for i, factor in enumerate(forecast.suppressing_factors, 1):
        lines.append(f"{i}. {factor}")
    if not forecast.suppressing_factors:
        lines.append("1. （暂无显著压制因子）")

    lines.extend(["", "## 风险提示", ""])
    for i, risk in enumerate(forecast.risks, 1):
        lines.append(f"{i}. {risk}")

    lines.extend(["", "## 判断失效条件", ""])
    for i, cond in enumerate(forecast.invalidation_conditions, 1):
        lines.append(f"{i}. {cond}")

    lines.extend(["", "## 数据异常", ""])
    anomalies = validation.anomalies
    if anomalies:
        for i, issue in enumerate(anomalies[:10], 1):
            lines.append(
                f"{i}. [{issue.severity}] {issue.row.indicator} "
                f"({issue.row.date}): {issue.reason}"
            )
    else:
        lines.append("1. 无异常数据")

    lines.extend(["", "## 缺失数据源", ""])
    if missing_sources:
        lines.extend(
            [
                "| 指标 | 预期来源 | 状态 | 说明 |",
                "|---|---|---|---|",
            ]
        )
        for item in missing_sources:
            detail = item.detail or "—"
            lines.append(
                f"| {item.indicator} | {item.expected_source or '—'} "
                f"| {item.reason_label} | {detail} |"
            )
    else:
        lines.append("1. 所有已配置自动数据源均已入库")

    lines.extend(["", "## 模块信号明细", ""])
    for key, label in MODULE_LABELS.items():
        mod = forecast.module_scores.get(key)
        if not mod or not mod.signals:
            continue
        lines.append(f"### {label}")
        lines.append("")
        for sig in mod.signals:
            sign = "+" if sig.score > 0 else ""
            lines.append(f"- [{sign}{sig.score:.0f}] {sig.description}")
        if mod.data_gaps:
            lines.append(f"- ⚠ 数据缺口: {', '.join(mod.data_gaps)}")
        lines.append("")

    lines.append("---")
    lines.append("*本报告由 gold-forecast MVP 生成，仅供研究参考，不构成投资建议。*")
    return "\n".join(lines)


def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
