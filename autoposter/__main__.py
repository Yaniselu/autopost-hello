"""Velosyntech auto-poster.

  python -m autoposter start           pornește programul: postează singur, la infinit
  python -m autoposter setup           (re)conectează contul și cheile
  python -m autoposter now             face și postează un Reel chiar acum
  python -m autoposter now --dry-run   face un Reel fără să-l posteze (îl vezi în output/)
  python -m autoposter demo            video de test, fără nicio cheie
"""
import argparse
import datetime as dt
import json
import os
import random
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

from .config import DATA, OUTPUT, ROOT, load_config

DEMO_POST = {
    "topic": "AI tools that quietly save hours every week",
    "hook": "You're wasting *10 hours* a week",
    "slides": [
        "Let *AI* draft your emails, then just edit and send.",
        "Turn meeting recordings into *action items* automatically.",
        "Automate repetitive reports with one *scheduled workflow*.",
        "Spend the saved time on work that actually *grows* the business.",
    ],
    "cta": "Follow @velosyntech for more",
    "caption": "Most teams don't need more hours. They need fewer repetitive tasks.\n\n"
               "Start with one workflow this week and measure the time you get back.\n\n"
               "Which task would you automate first?",
    "hashtags": ["#ai", "#automation", "#productivity", "#tech", "#software",
                 "#business", "#startup", "#velosyntech"],
    "pexels_query": "abstract technology dark",
}

STATE_FILE = DATA / "state.json"
LOG_DIR = ROOT / "logs"


# ====================================================================== one post
def make_reel(cfg: dict, demo=False) -> tuple[Path, str, dict]:
    from .content import build_caption, generate_post, load_history
    from .media import fetch_pexels_video

    post = DEMO_POST if demo else generate_post(cfg, load_history())
    caption = build_caption(post)
    print(f"[content] {post['topic']}  |  hook: {post['hook']}")

    OUTPUT.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUTPUT / f"reel-{stamp}.mp4"
    work = Path(tempfile.mkdtemp(prefix="reel-"))
    try:
        bg = None
        if cfg["video"].get("background") == "pexels" and not demo:
            bg = fetch_pexels_video(post.get("pexels_query", "technology"), work / "bg.mp4", 15)
        seed = random.randint(0, 10 ** 9)
        if cfg["video"].get("style", "liquid_glass") == "liquid_glass":
            from .glass import render_glass_video
            render_glass_video(post, cfg, bg, out, work, seed=seed)
        else:
            from .render import render_video
            render_video(post, cfg, bg, out, work, seed=seed)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out.with_suffix(".txt").write_text(caption, encoding="utf-8")
    return out, caption, post


def post_once(cfg: dict, dry_run=False) -> None:
    from .content import load_history, save_history
    from .instagram import publish_reel

    video, caption, post = make_reel(cfg)
    if dry_run:
        print(f"[dry-run] video: {video}\n[dry-run] caption:\n{caption}")
        return
    media_id, link = publish_reel(video, caption, cfg)
    save_history(load_history(), {
        "time": dt.datetime.now().astimezone().isoformat(timespec="minutes"), "status": "posted",
        "topic": post["topic"], "pillar": post.get("pillar"), "hook": post["hook"],
        "caption": caption, "media_id": media_id, "permalink": link,
    })
    _cleanup_output(cfg)


def run_cloud(cfg: dict, mode: str, slot: str) -> None:
    """One GitHub Actions run: make the video, post it (unless test), record everything."""
    from zoneinfo import ZoneInfo

    from .content import load_history, save_history
    from .instagram import publish_reel

    entry = {
        "time": dt.datetime.now(ZoneInfo(cfg.get("timezone", "Europe/Bucharest"))).isoformat(timespec="minutes"),
        "mode": mode, "slot": slot or None, "run_url": os.environ.get("RUN_URL"),
    }
    failed = False
    try:
        video, caption, post = make_reel(cfg)
        entry.update(topic=post["topic"], pillar=post.get("pillar"), hook=post["hook"], caption=caption)
        if mode == "test":
            entry["status"] = "test"
        else:
            media_id, link = publish_reel(video, caption, cfg)
            entry.update(status="posted", media_id=media_id, permalink=link)
    except BaseException as e:  # noqa: BLE001 - record any failure in the panel's history
        failed = True
        entry.update(status="error", error=f"{type(e).__name__}: {e}"[:600])
        traceback.print_exc()
    finally:
        save_history(load_history(), entry)
        if slot:
            state = _load_state()
            state["done"].append(slot)
            _save_state(state)
    print(json.dumps({k: entry.get(k) for k in ("status", "hook", "permalink", "error")}, ensure_ascii=False))
    if failed:
        sys.exit(1)


