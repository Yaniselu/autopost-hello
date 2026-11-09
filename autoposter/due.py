"""Runs at the start of every GitHub Actions job (standard library only, so it is
fast): decides whether a post is due right now and tells the next steps.

usage: python3 -m autoposter.due <event_name> <manual_mode>
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
WINDOW = dt.timedelta(minutes=100)  # GitHub can delay scheduled runs; the 2nd cron is a backup


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def decide(event: str, mode: str, now_utc: dt.datetime | None = None) -> dict:
    settings = _read(ROOT / "settings.json", {})
    if event == "workflow_dispatch":
        return {"run": "true", "mode": mode if mode in ("now", "test") else "test", "slot": ""}
    if settings.get("paused"):
        print("Paused from the panel -> nothing to do.")
        return {"run": "false", "mode": "", "slot": ""}
    tz = ZoneInfo(settings.get("timezone") or "Europe/Bucharest")
    now = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    done = set(_read(ROOT / "data" / "state.json", {}).get("done", []))
    for day in (now.date(), now.date() - dt.timedelta(days=1)):
        for t in sorted(settings.get("times") or []):
            slot = dt.datetime.combine(day, dt.time.fromisoformat(t), tzinfo=tz)
            if slot <= now < slot + WINDOW and slot.isoformat() not in done:
                print(f"Due: slot {slot.isoformat()}")
                return {"run": "true", "mode": "scheduled", "slot": slot.isoformat()}
    print(f"Nothing due at {now:%Y-%m-%d %H:%M} ({tz}).")
    return {"run": "false", "mode": "", "slot": ""}


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    mode = sys.argv[2] if len(sys.argv) > 2 else ""
    out = decide(event, mode)
    target = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in out.items())
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(lines)
    print(lines, end="")


if __name__ == "__main__":
    main()
