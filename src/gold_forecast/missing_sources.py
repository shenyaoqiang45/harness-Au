"""Track indicators that are expected but not present in live data."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import yaml


_ERROR_PREFIX = re.compile(r"^(?:yahoo|fred|eastmoney|akshare|cme|derived):([^:]+):")


def _load_sources_config(config_dir: Path) -> dict:
    with (config_dir / "sources.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@dataclass
class MissingSource:
    indicator: str
    expected_source: str
    reason: str
    source_url: str = ""
    detail: str = ""

    @property
    def reason_label(self) -> str:
        labels = {
            "no_automated_fetcher": "未接入自动抓取",
            "fetch_failed": "抓取失败",
            "not_in_dataset": "数据集中缺失",
        }
        return labels.get(self.reason, self.reason)


def _automated_indicators(cfg: dict) -> dict[str, dict]:
    """Indicator -> metadata from enabled automated sources."""
    out: dict[str, dict] = {}
    for source_name, source_cfg in cfg.get("sources", {}).items():
        if not source_cfg.get("enabled", True):
            continue
        for indicator, meta in source_cfg.get("indicators", {}).items():
            out[indicator] = {
                "expected_source": meta.get("source", source_name),
                "source_url": meta.get("source_url", ""),
            }
    return out


def _unwired_indicators(cfg: dict) -> dict[str, dict]:
    unwired = cfg.get("unwired", {})
    if unwired:
        return {
            name: {
                "expected_source": meta.get("expected_source", ""),
                "source_url": meta.get("source_url", ""),
                "note": meta.get("note", ""),
            }
            for name, meta in unwired.items()
        }

    # Backward compatibility with legacy `optional` list.
    optional = cfg.get("optional", [])
    return {
        name: {"expected_source": "", "source_url": "", "note": ""}
        for name in optional
    }


def parse_fetch_errors(errors: list[str]) -> dict[str, str]:
    """Map indicator name -> error detail from fetcher error strings."""
    by_indicator: dict[str, str] = {}
    for err in errors:
        match = _ERROR_PREFIX.match(err)
        if match:
            by_indicator[match.group(1)] = err.split(":", 2)[-1].strip()
    return by_indicator


def compute_missing_sources(
    config_dir: Path,
    present: set[str],
    fetch_errors: list[str] | None = None,
) -> list[MissingSource]:
    cfg = _load_sources_config(config_dir)
    automated = _automated_indicators(cfg)
    unwired = _unwired_indicators(cfg)
    optional = set(cfg.get("optional", []))
    error_map = parse_fetch_errors(fetch_errors or [])

    missing: list[MissingSource] = []

    for indicator, meta in automated.items():
        if indicator in present or indicator in optional:
            continue
        detail = error_map.get(indicator, "")
        reason = "fetch_failed" if detail else "not_in_dataset"
        missing.append(
            MissingSource(
                indicator=indicator,
                expected_source=meta.get("expected_source", ""),
                reason=reason,
                source_url=meta.get("source_url", ""),
                detail=detail,
            )
        )

    for indicator, meta in unwired.items():
        if indicator in present or indicator in optional:
            continue
        missing.append(
            MissingSource(
                indicator=indicator,
                expected_source=meta.get("expected_source", ""),
                reason="no_automated_fetcher",
                source_url=meta.get("source_url", ""),
                detail=meta.get("note", ""),
            )
        )

    return sorted(missing, key=lambda item: (item.reason, item.indicator))


def unwired_indicator_names(config_dir: Path) -> set[str]:
    cfg = _load_sources_config(config_dir)
    return set(_unwired_indicators(cfg).keys())


def write_missing_sources_log(path: Path, missing: list[MissingSource]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now().isoformat(),
        "count": len(missing),
        "missing": [asdict(item) for item in missing],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
