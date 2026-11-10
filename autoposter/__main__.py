"""Velosyntech auto-poster.

  python -m autoposter cloud --kind reel|carousel|story|comments --mode test|now|scheduled
                                     (what GitHub Actions runs)
  python -m autoposter demo          cinematic demo reel, no API keys needed (output/)
  python -m autoposter start         local mode: runs forever on this computer
  python -m autoposter setup         local mode: connect keys/account
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

STATE_FILE = DATA / "state.json"
LOG_DIR = ROOT / "logs"

DEMO_REEL = {
    "topic": "Automating follow-ups and reports",
    "hook": "Your team loses *8 hours* every week",
    "app_name": "FlowDesk",
    "problem": {"text": "Manual follow-ups, copy-paste reports and *missed leads* pile up.",
                "alerts": ["12 unread follow-ups", "Report overdue", "Lead went cold"]},
    "solution": {"steps": [{"title": "Capture every lead", "text": "Forms sync straight into your CRM"},
                           {"title": "Auto follow-ups", "text": "Smart emails go out on schedule"},
                           {"title": "Live reports", "text": "Dashboards update themselves daily"}]},
    "result": "Your team gets *8 hours* back. Every week.",
    "cta": "Follow for weekly automation ideas",
    "caption": "Most teams don't need more hours. They need fewer repetitive tasks.\n\nWhich task would you automate first?",
    "hashtags": ["#automation", "#ai", "#productivity", "#business", "#velosyntech"],
}


# ====================================================================== rendering
def _reel_as_slides(post: dict) -> dict:
    """Adapter so the older (non-3D) styles can render a hook/problem/solution script."""
    p = dict(post)
    p["slides"] = [post["problem"]["text"]] + [f"*{s['title']}*: {s['text']}" for s in post["solution"]["steps"]] + [post["result"]]
    return p


STYLE_CYCLE = ["cinematic", "liquid_glass"]


def pick_style(cfg: dict, history: list) -> str:
    """'rotate' alternates the looks through the day: 1st, 3rd... reel cinematic 3D, 2nd, 4th... liquid glass."""
    style = cfg["video"].get("style", "cinematic")
    if style != "rotate":
        return style
    slot, times = cfg.get("_slot") or "", sorted(cfg["schedule"].get("times") or [])
    hhmm = slot.split("T")[1][:5] if "T" in slot else ""
    from .learning import style_bias
    winner = style_bias()
    if hhmm in times:
        idx = times.index(hhmm)
        if winner in STYLE_CYCLE:  # the clear winner gets 2 of every 3 slots
            return winner if idx % 3 != 2 else next(x for x in STYLE_CYCLE if x != winner)
        return STYLE_CYCLE[idx % len(STYLE_CYCLE)]
    last = next((h.get("style") for h in reversed(history) if h.get("type", "reel") == "reel" and h.get("style")), None)
    return STYLE_CYCLE[(STYLE_CYCLE.index(last) + 1) % len(STYLE_CYCLE)] if last in STYLE_CYCLE else STYLE_CYCLE[0]


def render_reel(post: dict, cfg: dict, out: Path, work: Path, seed: int, previous_plan: dict | None = None,
                style: str | None = None, vo: dict | None = None) -> Path:
    style = style or cfg["video"].get("style", "cinematic")
    if style == "liquid_glass":
        from .liquid import render_liquid_reel
        return render_liquid_reel(post, cfg, out, work, seed, vo)
    if style in ("cinematic", "rotate"):
        from .cinematic import render_cinematic_reel
        return render_cinematic_reel(post, cfg, out, work, seed, previous_plan, vo)
    if style == "liquid_glass":
        from .glass import render_glass_video
        return render_glass_video(_reel_as_slides(post), cfg, None, out, work, seed=seed)
    from .render import render_video
    return render_video(_reel_as_slides(post), cfg, None, out, work, seed=seed)


def _upload_previews(paths: list[Path]) -> list[str]:
    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        return []
    from .publish import blob_upload
    urls = []
    for p in paths:
        try:
            urls.append(blob_upload(p, "previews"))
        except Exception as e:  # noqa: BLE001
            print(f"[preview] upload failed: {e}")
    return urls


def _repost(kind: str, source: Path, cfg: dict, work: Path, publish: bool, palette: str | None = None) -> dict:
    """Story announcing the new reel/carousel (on Instagram + Facebook). Never fails the main post."""
    if not cfg.get("repost_to_story", True):
        return {}
    from . import publish as pub
    from .glass import PALETTES
    from .llm import redact
    from .repost import frame_from_video, make_repost_story
    try:
        p = PALETTES.get(palette or "", PALETTES["aurora"])
        src = frame_from_video(source, work / "repost-src.jpg") if source.suffix == ".mp4" else source
        img = make_repost_story(src, kind, cfg, OUTPUT / f"repost-{source.stem}.jpg", tuple(p["accent"]), tuple(p["accent2"]))
        if not publish:
            return {"repost_preview": img}
        url = pub.blob_upload(img, "media")
        try:
            res = pub.both(lambda: pub.ig_story(url, cfg), lambda: pub.fb_story(url, cfg), cfg)
        finally:
            pub.blob_delete([url])
        return {"repost": "ok", **({"repost_fb_error": res["fb_error"]} if res.get("fb_error") else {})}
    except Exception as e:  # noqa: BLE001
        print(f"[repost] failed: {redact(e)}")
        return {"repost_error": redact(f"{type(e).__name__}: {e}")[:300]}


# ====================================================================== jobs
def run_job(cfg: dict, kind: str, mode: str) -> dict:
    """Makes (and unless mode == 'test', publishes) one piece of content. Returns a history entry."""
    from .content import build_caption, generate_carousel, generate_reel, generate_stories, load_history
    from . import publish as pub

    history = load_history()
    seed = random.randint(0, 10 ** 9)
    if kind != "comments":
        # read the real account: logo, grid, bio, and the style learned from its own posts
        from .account import fetch_account, recent_topics, render_assets, style_guide
        acct = fetch_account(cfg)
        cfg["_account"] = {"guide": style_guide(cfg, acct), "bio": (acct or {}).get("biography"),
                           "ig_recent": recent_topics(acct), "assets": render_assets(acct)}
        try:
            from .learning import update_performance
            update_performance(cfg, history)
        except Exception as e:  # noqa: BLE001 - stats are a bonus
            print(f"[learning] skipped: {e}")
    OUTPUT.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    work = Path(tempfile.mkdtemp(prefix=f"{kind}-"))
    entry = {"type": kind}
    try:
        if kind == "reel":
            post = generate_reel(cfg, history)
            caption = build_caption(post)
            entry.update(topic=post["topic"], pillar=post.get("pillar"), hook=post["hook"], caption=caption,
                         hook_type=post.get("hook_type"), hook_options=post.get("hook_options"))
            prev = next((h.get("plan") for h in reversed(history) if h.get("plan") and h["plan"].get("hook")), None)
            style = pick_style(cfg, history)
            entry["style"] = style
            print(f"[reel] style: {style}")
            from .voice import make_voiceover
            vo = make_voiceover(post, cfg, seed, work, history)
            if vo:
                entry["voice"] = vo["voice"]
            video = render_reel(post, cfg, OUTPUT / f"reel-{stamp}.mp4", work, seed, prev, style, vo)
            if post.get("_plan"):
                entry["plan"] = post["_plan"]
            pal = (post.get("_plan") or {}).get("palette")
            if mode == "test":
                rp = _repost("reel", video, cfg, work, False, pal).get("repost_preview")
                entry.update(status="test", previews=_upload_previews([video] + ([rp] if rp else [])))
            else:
                entry.update(pub.both(lambda: pub.ig_reel(video, caption, cfg), lambda: pub.fb_reel(video, caption, cfg), cfg))
                entry["status"] = "posted"
                entry.update(_repost("reel", video, cfg, work, True, pal))

        elif kind == "carousel":
            from .stills import render_carousel
            post = generate_carousel(cfg, history)
            caption = build_caption(post)
            entry.update(topic=post["topic"], pillar=post.get("pillar"), hook=post["title"], caption=caption)
            images = render_carousel(post, cfg, work, seed)
            for i, im in enumerate(images):
                shutil.copy(im, OUTPUT / f"carousel-{stamp}-{i:02d}.jpg")
            if mode == "test":
                rp = _repost("carousel", images[0], cfg, work, False).get("repost_preview")
                entry.update(status="test", previews=_upload_previews(images + ([rp] if rp else [])))
            else:
                urls = [pub.blob_upload(p, "media") for p in images]
                try:
                    entry.update(pub.both(lambda: pub.ig_carousel(urls, caption, cfg),
                                          lambda: pub.fb_carousel(urls, caption, cfg), cfg))
                finally:
                    pub.blob_delete(urls)
                entry["status"] = "posted"
                entry.update(_repost("carousel", images[0], cfg, work, True))

        elif kind == "story":
            from .stills import render_stories
            n = int(cfg.get("stories_per_slot", 1))
            stories = generate_stories(cfg, history, n)
            entry.update(topic="; ".join(s["title"] for s in stories), hook=stories[0]["title"],
                         caption="\n".join(f"{s['title']} — {s['body']}" for s in stories))
            images = render_stories(stories, cfg, work, seed)
            for i, im in enumerate(images):
                shutil.copy(im, OUTPUT / f"story-{stamp}-{i}.jpg")
            if mode == "test":
                entry.update(status="test", previews=_upload_previews(images))
            else:
                results = []
                for im in images:
                    url = pub.blob_upload(im, "media")
                    try:
                        results.append(pub.both(lambda: pub.ig_story(url, cfg), lambda: pub.fb_story(url, cfg), cfg))
                    finally:
                        pub.blob_delete([url])
                entry.update(status="posted", stories=results,
                             fb_error=next((r["fb_error"] for r in results if r.get("fb_error")), None))
        else:
            raise ValueError(f"unknown kind {kind}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return entry


HEALTH_FILE = DATA / "health.json"


def check_connection_health(cfg: dict) -> tuple[bool, str]:
    """Cheap check that Instagram still accepts our token (before spending minutes on a video)."""
    import requests
    if not (os.environ.get("IG_USER_ID") and os.environ.get("IG_ACCESS_TOKEN")):
        return False, "Contul Instagram nu e conectat (lipsesc cheile)."
    try:
        r = requests.get(f"https://graph.facebook.com/{cfg['instagram']['graph_version']}/{os.environ['IG_USER_ID']}",
                         params={"fields": "username", "access_token": os.environ["IG_ACCESS_TOKEN"]}, timeout=30)
        data = r.json()
    except Exception as e:  # noqa: BLE001 - network hiccup: don't block, let the real call decide
        return True, f"check skipped ({type(e).__name__})"
    if r.ok and data.get("username"):
        return True, data["username"]
    err = data.get("error", {})
    return False, (f"Instagram nu mai acceptă conexiunea ({err.get('message', r.status_code)}). "
                   "Reconectează contul în panou: Cont & chei → token nou din Graph API Explorer → Conectează.")


def _write_health(ok: bool, msg: str) -> None:
    HEALTH_FILE.write_text(json.dumps({"ok": ok, "message": msg, "checked": dt.datetime.now(dt.timezone.utc)
                                       .isoformat(timespec="minutes")}, ensure_ascii=False, indent=1), encoding="utf-8")


def _retryable(err: str) -> bool:
    e = err.lower()
    return any(x in e for x in ("oauth", "reconecteaz", "http 5", "timeout", "timed out", "connection", "429",
                                "rate limit", "temporarily", "text generation failed", "please retry"))


def run_cloud(cfg: dict, kind: str, mode: str, slot: str) -> None:
    """One GitHub Actions run. Records the result for the panel's history."""
    from zoneinfo import ZoneInfo

    from .content import load_history, save_history
    from .llm import redact

    if mode != "test":
        ok, msg = check_connection_health(cfg)
        _write_health(ok, msg)
        if not ok and kind == "comments":
            print(f"[health] {msg}")
            sys.exit(1)

    if kind == "comments":
        from .comments import run_comments
        run_comments(cfg)
        return

    entry = {"time": dt.datetime.now(ZoneInfo(cfg.get("timezone", "Europe/Bucharest"))).isoformat(timespec="minutes"),
             "type": kind, "mode": mode, "slot": slot or None, "run_url": os.environ.get("RUN_URL")}
    failed = False
    cfg["_slot"] = slot
    try:
        if mode != "test" and not ok:
            raise RuntimeError(msg)
        entry.update(run_job(cfg, kind, mode))
    except BaseException as e:  # noqa: BLE001 - every failure must show up in the panel
        failed = True
        entry.update(status="error", error=redact(f"{type(e).__name__}: {e}")[:600])
        traceback.print_exc()
    finally:
        state = _load_state()
        retry = False
        if slot:
            tries = state.setdefault("attempts", {})
            tries[slot] = tries.get(slot, 0) + 1
            retry = failed and _retryable(entry.get("error", "")) and tries[slot] < 3
            if retry:
                entry["retry"] = f"se reîncearcă automat (încercarea {tries[slot]}/3)"
            else:
                state["done"].append(slot)
            state["attempts"] = {k: v for k, v in tries.items() if k not in state["done"][-50:]} | (
                {slot: tries[slot]} if retry else {})
        _save_state(state)
        entry = {k: v for k, v in entry.items() if v not in (None, "", [])}
        save_history(load_history(), entry)
        if os.environ.get("BLOB_READ_WRITE_TOKEN"):
            from .publish import blob_cleanup
            blob_cleanup("previews/", 3)
    print(json.dumps({k: entry.get(k) for k in ("type", "status", "hook", "permalink", "fb_link", "error", "retry")},
                     ensure_ascii=False))
    if failed:
        sys.exit(1)


