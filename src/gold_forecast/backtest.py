"""Walk-forward backtest: score with data as of t, grade against future gold."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import yaml

from gold_forecast.data_loader import DataRow, group_by_indicator, load_csv
from gold_forecast.indicators import compute_all_module_scores
from gold_forecast.scoring import ForecastResult, compute_forecast, load_weights
from gold_forecast.validator import ValidationResult, validate_rows

GOLD_INDICATOR = "lme_gold_price"
HORIZON_BARS = {"week": 5, "month": 21}
WARMUP_BARS = 120
SCORE_RE = re.compile(r"总分[：:]\s*\*\*([+-]?\d+\.\d+)\*\*")
CUTOFF_RE = re.compile(r"数据截止[：:]\s*(\d{4}-\d{2}-\d{2})")
CONFIDENCE_RE = re.compile(r"置信度[：:]\s*\*\*(\d+)%\*\*")

MODULE_LABELS = {
    "physical_demand": "实物需求",
    "inventory": "库存现货",
    "macro_liquidity": "美元利率/通胀",
    "warsh_policy": "沃什因子",
    "financial_flow": "金融流动",
    "trend": "价格趋势",
}


@dataclass
class BacktestPoint:
    as_of: date
    score: float
    direction: str
    confidence: float
    low_confidence: bool
    ab_agreement: str
    price: float
    fwd_return: float
    module_scores: dict[str, float]
    pred_sign: int
    actual_sign: int
    hit: bool | None
    dxy_20d_sign: int = 0
    real_rate_20d_sign: int = 0


@dataclass
class BucketMetrics:
    label: str
    n: int
    n_directional: int
    hit_rate: float | None
    mean_fwd: float
    spearman: float | None


@dataclass
class SchemeMetrics:
    name: str
    hit_rate: float | None
    spearman: float | None
    mean_fwd_bull: float | None
    mean_fwd_bear: float | None
    n_directional: int


@dataclass
class HorizonResult:
    horizon: str
    bars: int
    n: int
    n_directional: int
    hit_rate: float | None
    spearman: float | None
    coverage: float
    always_long_hit: float | None
    momentum_hit: float | None
    mean_fwd: float
    mean_fwd_bull: float | None
    mean_fwd_bear: float | None
    by_direction: list[BucketMetrics]
    by_confidence: list[BucketMetrics]
    by_ab: list[BucketMetrics]
    module_spearman: dict[str, float | None]
    schemes: list[SchemeMetrics]
    reversal_rate: float | None
    reversal_with_hawkish_macro: float | None
    points: list[BacktestPoint] = field(default_factory=list)


@dataclass
class ReportReplayPoint:
    report_date: date
    cutoff: date
    score: float
    confidence: float | None
    path: str
    fwd_return: float | None
    hit: bool | None


@dataclass
class BacktestResult:
    generated_at: datetime
    input_path: str
    gold_start: date | None
    gold_end: date | None
    gold_days: int
    warmup_bars: int
    horizons: list[HorizonResult]
    report_replay: dict[str, list[ReportReplayPoint]]
    notes: list[str]


def load_publication_lags(config_dir: Path) -> dict[str, Any]:
    path = config_dir / "publication_lag.yaml"
    if not path.exists():
        return {"lags": {}, "default_monthly_lag": 40, "default_daily_lag": 0}
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def row_available_on(row: DataRow, lags_cfg: dict[str, Any]) -> date:
    lags = lags_cfg.get("lags") or {}
    if row.indicator in lags:
        lag = int(lags[row.indicator])
    elif row.frequency == "daily":
        lag = int(lags_cfg.get("default_daily_lag") or 0)
    else:
        lag = int(lags_cfg.get("default_monthly_lag") or 40)
    return row.date + timedelta(days=lag)


def rows_as_of(
    rows: Iterable[DataRow],
    as_of: date,
    lags_cfg: dict[str, Any] | None = None,
) -> list[DataRow]:
    if not lags_cfg:
        return [row for row in rows if row.date <= as_of]
    return [row for row in rows if row_available_on(row, lags_cfg) <= as_of]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return cov / math.sqrt(var_x * var_y)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    return _pearson(_ranks(xs), _ranks(ys))


def _sign_from_threshold(score: float, bullish: float, bearish: float) -> int:
    if score >= bullish:
        return 1
    if score <= bearish:
        return -1
    return 0


def _return_sign(ret: float) -> int:
    if ret > 0:
        return 1
    if ret < 0:
        return -1
    return 0


def _hit(pred: int, actual: int) -> bool | None:
    if pred == 0 or actual == 0:
        return None
    return pred == actual


def _mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return sum(xs) / len(xs)


def _hit_rate(hits: list[bool | None]) -> float | None:
    judged = [h for h in hits if h is not None]
    if not judged:
        return None
    return sum(1 for h in judged if h) / len(judged)


def _gold_series(rows: list[DataRow]) -> list[tuple[date, float]]:
    grouped = group_by_indicator(rows)
    series = grouped.get(GOLD_INDICATOR, [])
    out: list[tuple[date, float]] = []
    for row in series:
        value = row.numeric_value
        if value is None:
            continue
        out.append((row.date, value))
    return out


def _signal_sign(forecast: ForecastResult, name: str) -> int:
    mod = forecast.module_scores.get("macro_liquidity")
    if not mod:
        return 0
    sig = next((s for s in mod.signals if s.name == name), None)
    if sig is None:
        return 0
    if sig.score > 0:
        return 1
    if sig.score < 0:
        return -1
    return 0


def _momentum_sign(gold: list[tuple[date, float]], index: int, lookback: int = 20) -> int:
    if index < lookback:
        return 0
    old = gold[index - lookback][1]
    new = gold[index][1]
    if old == 0:
        return 0
    return _return_sign((new - old) / old)


def _bucket_metrics(label: str, points: list[BacktestPoint]) -> BucketMetrics:
    hits = [p.hit for p in points]
    judged = [h for h in hits if h is not None]
    return BucketMetrics(
        label=label,
        n=len(points),
        n_directional=len(judged),
        hit_rate=_hit_rate(hits),
        mean_fwd=_mean([p.fwd_return for p in points]) or 0.0,
        spearman=spearman_corr(
            [p.score for p in points], [p.fwd_return for p in points]
        ),
    )


def _scheme_metrics(
    name: str,
    points: list[BacktestPoint],
    totals: list[float],
    bullish: float,
    bearish: float,
) -> SchemeMetrics:
    hits: list[bool | None] = []
    bull_fwd: list[float] = []
    bear_fwd: list[float] = []
    for point, total in zip(points, totals):
        pred = _sign_from_threshold(total, bullish, bearish)
        hit = _hit(pred, point.actual_sign)
        hits.append(hit)
        if pred == 1:
            bull_fwd.append(point.fwd_return)
        elif pred == -1:
            bear_fwd.append(point.fwd_return)
    return SchemeMetrics(
        name=name,
        hit_rate=_hit_rate(hits),
        spearman=spearman_corr(totals, [p.fwd_return for p in points]),
        mean_fwd_bull=_mean(bull_fwd),
        mean_fwd_bear=_mean(bear_fwd),
        n_directional=sum(1 for h in hits if h is not None),
    )


def _reweight(points: list[BacktestPoint], weights: dict[str, float]) -> list[float]:
    return [
        sum(weights.get(name, 0.0) * score for name, score in point.module_scores.items())
        for point in points
    ]


def evaluate_horizon(
    points: list[BacktestPoint],
    gold: list[tuple[date, float]],
    gold_index: dict[date, int],
    horizon: str,
    weights_cfg: dict[str, Any],
) -> HorizonResult:
    thresholds = weights_cfg["direction_thresholds"]
    bullish = float(thresholds["bullish"])
    bearish = float(thresholds["bearish"])
    month_weights = (
        weights_cfg.get("horizon_weights", {}).get("month", {}).get("modules")
        or weights_cfg["modules"]
    )
    aggregate_weights = weights_cfg["modules"]
    equal_weights = {name: 1.0 / 6.0 for name in MODULE_LABELS}
    no_trend = {**month_weights, "trend": 0.0}
    no_warsh = {**month_weights, "warsh_policy": 0.0}

    hits = [p.hit for p in points]
    judged = [h for h in hits if h is not None]
    always_long = [p.fwd_return > 0 for p in points if p.fwd_return != 0]
    momentum_hits: list[bool | None] = []
    for point in points:
        idx = gold_index[point.as_of]
        mom = _momentum_sign(gold, idx)
        momentum_hits.append(_hit(mom, point.actual_sign))

    by_direction = []
    for label in ("看多", "偏多", "中性", "偏空", "看空"):
        subset = [p for p in points if p.direction == label]
        if subset:
            by_direction.append(_bucket_metrics(label, subset))

    ordered = sorted(points, key=lambda p: p.confidence)
    tertile = max(len(ordered) // 3, 1)
    by_confidence = [
        _bucket_metrics("低置信", ordered[:tertile]),
        _bucket_metrics("中置信", ordered[tertile : 2 * tertile]),
        _bucket_metrics("高置信", ordered[2 * tertile :]),
    ]

    by_ab = []
    for label in ("同向确认", "弱确认", "相互背离", "均为中性", "无法验证"):
        subset = [p for p in points if p.ab_agreement == label]
        if subset:
            by_ab.append(_bucket_metrics(label, subset))

    module_spearman: dict[str, float | None] = {}
    for name in MODULE_LABELS:
        module_spearman[name] = spearman_corr(
            [p.module_scores.get(name, 0.0) for p in points],
            [p.fwd_return for p in points],
        )

    schemes = [
        _scheme_metrics("month 权重", points, [p.score for p in points], bullish, bearish),
        _scheme_metrics(
            "aggregate 权重",
            points,
            _reweight(points, aggregate_weights),
            bullish,
            bearish,
        ),
        _scheme_metrics("等权", points, _reweight(points, equal_weights), bullish, bearish),
        _scheme_metrics("月权重去趋势", points, _reweight(points, no_trend), bullish, bearish),
        _scheme_metrics("月权重去沃什", points, _reweight(points, no_warsh), bullish, bearish),
    ]

    bull_points = [p for p in points if p.pred_sign == 1]
    reversals = [p for p in bull_points if p.fwd_return < 0]
    hawkish = [
        p
        for p in reversals
        if p.dxy_20d_sign < 0 and p.real_rate_20d_sign < 0
    ]

    return HorizonResult(
        horizon=horizon,
        bars=HORIZON_BARS[horizon],
        n=len(points),
        n_directional=len(judged),
        hit_rate=_hit_rate(hits),
        spearman=spearman_corr(
            [p.score for p in points], [p.fwd_return for p in points]
        ),
        coverage=len(judged) / len(points) if points else 0.0,
        always_long_hit=(sum(always_long) / len(always_long)) if always_long else None,
        momentum_hit=_hit_rate(momentum_hits),
        mean_fwd=_mean([p.fwd_return for p in points]) or 0.0,
        mean_fwd_bull=_mean([p.fwd_return for p in points if p.pred_sign == 1]),
        mean_fwd_bear=_mean([p.fwd_return for p in points if p.pred_sign == -1]),
        by_direction=by_direction,
        by_confidence=by_confidence,
        by_ab=by_ab,
        module_spearman=module_spearman,
        schemes=schemes,
        reversal_rate=(len(reversals) / len(bull_points)) if bull_points else None,
        reversal_with_hawkish_macro=(
            len(hawkish) / len(reversals) if reversals else None
        ),
        points=points,
    )


def walk_forward(
    confirmed: list[DataRow],
    config_dir: Path,
    lags_cfg: dict[str, Any],
    horizon: str,
    score_horizon: str | None = "month",
) -> tuple[list[BacktestPoint], list[tuple[date, float]], dict[date, int]]:
    gold = _gold_series(confirmed)
    gold_index = {d: i for i, (d, _) in enumerate(gold)}
    bars = HORIZON_BARS[horizon]
    weights_cfg = load_weights(config_dir)
    thresholds = weights_cfg["direction_thresholds"]
    bullish = float(thresholds["bullish"])
    bearish = float(thresholds["bearish"])
    empty_validation = ValidationResult(confirmed=confirmed)

    points: list[BacktestPoint] = []
    last_i = len(gold) - 1 - bars
    for i in range(WARMUP_BARS, last_i + 1):
        as_of, price = gold[i]
        future_price = gold[i + bars][1]
        fwd = (future_price - price) / price if price else 0.0
        snapshot = rows_as_of(confirmed, as_of, lags_cfg)
        module_scores = compute_all_module_scores(
            snapshot, str(config_dir), as_of=as_of
        )
        forecast = compute_forecast(
            module_scores,
            empty_validation,
            snapshot,
            config_dir,
            horizon=score_horizon,
            as_of=as_of,
        )
        pred = _sign_from_threshold(forecast.total_score, bullish, bearish)
        actual = _return_sign(fwd)
        agreement = (
            forecast.cross_validation.agreement
            if forecast.cross_validation
            else "无法验证"
        )
        points.append(
            BacktestPoint(
                as_of=as_of,
                score=forecast.total_score,
                direction=forecast.direction,
                confidence=forecast.confidence,
                low_confidence=forecast.low_confidence,
                ab_agreement=agreement,
                price=price,
                fwd_return=fwd,
                module_scores={name: ms.score for name, ms in module_scores.items()},
                pred_sign=pred,
                actual_sign=actual,
                hit=_hit(pred, actual),
                dxy_20d_sign=_signal_sign(forecast, "dxy_20d"),
                real_rate_20d_sign=_signal_sign(forecast, "us_10y_real_rate_20d"),
            )
        )
    return points, gold, gold_index


def _parse_report(path: Path) -> tuple[date | None, float | None, float | None]:
    text = path.read_text(encoding="utf-8")
    cutoff_m = CUTOFF_RE.search(text)
    score_m = SCORE_RE.search(text)
    conf_m = CONFIDENCE_RE.search(text)
    cutoff = date.fromisoformat(cutoff_m.group(1)) if cutoff_m else None
    score = float(score_m.group(1)) if score_m else None
    confidence = float(conf_m.group(1)) / 100.0 if conf_m else None
    return cutoff, score, confidence


def replay_reports(
    reports_dir: Path,
    gold: list[tuple[date, float]],
    gold_index: dict[date, int],
    bars: int,
    bullish: float,
    bearish: float,
) -> list[ReportReplayPoint]:
    by_cutoff: dict[date, ReportReplayPoint] = {}
    if not reports_dir.exists():
        return []
    for path in sorted(reports_dir.glob("20*/monthly_*.md")):
        cutoff, score, confidence = _parse_report(path)
        if cutoff is None or score is None:
            continue
        fwd = None
        hit = None
        idx = gold_index.get(cutoff)
        if idx is None:
            earlier = [i for i, (d, _) in enumerate(gold) if d <= cutoff]
            idx = earlier[-1] if earlier else None
        if idx is not None and idx + bars < len(gold):
            price = gold[idx][1]
            future = gold[idx + bars][1]
            fwd = (future - price) / price if price else 0.0
            hit = _hit(_sign_from_threshold(score, bullish, bearish), _return_sign(fwd))
        point = ReportReplayPoint(
            report_date=date.fromisoformat(path.parent.name),
            cutoff=cutoff,
            score=score,
            confidence=confidence,
            path=str(path).replace("\\", "/"),
            fwd_return=fwd,
            hit=hit,
        )
        prev = by_cutoff.get(cutoff)
        if prev is None or point.report_date > prev.report_date or (
            point.report_date == prev.report_date and path.name > Path(prev.path).name
        ):
            by_cutoff[cutoff] = point
    return [by_cutoff[k] for k in sorted(by_cutoff)]


def run_backtest(
    input_path: Path,
    config_dir: Path,
    reports_dir: Path | None = None,
    horizons: tuple[str, ...] = ("week", "month"),
    apply_publication_lag: bool = True,
) -> BacktestResult:
    rows = load_csv(input_path)
    validation = validate_rows(rows, config_dir)
    confirmed = validation.confirmed
    lags_cfg = load_publication_lags(config_dir) if apply_publication_lag else {}
    weights_cfg = load_weights(config_dir)
    thresholds = weights_cfg["direction_thresholds"]
    gold_all = _gold_series(confirmed)

    horizon_results: list[HorizonResult] = []
    gold_ref: list[tuple[date, float]] = gold_all
    gold_index: dict[date, int] = {d: i for i, (d, _) in enumerate(gold_all)}
    for horizon in horizons:
        points, gold_ref, gold_index = walk_forward(
            confirmed, config_dir, lags_cfg, horizon
        )
        horizon_results.append(
            evaluate_horizon(points, gold_ref, gold_index, horizon, weights_cfg)
        )

    report_replay: dict[str, list[ReportReplayPoint]] = {}
    if reports_dir is not None:
        for horizon in horizons:
            report_replay[horizon] = replay_reports(
                reports_dir,
                gold_ref,
                gold_index,
                HORIZON_BARS[horizon],
                float(thresholds["bullish"]),
                float(thresholds["bearish"]),
            )

    notes = [
        "Walk-forward 用截至 as_of 的已发布数据重算当前打分函数，不是回放当时报告里的沃什版本。",
        "沃什因子仅在当前 yaml 的 speech_date–valid_until 窗口内非零。",
        "月度序列按 publication_lag.yaml 推迟可用日，避免把尚未公布的 CPI/PCE/社融打进当日分数。",
        "命中率只统计预测非中性且金价有涨跌的样本；Spearman 用全样本分数 vs 未来收益。",
        "样本期金价偏牛，须对照「永远做多」与「20 日动量」基线，避免虚高命中率。",
        "权重方案对比只提供校准线索，不自动改 weights.yaml。",
    ]
    return BacktestResult(
        generated_at=datetime.now(),
        input_path=str(input_path).replace("\\", "/"),
        gold_start=gold_all[0][0] if gold_all else None,
        gold_end=gold_all[-1][0] if gold_all else None,
        gold_days=len(gold_all),
        warmup_bars=WARMUP_BARS,
        horizons=horizon_results,
        report_replay=report_replay,
        notes=notes,
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1%}"


def _num(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}" if digits else f"{value:+.0f}"


def render_backtest_markdown(result: BacktestResult) -> str:
    lines = [
        "# 伦敦金打分 walk-forward 回测",
        "",
        f"生成时间：{result.generated_at.strftime('%Y-%m-%d %H:%M')}",
        f"输入：`{result.input_path}`",
        (
            f"金价样本：{result.gold_start} → {result.gold_end}，"
            f"{result.gold_days} 个交易日，预热 {result.warmup_bars} 根"
        ),
        "",
        "## 结论摘要",
        "",
    ]
    for hz in result.horizons:
        lines.append(
            f"- **{hz.horizon}（{hz.bars} 个交易日）**：命中率 {_pct(hz.hit_rate)}"
            f"（n={hz.n_directional}/{hz.n}）· Spearman {_num(hz.spearman)}"
            f" · 永远做多 {_pct(hz.always_long_hit)} · 20d 动量 {_pct(hz.momentum_hit)}"
        )
    lines += ["", "## 方法", ""]
    for note in result.notes:
        lines.append(f"- {note}")

    for hz in result.horizons:
        lines += [
            "",
            f"## {hz.horizon} 期限（未来 {hz.bars} 个交易日）",
            "",
            f"- 样本 {hz.n} 日，方向性样本 {hz.n_directional}（覆盖率 {hz.coverage:.1%}）",
            f"- 命中率 **{_pct(hz.hit_rate)}**",
            f"- Spearman(分数, 未来收益) **{_num(hz.spearman)}**",
            f"- 样本期平均未来收益 {hz.mean_fwd:+.2%}",
            f"- 预测偏多后平均收益 {_pct(hz.mean_fwd_bull)}；预测偏空后 {_pct(hz.mean_fwd_bear)}",
            f"- 永远做多 {_pct(hz.always_long_hit)}；20 日动量 {_pct(hz.momentum_hit)}",
            "",
            "### 按预测方向",
            "",
            "| 方向 | 日数 | 方向性 | 命中率 | 平均未来收益 | Spearman |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for bucket in hz.by_direction:
            lines.append(
                f"| {bucket.label} | {bucket.n} | {bucket.n_directional} | "
                f"{_pct(bucket.hit_rate)} | {bucket.mean_fwd:+.2%} | {_num(bucket.spearman)} |"
            )
        lines += [
            "",
            "### 按置信度三分位",
            "",
            "| 分层 | 日数 | 方向性 | 命中率 | 平均未来收益 | Spearman |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for bucket in hz.by_confidence:
            lines.append(
                f"| {bucket.label} | {bucket.n} | {bucket.n_directional} | "
                f"{_pct(bucket.hit_rate)} | {bucket.mean_fwd:+.2%} | {_num(bucket.spearman)} |"
            )
        if hz.by_ab:
            lines += [
                "",
                "### 按 A/B 交叉验证",
                "",
                "| 结论 | 日数 | 方向性 | 命中率 | 平均未来收益 |",
                "|---|---:|---:|---:|---:|",
            ]
            for bucket in hz.by_ab:
                lines.append(
                    f"| {bucket.label} | {bucket.n} | {bucket.n_directional} | "
                    f"{_pct(bucket.hit_rate)} | {bucket.mean_fwd:+.2%} |"
                )
        lines += [
            "",
            "### 模块分数 vs 未来收益（校准线索）",
            "",
            "| 模块 | Spearman |",
            "|---|---:|",
        ]
        for name, corr in hz.module_spearman.items():
            lines.append(f"| {MODULE_LABELS.get(name, name)} | {_num(corr)} |")
        lines += [
            "",
            "### 权重方案对比（同一套模块分，只换权重）",
            "",
            "| 方案 | 方向性 n | 命中率 | Spearman | 偏多后收益 | 偏空后收益 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for scheme in hz.schemes:
            lines.append(
                f"| {scheme.name} | {scheme.n_directional} | {_pct(scheme.hit_rate)} | "
                f"{_num(scheme.spearman)} | {_pct(scheme.mean_fwd_bull)} | "
                f"{_pct(scheme.mean_fwd_bear)} |"
            )
        lines += [
            "",
            "### 判断失效条件（代理检验）",
            "",
            f"- 预测偏多后金价下跌的比例：{_pct(hz.reversal_rate)}",
            f"- 其中当日 DXY 20d 与实际利率 20d 均已走强（对应「美元/利率持续上行」失效条件）的占比："
            f"{_pct(hz.reversal_with_hawkish_macro)}",
            "- 该占比高说明失效条件能覆盖多数打脸日；占比低说明打脸时宏观尚未转鹰，条件触发偏晚。",
        ]

    if result.report_replay:
        lines += ["", "## 历史报告回放", "", "用当时报告总分对照数据截止日后的金价，回答「哪次报告是对的」。"]
        for horizon, points in result.report_replay.items():
            graded = [p for p in points if p.hit is not None]
            hits = sum(1 for p in graded if p.hit)
            show = graded[-15:] if graded else points[-12:]
            lines += [
                "",
                f"### 报告 vs 未来 {horizon}",
                "",
                f"- 可评分报告 {len(graded)} / {len(points)}，命中率 "
                f"{_pct(hits / len(graded) if graded else None)}",
                "",
                "| 截止日 | 总分 | 未来收益 | 命中 | 报告 |",
                "|---|---:|---:|---|---|",
            ]
            for point in show:
                hit_label = "—" if point.hit is None else ("是" if point.hit else "否")
                fwd = "—" if point.fwd_return is None else f"{point.fwd_return:+.2%}"
                lines.append(
                    f"| {point.cutoff} | {point.score:+.3f} | {fwd} | {hit_label} | "
                    f"`{Path(point.path).name}` |"
                )

    lines += ["", "---", "*本回测由 gold-forecast backtest 生成，用于校准权重，不构成交易建议。*"]
    return "\n".join(lines) + "\n"


def _json_ready(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        data = asdict(value)
        if "points" in data and isinstance(data["points"], list) and data["points"]:
            # Keep JSON usable: drop per-day points from horizon blobs, store separately.
            data["n_points"] = len(data["points"])
            data["points"] = [
                {
                    "as_of": p["as_of"].isoformat()
                    if isinstance(p["as_of"], date)
                    else p["as_of"],
                    "score": p["score"],
                    "direction": p["direction"],
                    "confidence": p["confidence"],
                    "fwd_return": p["fwd_return"],
                    "hit": p["hit"],
                    "module_scores": p["module_scores"],
                }
                for p in data["points"]
            ]
        return _json_ready(data)
    return value


def write_backtest_outputs(result: BacktestResult, output_md: Path) -> tuple[Path, Path]:
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_backtest_markdown(result), encoding="utf-8")
    json_path = output_md.with_suffix(".json")
    json_path.write_text(
        json.dumps(_json_ready(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_md, json_path