def _cleanup_output(cfg):
    keep = cfg.get("schedule", {}).get("keep_videos", 30)
    vids = sorted(OUTPUT.glob("reel-*.mp4"))
    for v in vids[:-keep] if keep else []:
        v.unlink(missing_ok=True)
        v.with_suffix(".txt").unlink(missing_ok=True)


# ====================================================================== forever loop
def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"done": []}


def _save_state(state: dict) -> None:
    state["done"] = state["done"][-200:]
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _slots(cfg, day: dt.date) -> list[dt.datetime]:
    times = cfg["schedule"]["times"]
    return sorted(dt.datetime.combine(day, dt.time.fromisoformat(t)) for t in times)


def _next_slot(cfg, now: dt.datetime) -> dt.datetime:
    for day in (now.date(), now.date() + dt.timedelta(days=1)):
        for s in _slots(cfg, day):
            if s > now:
                return s
    raise RuntimeError("no schedule times configured")


class _Tee:
    """Writes everything printed to the console into logs/autoposter.log too."""

    def __init__(self, stream, path):
        self.stream, self.file = stream, open(path, "a", encoding="utf-8", buffering=1)

    def write(self, s):
        self.stream.write(s)
        self.file.write(s)

    def flush(self):
        self.stream.flush()
        self.file.flush()


def run_forever(cfg: dict) -> None:
    from .instagram import check_connection
    from .setup_wizard import run_setup

    LOG_DIR.mkdir(exist_ok=True)
    sys.stdout = _Tee(sys.stdout, LOG_DIR / "autoposter.log")
    sys.stderr = _Tee(sys.stderr, LOG_DIR / "autoposter.log")

    if not all(os.environ.get(k) for k in ("GEMINI_API_KEY", "IG_USER_ID", "IG_ACCESS_TOKEN")):
        run_setup(cfg)
    try:
        user = check_connection(cfg)
    except Exception as e:
        print(f"Conexiunea la Instagram nu merge ({e}). Hai să o refacem.")
        run_setup(cfg)
        user = check_connection(cfg)

    sch = cfg["schedule"]
    grace = dt.timedelta(minutes=sch.get("grace_minutes", 45))
    print("\n" + "=" * 62)
    print(f"  ✓ Conectat la Instagram: @{user}")
    print(f"  ✓ Postez {len(sch['times'])} Reels pe zi, la orele: {', '.join(sorted(sch['times']))}")
    print("  Lasă fereastra deschisă. Oprești cu Ctrl+C.")
    print("=" * 62 + "\n")

    state = _load_state()
    announced = None
    while True:
        now = dt.datetime.now()
        due = [s for s in _slots(cfg, now.date())
               if s <= now <= s + grace and s.isoformat() not in state["done"]]
        if due:
            slot = due[0]
            print(f"\n[{now:%Y-%m-%d %H:%M}] ▶ Postarea de la {slot:%H:%M}")
            for attempt in range(1, sch.get("retries", 3) + 1):
                try:
                    post_once(cfg)
                    print(f"[{dt.datetime.now():%H:%M}] ✓ Postat!")
                    break
                except Exception as e:
                    print(f"[{dt.datetime.now():%H:%M}] ✗ Încercarea {attempt} a eșuat: {e}")
                    traceback.print_exc()
                    time.sleep(120 * attempt)
            state["done"].append(slot.isoformat())
            _save_state(state)
            announced = None
            continue

        nxt = _next_slot(cfg, now)
        if announced != nxt:
            print(f"[{now:%Y-%m-%d %H:%M}] ⏳ Următoarea postare: {nxt:%A %H:%M}")
            announced = nxt
        time.sleep(max(5, min(60, (nxt - now).total_seconds())))


# ====================================================================== CLI
def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="autoposter", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("start")
    sub.add_parser("setup")
    p = sub.add_parser("now")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("post")  # alias kept for GitHub Actions
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("demo")
    p = sub.add_parser("cloud")  # used by GitHub Actions
    p.add_argument("--mode", default="test", choices=["test", "now", "scheduled"])
    p.add_argument("--slot", default="")
    args = ap.parse_args()
    cfg = load_config()

    try:
        if args.cmd in (None, "start"):
            run_forever(cfg)
        elif args.cmd == "setup":
            from .setup_wizard import run_setup
            run_setup(cfg)
        elif args.cmd in ("now", "post"):
            post_once(cfg, dry_run=args.dry_run)
        elif args.cmd == "cloud":
            run_cloud(cfg, args.mode, args.slot)
        elif args.cmd == "demo":
            video, caption, _ = make_reel(cfg, demo=True)
            print(f"\nVideo: {video}\n\nCaption:\n{caption}")
    except KeyboardInterrupt:
        print("\nOprit. Pornește din nou oricând.")


if __name__ == "__main__":
    main()
