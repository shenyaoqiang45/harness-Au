"""CLI entry point for the gold forecast MVP."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from gold_forecast.collector import run_fetch
from gold_forecast.data_loader import load_csv, write_csv
from gold_forecast.indicators import compute_all_module_scores
from gold_forecast.report import render_report, write_report
from gold_forecast.scoring import compute_forecast
from gold_forecast.missing_sources import compute_missing_sources, write_missing_sources_log
from gold_forecast.validator import ValidationResult, validate_rows


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_report_output_path(requested: Path, generated_at: datetime) -> Path:
    """Archive report outputs by execution date to avoid overwriting files."""
    root = _project_root()
    reports_dir = (root / "reports").resolve()
    try:
        requested_abs = requested.resolve()
    except FileNotFoundError:
        requested_abs = requested.absolute()

    # Keep non-report destinations unchanged for explicit external paths.
    if reports_dir not in requested_abs.parents and requested_abs != reports_dir:
        return requested

    stamp_date = generated_at.strftime("%Y-%m-%d")
    stamp_time = generated_at.strftime("%Y%m%d_%H%M%S")
    stem = requested.stem or "report"
    suffix = requested.suffix or ".md"
    return reports_dir / stamp_date / f"{stem}_{stamp_time}{suffix}"


def _write_audit_log(path: Path, validation: ValidationResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for issue in validation.anomalies:
        entries.append(
            {
                "timestamp": datetime.now().isoformat(),
                "severity": issue.severity,
                "indicator": issue.row.indicator,
                "date": issue.row.date.isoformat(),
                "line": issue.row.raw_line,
                "reason": issue.reason,
            }
        )
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(
    input_path: Path,
    output_path: Path,
    config_dir: Path | None = None,
    data_dir: Path | None = None,
    horizon: str | None = None,
) -> int:
    root = _project_root()
    config_dir = config_dir or root / "config"
    data_dir = data_dir or root / "data"

    raw_rows = load_csv(input_path)
    validation = validate_rows(raw_rows, config_dir)

    validated_path = data_dir / "validated" / "latest.csv"
    clean_path = data_dir / "clean" / "latest.csv"
    audit_path = data_dir / "audit" / "anomalies.json"

    all_validated = validation.confirmed + [i.row for i in validation.pending]
    write_csv(validated_path, all_validated)
    write_csv(clean_path, validation.confirmed)
    _write_audit_log(audit_path, validation)

    module_scores = compute_all_module_scores(validation.confirmed, str(config_dir))
    present = {r.indicator for r in validation.confirmed}
    missing_sources = compute_missing_sources(config_dir, present)
    write_missing_sources_log(data_dir / "audit" / "missing_sources.json", missing_sources)
    forecast = compute_forecast(
        module_scores, validation, validation.confirmed, config_dir, horizon=horizon
    )
    report_text = render_report(forecast, validation, missing_sources)
    final_output = _resolve_report_output_path(output_path, forecast.generated_at)
    write_report(final_output, report_text)

    print(f"Report written to {final_output}")
    print(f"Direction: {forecast.direction} | Score: {forecast.total_score:+.3f}")
    print(f"Confirmed rows: {len(validation.confirmed)}")
    print(f"Missing sources: {len(missing_sources)} (see {data_dir / 'audit' / 'missing_sources.json'})")
    print(f"Anomalies: {len(validation.anomalies)} (see {audit_path})")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    root = _project_root()
    config_dir = args.config or root / "config"
    result = run_fetch(config_dir, root, args.output, merge_history=not args.no_merge)
    out = args.output or root / "data" / "raw" / "live.csv"
    print(f"Fetched {len(result.records)} indicator rows -> {out}")
    if result.warnings:
        print(f"Warnings: {len(result.warnings)} (see data/audit/fetch_log.json)")
    if result.errors:
        print(f"Errors: {len(result.errors)}")
        for err in result.errors[:5]:
            print(f"  - {err}")
    missing_path = root / "data" / "audit" / "missing_sources.json"
    if missing_path.exists():
        print(f"Missing sources logged -> {missing_path}")
    return 0 if result.records else 1


def cmd_report(args: argparse.Namespace) -> int:
    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 1
    return run_pipeline(args.input, args.output, args.config, horizon=args.horizon)


def cmd_run(args: argparse.Namespace) -> int:
    root = _project_root()
    fetch_args = argparse.Namespace(
        config=args.config,
        output=root / "data" / "raw" / "live.csv",
        no_merge=args.no_merge,
    )
    code = cmd_fetch(fetch_args)
    if code != 0 and not args.allow_empty:
        return code
    report_args = argparse.Namespace(
        input=root / "data" / "raw" / "live.csv",
        output=args.output,
        config=args.config,
        horizon=args.horizon,
    )
    return cmd_report(report_args)


def main(argv: list[str] | None = None) -> int:
    root = _project_root()
    parser = argparse.ArgumentParser(
        description="London gold trend judgment system (MVP)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Config directory (default: project config/)",
    )
    sub = parser.add_subparsers(dest="command")

    fetch_p = sub.add_parser("fetch", help="Pull live data into CSV")
    fetch_p.add_argument(
        "--output",
        "-o",
        type=Path,
        default=root / "data" / "raw" / "live.csv",
    )
    fetch_p.add_argument(
        "--no-merge",
        action="store_true",
        help="Replace output instead of merging with existing live.csv",
    )

    report_p = sub.add_parser("report", help="Generate report from CSV")
    report_p.add_argument(
        "--input",
        "-i",
        type=Path,
        default=root / "data" / "raw" / "live.csv",
    )
    report_p.add_argument(
        "--output",
        "-o",
        type=Path,
        default=root / "reports" / "monthly.md",
    )
    report_p.add_argument(
        "--horizon",
        choices=["aggregate", "month"],
        default="month",
        help="Forecast horizon focus (aggregate uses default weights, month emphasises 1-month drivers)",
    )

    run_p = sub.add_parser("run", help="Fetch live data then generate report")
    run_p.add_argument(
        "--output",
        "-o",
        type=Path,
        default=root / "reports" / "monthly.md",
    )
    run_p.add_argument(
        "--horizon",
        choices=["aggregate", "month"],
        default="month",
        help="Forecast horizon focus (aggregate uses default weights, month emphasises 1-month drivers)",
    )
    run_p.add_argument("--no-merge", action="store_true")
    run_p.add_argument(
        "--allow-empty",
        action="store_true",
        help="Continue to report even if fetch returns no rows",
    )

    # backward compatible: no subcommand => report with --input/--output
    parser.add_argument("--input", "-i", type=Path, default=None)
    parser.add_argument("--output", "-o", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "fetch":
        return cmd_fetch(args)
    if args.command == "report":
        if args.input is None:
            args.input = root / "data" / "raw" / "live.csv"
        if args.output is None:
            args.output = root / "reports" / "monthly.md"
        return cmd_report(args)
    if args.command == "run":
        return cmd_run(args)

    # legacy default (sample.csv removed; use live.csv as the real data source)
    input_path = args.input or root / "data" / "raw" / "live.csv"
    output_path = args.output or root / "reports" / "monthly.md"
    legacy = argparse.Namespace(
        input=input_path, output=output_path, config=args.config, horizon="month"
    )
    return cmd_report(legacy)


if __name__ == "__main__":
    sys.exit(main())