# ====================================================================== local mode (optional)
def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"done": []}


def _save_state(state: dict) -> None:
    state["done"] = state["done"][-400:]
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run_forever(cfg: dict) -> None:
    from .due import due_slots
    from .instagram import check_connection
    from .setup_wizard import run_setup

    LOG_DIR.mkdir(exist_ok=True)
    if not all(os.environ.get(k) for k in ("GEMINI_API_KEY", "IG_USER_ID", "IG_ACCESS_TOKEN")):
        run_setup(cfg)
    print(f"✓ Connected to Instagram: @{check_connection(cfg)}. Leave this window open (Ctrl+C to stop).")
    last_comments = 0.0
    while True:
        cfg = load_config()
        state = _load_state()
        for kind, slot in due_slots(dt.datetime.now(dt.timezone.utc), state.get("done", [])):
            print(f"[{dt.datetime.now():%H:%M}] ▶ {kind} ({slot})")
            run_cloud_safe(cfg, kind, "scheduled", slot)
        if time.time() - last_comments > 3600:
            last_comments = time.time()
            run_cloud_safe(cfg, "comments", "scheduled", "")
        time.sleep(60)


def run_cloud_safe(cfg, kind, mode, slot):
    try:
        run_cloud(cfg, kind, mode, slot)
    except SystemExit:
        pass


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="autoposter", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("cloud")
    p.add_argument("--kind", default="reel", choices=["reel", "carousel", "story", "comments"])
    p.add_argument("--mode", default="test", choices=["test", "now", "scheduled"])
    p.add_argument("--slot", default="")
    sub.add_parser("demo")
    sub.add_parser("start")
    sub.add_parser("setup")
    args = ap.parse_args()
    cfg = load_config()
    try:
        if args.cmd == "cloud":
            run_cloud(cfg, args.kind, args.mode, args.slot)
        elif args.cmd == "demo":
            OUTPUT.mkdir(exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix="demo-"))
            out = render_reel(DEMO_REEL, cfg, OUTPUT / "demo-cinematic.mp4", work, 7)
            shutil.rmtree(work, ignore_errors=True)
            print(f"Video: {out}")
        elif args.cmd == "setup":
            from .setup_wizard import run_setup
            run_setup(cfg)
        else:
            run_forever(cfg)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
