"""Warsh policy factor — qualitative Fed chair signals for gold forecasting."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from gold_forecast.indicators import SignalDetail


def load_warsh_config(config_dir: Path) -> dict[str, Any]:
    path = config_dir / "warsh_factor.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value).strip()[:10])


def _is_active(cfg: dict[str, Any], as_of: date) -> bool:
    meta = cfg.get("meta", {})
    speech_date = _parse_iso_date(meta.get("speech_date"))
    valid_until = _parse_iso_date(meta.get("valid_until"))
    if speech_date and as_of < speech_date:
        return False
    if valid_until and as_of > valid_until:
        return False
    return bool(cfg.get("dimensions"))


def compute_warsh_signals(
    config_dir: Path,
    as_of: date | None = None,
) -> list[SignalDetail]:
    """Return per-dimension Warsh signals; empty if config missing or expired."""
    cfg = load_warsh_config(config_dir)
    if not cfg:
        return []

    today = as_of or date.today()
    if not _is_active(cfg, today):
        return []

    signals: list[SignalDetail] = []
    for name, dim in cfg.get("dimensions", {}).items():
        score = float(dim.get("score", 0.0))
        label = dim.get("label", name)
        desc = dim.get("description", label)
        signals.append(
            SignalDetail(
                name=f"warsh_{name}",
                score=max(-1.0, min(1.0, score)),
                description=f"{label}: {desc}",
            )
        )

    composite = _composite_score(cfg)
    if composite is not None:
        meta = cfg.get("meta", {})
        venue = meta.get("venue", "policy speech")
        speech = meta.get("speech_date", "")
        signals.append(
            SignalDetail(
                name="warsh_composite",
                score=composite,
                description=f"沃什因子综合 ({venue}, {speech})",
            )
        )
    return signals


def _composite_score(cfg: dict[str, Any]) -> float | None:
    dims = cfg.get("dimensions", {})
    if not dims:
        return None
    weighted = 0.0
    weight_sum = 0.0
    for dim in dims.values():
        w = float(dim.get("weight", 1.0))
        s = float(dim.get("score", 0.0))
        weighted += w * s
        weight_sum += abs(w)
    if weight_sum == 0:
        return None
    return max(-1.0, min(1.0, weighted / weight_sum))
