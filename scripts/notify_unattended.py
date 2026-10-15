"""Notify on unattended gate failures. Webhook URL comes from the environment."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from gold_forecast.unattended import update_fail_streak


def main() -> int:
    status_path = Path("data/audit/run_status.json")
    if status_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))
    else:
        status = {
            "status": "failed",
            "notify": True,
            "reasons": ["run_status_missing"],
        }

    state_dir = Path(".unattended-state")
    state_dir.mkdir(parents=True, exist_ok=True)
    streak_path = state_dir / "fail_streak"
    previous = int(streak_path.read_text(encoding="utf-8")) if streak_path.exists() else 0
    streak = update_fail_streak(previous, str(status.get("status", "failed")))
    streak_path.write_text(str(streak), encoding="utf-8")

    notify = bool(status.get("notify")) or streak >= 2
    print(f"fail_streak={streak} notify={notify}")
    if not notify:
        return 0

    webhook = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not webhook:
        print("ALERT_WEBHOOK_URL is unset; notification recorded only in the job log")
        return 0

    payload = {
        "text": (
            f"gold unattended {status.get('status')} "
            f"(streak={streak}): {', '.join(status.get('reasons') or [])}"
        ),
        "status": status.get("status"),
        "fail_streak": streak,
        "reasons": status.get("reasons") or [],
    }
    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            print(f"webhook_status={response.status}")
    except Exception as exc:
        print(f"webhook_failed:{exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
