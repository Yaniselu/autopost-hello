"""Replies to new comments on Instagram and on the Facebook Page.

Runs every hour as a tiny job (no video tools needed). All new comments of a run
are answered with ONE request to the cheap Flash-Lite model, to save tokens.
"""
import datetime as dt
import json
import os

import requests

from .config import DATA, env
from .instagram import InstagramError, _check
from .llm import generate, redact

STATE = DATA / "comments.json"

PROMPT = """You manage the comments of {name} ({handle}) on Instagram/Facebook.
About the brand: {description}
Tone: {tone}. Extra instructions: {extra}

Write a reply to each comment below. Rules:
- Reply in the SAME language as the comment. Short: max 25 words. Warm, human, specific to what they said.
- Questions about prices, offers, projects or support: answer briefly and invite them to send a DM.
- Never invent facts, prices or promises. No links. Max 1 emoji.
- Set "skip": true for spam, scams, hate, bots, or comments that need no answer.
Comments (JSON): {items}
Return ONLY JSON: {{"replies": [{{"id": "...", "skip": false, "reply": "..."}}]}}
"""


def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"replied": [], "log": []}


def _save(s):
    s["replied"] = s["replied"][-3000:]
    s["log"] = s["log"][-80:]
    STATE.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")


def _recent(ts: str, days=7) -> bool:
    try:
        t = dt.datetime.fromisoformat(ts.replace("+0000", "+00:00").replace("Z", "+00:00"))
        return (dt.datetime.now(dt.timezone.utc) - t).days < days
    except ValueError:
        return True


def _collect_ig(cfg, seen, me):
    base = f"https://graph.facebook.com/{cfg['instagram']['graph_version']}"
    token, user = env("IG_ACCESS_TOKEN"), env("IG_USER_ID")
    out = []
    media = _check(requests.get(f"{base}/{user}/media", params={
        "fields": "id,caption,timestamp,comments_count", "limit": 10, "access_token": token}, timeout=30))
    for m in media.get("data", []):
        if not m.get("comments_count") or not _recent(m.get("timestamp", ""), 14):
            continue
        cm = _check(requests.get(f"{base}/{m['id']}/comments", params={
            "fields": "id,text,username,timestamp,replies{username}", "limit": 50, "access_token": token}, timeout=30))
        for c in cm.get("data", []):
            replied_by_us = any((r.get("username") or "").lower() == me for r in (c.get("replies") or {}).get("data", []))
            if c["id"] in seen or replied_by_us or (c.get("username") or "").lower() == me or not _recent(c.get("timestamp", "")):
                continue
            out.append({"id": c["id"], "platform": "instagram", "user": c.get("username", ""),
                        "comment": (c.get("text") or "")[:400], "post": (m.get("caption") or "")[:160]})
    return out


def _collect_fb(cfg, seen):
    base = f"https://graph.facebook.com/{cfg['instagram']['graph_version']}"
    token, page = env("IG_ACCESS_TOKEN"), env("FB_PAGE_ID")
    out = []
    posts = _check(requests.get(f"{base}/{page}/posts", params={
        "fields": "id,message,created_time", "limit": 10, "access_token": token}, timeout=30))
    for p in posts.get("data", []):
        if not _recent(p.get("created_time", ""), 14):
            continue
        cm = _check(requests.get(f"{base}/{p['id']}/comments", params={
            "fields": "id,message,from,created_time,comments{from}", "filter": "toplevel", "limit": 50,
            "access_token": token}, timeout=30))
        for c in cm.get("data", []):
            frm = (c.get("from") or {}).get("id")
            ours = frm == page or any((r.get("from") or {}).get("id") == page for r in (c.get("comments") or {}).get("data", []))
            if c["id"] in seen or ours or not _recent(c.get("created_time", "")):
                continue
            out.append({"id": c["id"], "platform": "facebook", "user": (c.get("from") or {}).get("name", ""),
                        "comment": (c.get("message") or "")[:400], "post": (p.get("message") or "")[:160]})
    return out


def _keyword_hit(text: str, keyword: str) -> bool:
    import re
    return bool(keyword) and re.search(rf"(?<![\w]){re.escape(keyword)}(?![\w])", text or "", re.I) is not None


