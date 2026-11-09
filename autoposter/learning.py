"""Learns from results: reads the stats of every post (views, reach, likes, comments, saves,
shares), joins them with what we know about how the post was made (style, topic, hook type,
hour) and turns that into decisions for the next posts + a report for the panel.

Needs the `instagram_manage_insights` permission for views/saves/shares; without it it
falls back to likes and comments (always available).
"""
import datetime as dt
import json
import math
import os
import random

import requests

from .config import DATA, env
from .llm import redact

PERF_FILE = DATA / "performance.json"
INSIGHTS_FILE = DATA / "insights.json"
METRICS = ["views", "reach", "likes", "comments", "saved", "shares", "total_interactions"]


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def score(m: dict) -> float:
    """One number per post: reach matters, saves/shares (what the algorithm loves) matter most."""
    views = m.get("views") or m.get("reach") or 0
    return (math.log1p(views) * 25 + 6 * (m.get("shares") or 0) + 5 * (m.get("saved") or 0)
            + 3 * (m.get("comments") or 0) + 1 * (m.get("likes") or 0))


def _fetch_metrics(cfg, media_id: str, token: str) -> dict:
    base = f"https://graph.facebook.com/{cfg['instagram']['graph_version']}"
    out = {}
    r = requests.get(f"{base}/{media_id}/insights", params={"metric": ",".join(METRICS), "access_token": token}, timeout=30)
    data = r.json()
    if r.ok and "data" in data:
        for row in data["data"]:
            vals = row.get("values") or [{}]
            out[row["name"]] = vals[0].get("value", 0) if vals else row.get("total_value", {}).get("value", 0)
    else:  # no insights permission or metric not supported for this media type -> basic counters
        b = requests.get(f"{base}/{media_id}", params={"fields": "like_count,comments_count", "access_token": token},
                         timeout=30).json()
        out = {"likes": b.get("like_count", 0), "comments": b.get("comments_count", 0), "_basic": True}
    return out


def update_performance(cfg: dict, history: list, max_age_hours: float = 12) -> dict:
    """Refreshes stats for our posts (recent ones twice a day, old ones once) -> data/performance.json."""
    perf = _load(PERF_FILE, {})
    if not (os.environ.get("IG_ACCESS_TOKEN") and (cfg.get("learning") or {}).get("enabled", True)):
        return perf
    token = env("IG_ACCESS_TOKEN")
    now = dt.datetime.now(dt.timezone.utc)
    n = 0
    for h in history:
        mid = h.get("ig_id") or h.get("media_id")
        if h.get("status") != "posted" or not mid:
            continue
        old = perf.get(mid)
        try:
            posted = dt.datetime.fromisoformat(h["time"])
        except (KeyError, ValueError):
            continue
        age_days = (now - posted).days
        if old and (age_days > 14 or (now - dt.datetime.fromisoformat(old["fetched"])).total_seconds() < max_age_hours * 3600):
            continue
        try:
            m = _fetch_metrics(cfg, mid, token)
        except Exception as e:  # noqa: BLE001
            print(f"[learning] {mid}: {redact(e)}")
            continue
        perf[mid] = {"fetched": now.isoformat(), "metrics": m, "score": round(score(m), 2),
                     "type": h.get("type", "reel"), "style": h.get("style"), "pillar": h.get("pillar"),
                     "hook_type": h.get("hook_type"), "hook": h.get("hook"), "hour": posted.strftime("%H:%M"),
                     "time": h["time"], "permalink": h.get("permalink")}
        n += 1
        if n >= 40:
            break
    PERF_FILE.write_text(json.dumps(perf, indent=1, ensure_ascii=False), encoding="utf-8")
    if n:
        print(f"[learning] updated stats for {n} posts")
    build_insights(perf)
    return perf


def _group(rows, key, min_n=1):
    g = {}
    for r in rows:
        k = r.get(key)
        if k:
            g.setdefault(k, []).append(r["score"])
    return {k: {"avg": round(sum(v) / len(v), 1), "n": len(v)} for k, v in g.items() if len(v) >= min_n}


def build_insights(perf: dict) -> dict:
    rows = [p for p in perf.values() if "score" in p]
    reels = [r for r in rows if r.get("type") == "reel"]
    ins = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "posts_measured": len(rows),
        "basic_only": any(r["metrics"].get("_basic") for r in rows),
        "by_type": _group(rows, "type"), "by_style": _group(reels, "style"),
        "by_pillar": _group(rows, "pillar"), "by_hook_type": _group(reels, "hook_type"),
        "by_hour": _group(rows, "hour"),
        "top_posts": [{k: r.get(k) for k in ("hook", "type", "style", "score", "permalink", "metrics")}
                      for r in sorted(rows, key=lambda r: r["score"], reverse=True)[:5]],
    }
    hours = sorted(((v["avg"], h) for h, v in ins["by_hour"].items() if v["n"] >= 2), reverse=True)
    ins["recommended_hours"] = [h for _, h in hours[:4]]
    INSIGHTS_FILE.write_text(json.dumps(ins, indent=1, ensure_ascii=False), encoding="utf-8")
    return ins


def insights() -> dict:
    return _load(INSIGHTS_FILE, {})


# ---------------------------------------------------------------- decisions
def _best(group: dict, min_n: int):
    ok = [(v["avg"], k) for k, v in group.items() if v["n"] >= min_n]
    return max(ok)[1] if ok else None


def choose_pillar(pillars: list, default: str, rng: random.Random) -> str:
    """70% of the time pick among the best-scoring topics, 30% keep exploring (rotation)."""
    by = insights().get("by_pillar", {})
    scored = sorted(((v["avg"], p) for p, v in by.items() if p in pillars and v["n"] >= 2), reverse=True)
    if len(scored) >= 3 and rng.random() < 0.7:
        return rng.choice([p for _, p in scored[:3]])
    return default


def choose_hook(options: list, llm_best: int, rng: random.Random) -> int:
    """Picks the hook whose *type* performed best so far; explores 35% of the time."""
    by = insights().get("by_hook_type", {})
    best_type = _best(by, 2)
    if best_type and rng.random() > 0.35:
        for i, o in enumerate(options):
            if o.get("type") == best_type:
                return i
    return llm_best if 0 <= llm_best < len(options) else 0


def style_bias() -> str | None:
    """The reel style that clearly wins (>=30% better with >=4 posts each), if any."""
    by = insights().get("by_style", {})
    if len(by) < 2 or any(v["n"] < 4 for v in by.values()):
        return None
    (a, sa), (b, sb) = sorted(((k, v["avg"]) for k, v in by.items()), key=lambda x: -x[1])[:2]
    return a if sa >= sb * 1.3 else None


def prompt_notes() -> str:
    """Short summary of what works, injected into the writing prompt."""
    ins = insights()
    if not ins.get("top_posts"):
        return "(not enough data yet)"
    lines = [f"- top post: \"{(p.get('hook') or '').replace('*', '')}\" ({p.get('type')}, score {p.get('score')})"
             for p in ins["top_posts"][:3]]
    bh = _best(ins.get("by_hook_type", {}), 2)
    if bh:
        lines.append(f"- hook type that performs best: {bh}")
    bp = _best(ins.get("by_pillar", {}), 2)
    if bp:
        lines.append(f"- best topic: {bp}")
    return "\n".join(lines)
