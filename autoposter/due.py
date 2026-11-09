"""First step of every GitHub Actions run (standard library only, so it is fast):
decides WHAT to do now: a reel, a carousel, a story, comment replies, or nothing.

usage: python3 -m autoposter.due <event_name> <manual_mode> <manual_kind> <cron_that_fired>
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
WINDOW = dt.timedelta(minutes=100)  # GitHub may start scheduled runs late; a 2nd cron line acts as backup
COMMENTS_MINUTE = "41"
KINDS = (("reel", "times"), ("carousel", "carousel_times"), ("story", "story_times"))


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def settings() -> dict:
    return _read(ROOT / "settings.json", {})


def due_slots(now_utc: dt.datetime, done: list, s: dict | None = None) -> list[tuple[str, str]]:
    s = settings() if s is None else s
    if s.get("paused"):
        return []
    tz = ZoneInfo(s.get("timezone") or "Europe/Bucharest")
    now = now_utc.astimezone(tz)
    done = set(done)
    out = []
    for kind, key in KINDS:
        for day in (now.date(), now.date() - dt.timedelta(days=1)):
            for t in sorted(s.get(key) or []):
                slot = dt.datetime.combine(day, dt.time.fromisoformat(t), tzinfo=tz)
                tag = f"{kind}@{slot.isoformat()}"
                if slot <= now < slot + WINDOW and tag not in done and slot.isoformat() not in done:
                    out.append((kind, tag))
    return out


def decide(event: str, mode: str, kind: str, cron: str, now_utc: dt.datetime | None = None) -> dict:
    nothing = {"run": "false", "mode": "", "slot": "", "kind": ""}
    if event == "workflow_dispatch":
        k = kind if kind in ("reel", "carousel", "story", "comments") else "reel"
        return {"run": "true", "mode": mode if mode in ("now", "test") else "test", "slot": "", "kind": k}
    s = settings()
    if s.get("paused"):
        print("Paused from the panel -> nothing to do.")
        return nothing
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    done = _read(ROOT / "data" / "state.json", {}).get("done", [])
    due = due_slots(now_utc, done, s)
    if due:
        k, tag = due[0]
        print(f"Due: {tag}")
        return {"run": "true", "mode": "scheduled", "slot": tag, "kind": k}
    if cron.startswith(COMMENTS_MINUTE + " ") and (s.get("comments") or {}).get("enabled", True):
        print("Checking comments.")
        return {"run": "true", "mode": "scheduled", "slot": "", "kind": "comments"}
    print(f"Nothing due at {now_utc:%Y-%m-%d %H:%M} UTC.")
    return nothing


def main():
    a = sys.argv[1:] + ["", "", "", ""]
    out = decide(a[0], a[1], a[2], a[3])
    lines = "".join(f"{k}={v}\n" for k, v in out.items())
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(lines)
    print(lines, end="")


if __name__ == "__main__":
    main()