def _send_dm(cfg, item, message: str) -> None:
    """Private reply: a DM to the person who commented (Instagram & Facebook allow one per comment, within 7 days)."""
    base = f"https://graph.facebook.com/{cfg['instagram']['graph_version']}"
    sender = env("IG_USER_ID") if item["platform"] == "instagram" else env("FB_PAGE_ID")
    _check(requests.post(f"{base}/{sender}/messages", params={"access_token": env("IG_ACCESS_TOKEN")},
                         json={"recipient": {"comment_id": item["id"]}, "message": {"text": message}}, timeout=30))


def handle_dm_keywords(cfg: dict, items: list, state: dict) -> list:
    """Comments containing the keyword get a DM with the link + a short public reply. Returns the rest."""
    dm = cfg.get("dm") or {}
    if not dm.get("enabled") or not dm.get("keyword"):
        return items
    base = f"https://graph.facebook.com/{cfg['instagram']['graph_version']}"
    rest = []
    msg = (dm.get("message") or "Hi {name}! Here's the link to book your free demo: {link}")
    for it in items:
        if not _keyword_hit(it["comment"], dm["keyword"]):
            rest.append(it)
            continue
        text = msg.replace("{name}", (it.get("user") or "").split(" ")[0] or "there").replace("{link}", dm.get("link") or "")
        try:
            _send_dm(cfg, it, text)
            path = "replies" if it["platform"] == "instagram" else "comments"
            _check(requests.post(f"{base}/{it['id']}/{path}", data={"message": dm.get("public_reply") or "Just sent you a DM 📩",
                                                                    "access_token": env("IG_ACCESS_TOKEN")}, timeout=30))
            state["replied"].append(it["id"])
            state["log"].append({"time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                                 "platform": it["platform"], "user": it["user"], "comment": it["comment"][:200],
                                 "reply": "📩 DM: " + text[:180]})
            state["dms"] = state.get("dms", 0) + 1
            print(f"[comments] DM sent for keyword '{dm['keyword']}'")
        except InstagramError as e:
            print(f"[comments] DM failed ({redact(e)}) - answering normally")
            rest.append(it)
    return rest


def run_comments(cfg: dict) -> dict:
    opts = cfg.get("comments") or {}
    if not opts.get("enabled", True):
        print("[comments] disabled in the panel")
        return {"replied": 0}
    state = _load()
    seen = set(state["replied"])
    me = (cfg.get("instagram_username") or cfg["brand"]["handle"]).lstrip("@").lower()
    items = []
    try:
        items += _collect_ig(cfg, seen, me)
    except InstagramError as e:
        print(f"[comments] instagram: {redact(e)}")
    if os.environ.get("FB_PAGE_ID") and cfg.get("post_to_facebook", True):
        try:
            items += _collect_fb(cfg, seen)
        except InstagramError as e:
            print(f"[comments] facebook: {redact(e)}")
    items = handle_dm_keywords(cfg, items, state)
    items = items[: int(opts.get("max_per_run", 20))]
    if not items:
        _save(state)
        print("[comments] nothing new")
        return {"replied": 0}

    b = cfg["brand"]
    prompt = PROMPT.format(name=b["name"], handle=b["handle"], description=b["description"], tone=b["tone"],
                           extra=opts.get("instructions") or "none",
                           items=json.dumps([{k: i[k] for k in ("id", "user", "comment", "post")} for i in items],
                                            ensure_ascii=False))
    answers = generate(prompt, cfg, kind="light", validate=lambda o: o["replies"])
    by_id = {str(a.get("id")): a for a in answers.get("replies", [])}

    base = f"https://graph.facebook.com/{cfg['instagram']['graph_version']}"
    token = env("IG_ACCESS_TOKEN")
    done = 0
    for it in items:
        a = by_id.get(it["id"])
        state["replied"].append(it["id"])  # never look at the same comment twice
        if not a or a.get("skip") or not str(a.get("reply", "")).strip():
            continue
        reply = str(a["reply"]).strip()[:500]
        path = "replies" if it["platform"] == "instagram" else "comments"
        try:
            _check(requests.post(f"{base}/{it['id']}/{path}", data={"message": reply, "access_token": token}, timeout=30))
            done += 1
            state["log"].append({"time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                                 "platform": it["platform"], "user": it["user"], "comment": it["comment"][:200],
                                 "reply": reply})
        except InstagramError as e:
            print(f"[comments] reply failed: {redact(e)}")
    _save(state)
    print(f"[comments] replied to {done} of {len(items)} new comments")
    return {"replied": done}
